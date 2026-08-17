"""Persistência do log de execução do pipeline de pregão (`execucao_pipeline`,
migração 007). Não decide nada: só registra o que aconteceu.

POR QUE A LINHA ABRE ANTES DO TRABALHO
--------------------------------------
`iniciar()` grava `status='executando'` e **commita na hora**, numa transação
própria. É o oposto do instinto de gravar só no fim, e é deliberado: um
processo morto no meio (OOM, `kill -9`, máquina desligada) não executa
nenhum código de finalização. Se a linha só existisse ao final, esse caso
não deixaria rastro nenhum — indistinguível de "o timer nunca disparou".

Com a linha aberta antes, um crash duro deixa `status='executando'` com
`encerrado_em` nulo. Isso é o rastro. `orfas()` acha essas linhas, e é o que
permite a Fase 5 alertar "o pipeline morreu" em vez de "o pipeline sumiu".

O CUSTO DISSO, DECLARADO
------------------------
Duas escritas por execução em vez de uma. Com um disparo a cada 30 min em
pregão são ~14 linhas e ~28 escritas por dia — irrelevante perto do que se
ganha em poder responder "rodou?".

O QUE ISTO NÃO COBRE
--------------------
Se o banco estiver fora do ar, `iniciar()` falha e não há linha nenhuma. Um
log que depende do banco não consegue registrar a queda do próprio banco —
por isso a Fase 5 do plano pede um alerta de "não rodou hoje" por um caminho
que NÃO passa por aqui. Está anotado para não virar falsa sensação de
cobertura.
"""
import datetime as dt
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from src.db.connection import get_connection
from src.observability.logging import sanitizar_texto

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

#: Espelham o CHECK `execucao_pipeline_status_valido` da migração 007. Ficam
#: aqui para o erro aparecer em Python com nome de constante, e não como
#: violação de constraint crua vinda do Postgres.
EXECUTANDO = "executando"
EXECUTADO = "executado"
PULADO = "pulado_fora_de_pregao"
FALHOU = "falhou"
PARCIAL = "parcial"
PULADO_GERAL = "pulado"
ORFA = "orfa"

_FINAIS = (EXECUTADO, PARCIAL, PULADO_GERAL, PULADO, FALHOU, ORFA)

ETAPA_EXECUTANDO = "executando"
ETAPA_SUCESSO = "sucesso"
ETAPA_PARCIAL = "parcial"
ETAPA_FALHA = "falha"
ETAPA_BLOQUEADO = "bloqueado"
ETAPA_PULADO = "pulado"
_ETAPA_FINAIS = (
    ETAPA_SUCESSO, ETAPA_PARCIAL, ETAPA_FALHA, ETAPA_BLOQUEADO, ETAPA_PULADO,
)


@dataclass(frozen=True)
class RegistroExecucao:
    id: int
    execution_id: uuid.UUID
    ambiente: str
    tipo_fluxo: str
    janela_logica: str
    status: str
    gatilho: str
    iniciado_em: dt.datetime
    heartbeat_em: dt.datetime
    encerrado_em: dt.datetime | None
    detalhe: dict[str, Any]
    erro_sanitizado: str | None


@dataclass(frozen=True)
class AquisicaoExecucao:
    execucao: RegistroExecucao
    adquirida: bool

    @property
    def duplicada(self) -> bool:
        return not self.adquirida


@dataclass(frozen=True)
class TentativaEtapa:
    id: int
    execution_id: uuid.UUID
    etapa: str
    tentativa: int
    status: str
    iniciado_em: dt.datetime
    encerrado_em: dt.datetime | None
    alvos_tentados: int
    alvos_persistidos: int
    alvos_falhos: int
    alvos_nao_executados: int
    detalhe: dict[str, Any]
    erro_sanitizado: str | None


_COLUNAS_EXECUCAO = (
    "id, execution_id, ambiente, tipo_fluxo, janela_logica, status, gatilho, "
    "iniciado_em, heartbeat_em, encerrado_em, detalhe, erro_sanitizado"
)
_COLUNAS_ETAPA = (
    "id, execution_id, etapa, tentativa, status, iniciado_em, encerrado_em, "
    "alvos_tentados, alvos_persistidos, alvos_falhos, alvos_nao_executados, "
    "detalhe, erro_sanitizado"
)


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


