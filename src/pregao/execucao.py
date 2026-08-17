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
from typing import Any

from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

#: Espelham o CHECK `execucao_pipeline_status_valido` da migração 007. Ficam
#: aqui para o erro aparecer em Python com nome de constante, e não como
#: violação de constraint crua vinda do Postgres.
EXECUTANDO = "executando"
EXECUTADO = "executado"
PULADO = "pulado_fora_de_pregao"
FALHOU = "falhou"

_FINAIS = (EXECUTADO, PULADO, FALHOU)


def iniciar(gatilho: str = "manual") -> int:
    """Abre a execução e devolve o id. Commita imediatamente — ver cabeçalho."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO execucao_pipeline (status, gatilho) VALUES (%s, %s) "
            "RETURNING id",
            (EXECUTANDO, gatilho),
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