def _registro_execucao(row) -> RegistroExecucao:
    detalhe = row[10]
    if isinstance(detalhe, str):
        detalhe = json.loads(detalhe)
    return RegistroExecucao(
        id=row[0], execution_id=row[1], ambiente=row[2], tipo_fluxo=row[3],
        janela_logica=row[4], status=row[5], gatilho=row[6], iniciado_em=row[7],
        heartbeat_em=row[8], encerrado_em=row[9], detalhe=detalhe or {},
        erro_sanitizado=row[11],
    )


def _tentativa_etapa(row) -> TentativaEtapa:
    detalhe = row[11]
    if isinstance(detalhe, str):
        detalhe = json.loads(detalhe)
    return TentativaEtapa(
        id=row[0], execution_id=row[1], etapa=row[2], tentativa=row[3],
        status=row[4], iniciado_em=row[5], encerrado_em=row[6],
        alvos_tentados=row[7], alvos_persistidos=row[8], alvos_falhos=row[9],
        alvos_nao_executados=row[10], detalhe=detalhe or {},
        erro_sanitizado=row[12],
    )


class RepositorioExecucao:
    """Estado transacional de uma execução lógica e suas etapas."""

    def adquirir(
        self, ambiente: str, tipo_fluxo: str, janela_logica: str,
        gatilho: str = "manual",
    ) -> AquisicaoExecucao:
        """Insere a chave lógica uma vez ou devolve a execução concorrente."""
        if not ambiente or not tipo_fluxo or not janela_logica:
            raise ValueError("ambiente, tipo_fluxo e janela_logica são obrigatórios")
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO execucao_pipeline (
                    ambiente, tipo_fluxo, janela_logica, status, gatilho
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ambiente, tipo_fluxo, janela_logica) DO NOTHING
                RETURNING {_COLUNAS_EXECUCAO}
                """,
                (ambiente, tipo_fluxo, janela_logica, EXECUTANDO, gatilho),
            )
            row = cur.fetchone()
            adquirida = row is not None
            if row is None:
                cur.execute(
                    f"SELECT {_COLUNAS_EXECUCAO} FROM execucao_pipeline "
                    "WHERE ambiente = %s AND tipo_fluxo = %s AND janela_logica = %s",
                    (ambiente, tipo_fluxo, janela_logica),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:  # pragma: no cover - a constraint garante a linha
            raise RuntimeError("execução lógica não foi adquirida nem encontrada")
        return AquisicaoExecucao(_registro_execucao(row), adquirida)

    def obter(self, execution_id: uuid.UUID | str) -> RegistroExecucao | None:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUNAS_EXECUCAO} FROM execucao_pipeline "
                "WHERE execution_id = %s",
                (execution_id,),
            )
            row = cur.fetchone()
        return _registro_execucao(row) if row else None

    def obter_por_chave(
        self, ambiente: str, tipo_fluxo: str, janela_logica: str,
    ) -> RegistroExecucao | None:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUNAS_EXECUCAO} FROM execucao_pipeline "
                "WHERE ambiente = %s AND tipo_fluxo = %s AND janela_logica = %s",
                (ambiente, tipo_fluxo, janela_logica),
            )
            row = cur.fetchone()
        return _registro_execucao(row) if row else None

    def tentativas(
        self, execution_id: uuid.UUID | str,
    ) -> list[TentativaEtapa]:
        """Histórico de etapas na ordem em que foram abertas."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUNAS_ETAPA} FROM execucao_etapa_tentativa "
                "WHERE execution_id = %s ORDER BY iniciado_em, id",
                (execution_id,),
            )
            rows = cur.fetchall()
        return [_tentativa_etapa(row) for row in rows]

    def reativar(
        self, execution_id: uuid.UUID | str, *, minutos_sem_heartbeat: int = 60,
    ) -> RegistroExecucao:
        """Retoma falha/parcial/órfã ou execução ativa com heartbeat expirado.

        A condição fica no próprio UPDATE para dois operadores não retomarem a
        mesma execução ao mesmo tempo. Uma execução ativa e recente continua
        pertencendo ao processo original.
        """
        if minutos_sem_heartbeat <= 0:
            raise ValueError("minutos_sem_heartbeat deve ser positivo")
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE execucao_pipeline
                SET status = %s, encerrado_em = NULL, heartbeat_em = now(),
                    erro_sanitizado = NULL,
                    detalhe = detalhe || '{{"retomada": true}}'::jsonb
                WHERE execution_id = %s
                  AND (
                    status IN (%s, %s, %s)
                    OR (status = %s AND heartbeat_em <
                        now() - make_interval(mins => %s))
                  )
                RETURNING {_COLUNAS_EXECUCAO}
                """,
                (EXECUTANDO, execution_id, FALHOU, ORFA, PARCIAL, EXECUTANDO,
                 minutos_sem_heartbeat),
            )
            row = cur.fetchone()
            conn.commit()
        if row is None:
            existente = self.obter(execution_id)
            if existente is None:
                raise ValueError("execução inexistente")
            raise ValueError(
                f"execução {existente.status!r} não pode ser retomada; "
                "se ainda está ativa, aguarde o heartbeat expirar"
            )
        return _registro_execucao(row)

    def heartbeat(self, execution_id: uuid.UUID | str) -> RegistroExecucao:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE execucao_pipeline SET heartbeat_em = now() "
                f"WHERE execution_id = %s AND status = %s RETURNING {_COLUNAS_EXECUCAO}",
                (execution_id, EXECUTANDO),
            )
            row = cur.fetchone()
            conn.commit()
        if row is None:
            raise ValueError("execução inexistente ou já encerrada")
        return _registro_execucao(row)

    def finalizar(
        self, execution_id: uuid.UUID | str, status: str,
        detalhe: Mapping[str, Any] | None = None, erro: BaseException | str | None = None,
    ) -> RegistroExecucao:
        if status not in _FINAIS:
            raise ValueError(f"status final inválido: {status!r}")
        erro_limpo = sanitizar_texto(str(erro)) if erro is not None else None
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE execucao_pipeline
                SET status = %s, encerrado_em = now(), heartbeat_em = now(),
                    detalhe = %s, erro_sanitizado = %s
                WHERE execution_id = %s AND status = %s
                RETURNING {_COLUNAS_EXECUCAO}
                """,
                (status, _json(dict(detalhe or {})), erro_limpo, execution_id, EXECUTANDO),
            )
            row = cur.fetchone()
            conn.commit()
        if row is None:
            existente = self.obter(execution_id)
            if existente is None:
                raise ValueError("execução inexistente")
            if existente.status == status:
                return existente
            raise ValueError(f"execução já encerrada como {existente.status!r}")
        return _registro_execucao(row)

    def iniciar_etapa(
        self, execution_id: uuid.UUID | str, etapa: str,
        detalhe: Mapping[str, Any] | None = None,
    ) -> TentativaEtapa:
        """Numera a tentativa sob lock da linha da execução, não da sessão."""
        if not etapa:
            raise ValueError("etapa é obrigatória")
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM execucao_pipeline WHERE execution_id = %s FOR UPDATE",
                (execution_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("execução inexistente")
            if row[0] != EXECUTANDO:
                raise ValueError(f"execução não está ativa: {row[0]!r}")
            cur.execute(
                "SELECT COALESCE(MAX(tentativa), 0) + 1 "
                "FROM execucao_etapa_tentativa WHERE execution_id = %s AND etapa = %s",
                (execution_id, etapa),
            )
            tentativa = cur.fetchone()[0]
            cur.execute(
                f"""
                INSERT INTO execucao_etapa_tentativa (
                    execution_id, etapa, tentativa, status, detalhe
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING {_COLUNAS_ETAPA}
                """,
                (execution_id, etapa, tentativa, ETAPA_EXECUTANDO,
                 _json(dict(detalhe or {}))),
            )
            tentativa_row = cur.fetchone()
            cur.execute(
                "UPDATE execucao_pipeline SET heartbeat_em = now() WHERE execution_id = %s",
                (execution_id,),
            )
            conn.commit()
        return _tentativa_etapa(tentativa_row)

    def concluir_etapa(
        self, execution_id: uuid.UUID | str, etapa: str, tentativa: int,
        status: str = ETAPA_SUCESSO, *, alvos_tentados: int = 0,
        alvos_persistidos: int = 0, alvos_falhos: int = 0,
        alvos_nao_executados: int = 0,
        detalhe: Mapping[str, Any] | None = None,
        erro: BaseException | str | None = None,
    ) -> TentativaEtapa:
        if status not in _ETAPA_FINAIS:
            raise ValueError(f"status final de etapa inválido: {status!r}")
        contagens = (
            alvos_tentados, alvos_persistidos, alvos_falhos, alvos_nao_executados,
        )
        if any(valor < 0 for valor in contagens):
            raise ValueError("contagens da etapa não podem ser negativas")
        erro_limpo = sanitizar_texto(str(erro)) if erro is not None else None
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE execucao_etapa_tentativa
                SET status = %s, encerrado_em = now(), alvos_tentados = %s,
                    alvos_persistidos = %s, alvos_falhos = %s,
                    alvos_nao_executados = %s, detalhe = %s, erro_sanitizado = %s
                WHERE execution_id = %s AND etapa = %s AND tentativa = %s
                  AND status = %s
                RETURNING {_COLUNAS_ETAPA}
                """,
                (status, *contagens, _json(dict(detalhe or {})), erro_limpo,
                 execution_id, etapa, tentativa, ETAPA_EXECUTANDO),
            )
            row = cur.fetchone()
            cur.execute(
                "UPDATE execucao_pipeline SET heartbeat_em = now() "
                "WHERE execution_id = %s AND status = %s",
                (execution_id, EXECUTANDO),
            )
            conn.commit()
        if row is None:
            raise ValueError("tentativa inexistente ou já encerrada")
        return _tentativa_etapa(row)

    def falhar_etapa(
        self, execution_id: uuid.UUID | str, etapa: str, tentativa: int,
        erro: BaseException | str, **kwargs: Any,
    ) -> TentativaEtapa:
        return self.concluir_etapa(
            execution_id, etapa, tentativa, ETAPA_FALHA, erro=erro, **kwargs,
        )

    def interromper_etapa(
        self, execution_id: uuid.UUID | str, etapa: str, tentativa: int,
        motivo: str,
    ) -> TentativaEtapa:
        """Fecha a tentativa deixada aberta por crash antes de uma retomada."""
        return self.falhar_etapa(
            execution_id, etapa, tentativa, motivo,
            detalhe={"interrompida_por_resume": True},
        )

    def classificar_orfas(self, minutos: int = 60) -> list[RegistroExecucao]:
        if minutos <= 0:
            raise ValueError("minutos deve ser positivo")
        erro = f"heartbeat ausente há mais de {minutos} minuto(s)"
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE execucao_pipeline
                SET status = %s, encerrado_em = now(), erro_sanitizado = %s
                WHERE status = %s
                  AND heartbeat_em < now() - make_interval(mins => %s)
                RETURNING {_COLUNAS_EXECUCAO}
                """,
                (ORFA, erro, EXECUTANDO, minutos),
            )
            rows = cur.fetchall()
            conn.commit()
        return [_registro_execucao(row) for row in rows]


def iniciar(gatilho: str = "manual") -> int:
    """Abre a execução e devolve o id. Commita imediatamente — ver cabeçalho."""
    janela = f"legacy:{uuid.uuid4()}"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO execucao_pipeline ("
            "ambiente, tipo_fluxo, janela_logica, status, gatilho"
            ") VALUES (%s, %s, %s, %s, %s) "
            "RETURNING id",
            (os.getenv("OPCOES_IA_ENV", "local"), "intraday", janela,
             EXECUTANDO, gatilho),
        )
        execucao_id = cur.fetchone()[0]
        conn.commit()
    return execucao_id


def concluir(execucao_id: int, status: str, detalhe: dict[str, Any] | None = None) -> None:
    """Fecha a execução com o status final e o detalhe por etapa."""
    if status not in _FINAIS:
        raise ValueError(
            f"status final inválido: {status!r}. Esperado um de {_FINAIS} — "
            f"{EXECUTANDO!r} é estado de abertura, não de encerramento."
        )
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE execucao_pipeline SET status = %s, encerrado_em = now(), "
            "detalhe = %s WHERE id = %s",
            (status, json.dumps(detalhe or {}, ensure_ascii=False, default=str), execucao_id),
        )
        conn.commit()


def _row(row) -> dict[str, Any]:
    id_, iniciado, encerrado, status, gatilho, detalhe = row
    if isinstance(detalhe, str):
        detalhe = json.loads(detalhe)
    return {
        "id": id_,
        "iniciado_em": iniciado,
        "encerrado_em": encerrado,
        "status": status,
        "gatilho": gatilho,
        "detalhe": detalhe or {},
        # Derivado na leitura em vez de coluna: guardar duração gravaria duas
        # vezes a mesma informação, e as duas poderiam divergir.
        "duracao_s": (encerrado - iniciado).total_seconds() if encerrado else None,
    }


_SELECT = (
    "SELECT id, iniciado_em, encerrado_em, status, gatilho, detalhe "
    "FROM execucao_pipeline "
)


def ultimas(limite: int = 20, cur=None) -> list[dict[str, Any]]:
    """As execuções mais recentes, da mais nova para a mais antiga.

    Aceita um cursor para poder ser chamada de dentro de uma leitura já
    aberta (é o que a API faz), e abre conexão própria quando não recebe.
    """
    sql = _SELECT + "ORDER BY iniciado_em DESC LIMIT %s"
    if cur is not None:
        cur.execute(sql, (limite,))
        return [_row(r) for r in cur.fetchall()]
    with get_connection() as conn, conn.cursor() as c:
        c.execute(sql, (limite,))
        return [_row(r) for r in c.fetchall()]


def orfas(minutos: int = 60, cur=None) -> list[dict[str, Any]]:
    """Execuções abertas há mais de `minutos` e nunca encerradas.

    Cada uma é um processo que morreu sem executar o encerramento. O corte
    por tempo existe para não confundir isso com a execução que está em
    curso agora — uma rodada normal leva segundos, não uma hora.
    """
    sql = (
        _SELECT + "WHERE status = %s AND encerrado_em IS NULL "
        "AND iniciado_em < now() - make_interval(mins => %s) "
        "ORDER BY iniciado_em DESC"
    )
    if cur is not None:
        cur.execute(sql, (EXECUTANDO, minutos))
        return [_row(r) for r in cur.fetchall()]
    with get_connection() as conn, conn.cursor() as c:
        c.execute(sql, (EXECUTANDO, minutos))
        return [_row(r) for r in c.fetchall()]


def ultima_conclusao(cur=None) -> dict[str, Any] | None:
    """A execução encerrada mais recente, qualquer que tenha sido o desfecho.

    É o que responde "quando isto rodou pela última vez, e no que deu" — a
    pergunta que hoje `/saude-coleta` não consegue responder.
    """
    sql = _SELECT + "WHERE encerrado_em IS NOT NULL ORDER BY encerrado_em DESC LIMIT 1"
    if cur is not None:
        cur.execute(sql)
        row = cur.fetchone()
        return _row(row) if row else None
    with get_connection() as conn, conn.cursor() as c:
        c.execute(sql)
        row = c.fetchone()
        return _row(row) if row else None


def rodou_em(data: dt.date, cur=None) -> bool:
    """Se houve ao menos uma execução CONCLUÍDA na data (UTC, convenção do
    projeto). Pulo por fora-de-pregão conta: o pipeline acordou e decidiu."""
    sql = (
        "SELECT EXISTS (SELECT 1 FROM execucao_pipeline "
        "WHERE iniciado_em::date = %s AND status <> %s)"
    )
    if cur is not None:
        cur.execute(sql, (data, EXECUTANDO))
        return bool(cur.fetchone()[0])
    with get_connection() as conn, conn.cursor() as c:
        c.execute(sql, (data, EXECUTANDO))
        return bool(c.fetchone()[0])
