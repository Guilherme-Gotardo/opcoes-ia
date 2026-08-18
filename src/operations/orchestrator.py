"""Orquestrador único, durável e retomável dos fluxos operacionais.

Cada etapa é concluída em uma transação própria antes da próxima começar.
Chamadas externas nunca acontecem antes da aquisição da chave lógica no banco.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src.etl.policy import agregar
from src.etl.result import (
    DetalheAlvo,
    EstadoAlvo,
    EstadoColeta,
    ResultadoColeta,
)
from src.observability.logging import log_context, set_log_context
from src.observability.metrics import (
    emit_execution,
    emit_operational_alert,
    emit_source,
    emit_stage,
)
from src.pregao import execucao

log = logging.getLogger("operations")

FUSO_OPERACIONAL = ZoneInfo("America/Sao_Paulo")
INTERVALO_INTRADAY_MINUTOS = 30

ETAPA_CALENDARIO = "calendario"
ETAPA_COTACOES = "coleta_cotacoes"
ETAPA_CANDLES_1H = "coleta_candles_1h"
ETAPA_CANDLES_1D = "coleta_candles_1d"
ETAPA_OPCOES = "coleta_opcoes"
ETAPA_NOTICIAS = "coleta_noticias"
ETAPA_EARNINGS = "earnings"
ETAPA_POLITICA = "politica_coleta"
ETAPA_AVALIACAO = "avaliacao_deterministica"
ETAPA_QUANT = "enriquecimento_quantitativo"
ETAPA_RELATORIO = "relatorio_deterministico"
ETAPA_AGENTE = "relatorio_anthropic"
ETAPA_NOTIFICACAO = "notificacao"
ETAPA_ALERTA_VERIFICACAO = "verificacao_alerta"
ETAPA_ALERTA_NOTIFICACAO = "notificacao_alerta"

ETAPAS_EXTERNAS = frozenset({
    ETAPA_COTACOES,
    ETAPA_CANDLES_1H,
    ETAPA_CANDLES_1D,
    ETAPA_OPCOES,
    ETAPA_NOTICIAS,
    ETAPA_EARNINGS,
    ETAPA_QUANT,  # consulta a taxa BCB antes do cálculo local
    ETAPA_AGENTE,
    ETAPA_NOTIFICACAO,
    ETAPA_ALERTA_NOTIFICACAO,
})

_ETAPAS_CONCLUIDAS = frozenset({
    execucao.ETAPA_SUCESSO,
    execucao.ETAPA_PARCIAL,
    execucao.ETAPA_BLOQUEADO,
    execucao.ETAPA_PULADO,
})


@dataclass(frozen=True)
class ResultadoOperacao:
    codigo_saida: int
    status: str
    execution_id: str | None
    janela_logica: str
    detalhe: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultadoEtapaOperacional:
    status: str = execucao.ETAPA_SUCESSO
    detalhe: dict[str, Any] = field(default_factory=dict)
    alvos_tentados: int = 0
    alvos_persistidos: int = 0
    alvos_falhos: int = 0
    alvos_nao_executados: int = 0
    payload: Any = None
    degrada_execucao: bool = False


class FalhaCritica(RuntimeError):
    pass


class ResumeRecusado(RuntimeError):
    pass


def janela_logica(
    tipo_fluxo: str, agora: dt.datetime | None = None, fornecida: str | None = None,
) -> str:
    if fornecida:
        return fornecida
    agora = agora or dt.datetime.now(dt.timezone.utc)
    if agora.tzinfo is None:
        raise ValueError("agora precisa ter fuso horário")
    local = agora.astimezone(FUSO_OPERACIONAL)
    if tipo_fluxo == "intraday":
        minuto = local.minute - local.minute % INTERVALO_INTRADAY_MINUTOS
        return local.replace(minute=minuto, second=0, microsecond=0).isoformat(
            timespec="minutes"
        )
    if tipo_fluxo in {"daily", "alert"}:
        return local.date().isoformat()
    raise ValueError(f"tipo de fluxo desconhecido: {tipo_fluxo!r}")


def _status_coleta(estado: EstadoColeta) -> str:
    return {
        EstadoColeta.SUCESSO: execucao.ETAPA_SUCESSO,
        EstadoColeta.PARCIAL: execucao.ETAPA_PARCIAL,
        EstadoColeta.FALHA: execucao.ETAPA_FALHA,
        EstadoColeta.BLOQUEADO: execucao.ETAPA_BLOQUEADO,
        EstadoColeta.PULADO: execucao.ETAPA_PULADO,
    }[estado]


def _etapa_de_coleta(
    resultado: ResultadoColeta, *, degrada_execucao: bool = False,
) -> ResultadoEtapaOperacional:
    return ResultadoEtapaOperacional(
        status=_status_coleta(resultado.estado),
        detalhe={"resultado_coleta": resultado.como_dict()},
        alvos_tentados=resultado.alvos_tentados,
        alvos_persistidos=resultado.registros_persistidos,
        alvos_falhos=resultado.alvos_falhos,
        alvos_nao_executados=resultado.alvos_nao_executados,
        payload=resultado,
        degrada_execucao=degrada_execucao,
    )


def _coleta_do_dict(valor: dict[str, Any]) -> ResultadoColeta:
    detalhes = tuple(
        DetalheAlvo(
            ticker=item["ticker"],
            estado=EstadoAlvo(item["estado"]),
            registros_persistidos=item.get("registros_persistidos", 0),
            codigo_motivo=item.get("codigo_motivo"),
            detalhe=item.get("detalhe"),
            tentado=item.get("tentado", True),
        )
        for item in valor.get("detalhes", [])
    )
    return ResultadoColeta(
        coletor=valor["coletor"],
        fonte=valor["fonte"],
        estado=EstadoColeta(valor["estado"]),
        detalhes=detalhes,
        motivo=valor.get("motivo"),
        contexto=valor.get("contexto") or {},
    )


def _serializar_avaliacoes(resultados: list) -> list[dict[str, Any]]:
    return [
        {
            "ticker_objeto": item.ticker_objeto,
            "codigo_opcao": item.codigo_opcao,
            "tipo_operacao": item.tipo_operacao,
            "elegivel": item.elegivel,
            "strike": item.strike,
            "vencimento": item.vencimento,
            "premio_estimado": item.premio_estimado,
            "preco_mercado": item.preco_mercado,
            "cotacao_em": item.cotacao_em,
            "vereditos": item.criterios_json(),
        }
        for item in resultados
    ]


def _avaliacoes_para_quant(itens: list[dict[str, Any]]) -> list[SimpleNamespace]:
    return [SimpleNamespace(**item) for item in itens]


def _data_da_janela(janela: str, agora: dt.datetime) -> dt.date:
    try:
        return dt.date.fromisoformat(janela[:10])
    except ValueError:
        return agora.astimezone(FUSO_OPERACIONAL).date()


class Orquestrador:
    def __init__(
        self, tipo_fluxo: str, janela: str, gatilho: str, *,
        repo: execucao.RepositorioExecucao | None = None,
        resume: bool = False,
        repetir_etapas_externas: frozenset[str] = frozenset(),
        minutos_resume: int = 60,
    ) -> None:
        self.tipo_fluxo = tipo_fluxo
        self.janela = janela
        self.gatilho = gatilho
        self.repo = repo or execucao.RepositorioExecucao()
        self.resume = resume
        self.repetir_etapas_externas = repetir_etapas_externas
        self.minutos_resume = minutos_resume
        self.execution_id: str | None = None
        self.iniciado_monotonic = time.monotonic()
        self.latest: dict[str, execucao.TentativaEtapa] = {}
        self.parcial = False

    def adquirir(self) -> ResultadoOperacao | None:
        ambiente = os.getenv("OPCOES_IA_ENV", "local")
        aquisicao = self.repo.adquirir(
            ambiente, self.tipo_fluxo, self.janela, self.gatilho,
        )
        registro = aquisicao.execucao
        self.execution_id = str(registro.execution_id)
        set_log_context(execution_id=self.execution_id)
        if aquisicao.adquirida:
            return None
        if not self.resume:
            log.info(
                "Execução lógica duplicada; nenhum efeito será repetido.",
                extra={"result": "duplicada", "details": {
                    "tipo_fluxo": self.tipo_fluxo, "janela_logica": self.janela,
                }},
            )
            return ResultadoOperacao(
                0, "duplicada", self.execution_id, self.janela,
                {"status_existente": registro.status},
            )
        if registro.status in {
            execucao.EXECUTADO, execucao.PULADO, execucao.PULADO_GERAL,
        }:
            return ResultadoOperacao(
                0, "duplicada", self.execution_id, self.janela,
                {"status_existente": registro.status},
            )

        tentativas = self.repo.tentativas(registro.execution_id)
        self.latest = {item.etapa: item for item in tentativas}
        ambiguas = [
            item.etapa for item in self.latest.values()
            if item.status == execucao.ETAPA_EXECUTANDO
            and item.etapa in ETAPAS_EXTERNAS
            and item.etapa not in self.repetir_etapas_externas
        ]
        if ambiguas:
            raise ResumeRecusado(
                "etapa(s) externa(s) em estado ambíguo: "
                f"{', '.join(sorted(ambiguas))}; repita com "
                "--allow-external-retry ETAPA após verificar o efeito no provedor"
            )

        self.repo.reativar(
            registro.execution_id, minutos_sem_heartbeat=self.minutos_resume,
        )
        for item in list(self.latest.values()):
            if item.status == execucao.ETAPA_EXECUTANDO:
                self.repo.interromper_etapa(
                    registro.execution_id, item.etapa, item.tentativa,
                    "tentativa interrompida antes da retomada explícita",
                )
        self.latest = {
            item.etapa: item
            for item in self.repo.tentativas(registro.execution_id)
        }
        log.info("Execução retomada.", extra={"result": "retomada"})
        return None

    def rodar_etapa(
        self, nome: str, funcao: Callable[[], ResultadoEtapaOperacional], *,
        critica: bool = False,
    ) -> ResultadoEtapaOperacional:
        anterior = self.latest.get(nome)
        if self.resume and anterior is not None and anterior.status in _ETAPAS_CONCLUIDAS:
            detalhe = anterior.detalhe
            payload = None
            if "resultado_coleta" in detalhe:
                payload = _coleta_do_dict(detalhe["resultado_coleta"])
            resultado = ResultadoEtapaOperacional(
                status=anterior.status, detalhe=detalhe,
                alvos_tentados=anterior.alvos_tentados,
                alvos_persistidos=anterior.alvos_persistidos,
                alvos_falhos=anterior.alvos_falhos,
                alvos_nao_executados=anterior.alvos_nao_executados,
                payload=payload,
                degrada_execucao=anterior.status in {
                    execucao.ETAPA_PARCIAL, execucao.ETAPA_BLOQUEADO,
                },
            )
            self.parcial = self.parcial or resultado.degrada_execucao
            log.info("Etapa concluída anteriormente; pulando no resume.", extra={
                "stage": nome, "result": "resume_skip",
            })
            return resultado

        tentativa = self.repo.iniciar_etapa(self.execution_id, nome)
        inicio = time.monotonic()
        with log_context(stage=nome):
            log.info("Etapa iniciada.", extra={"attempt": tentativa.tentativa})
            try:
                resultado = funcao()
                concluida = self.repo.concluir_etapa(
                    self.execution_id, nome, tentativa.tentativa,
                    status=resultado.status,
                    alvos_tentados=resultado.alvos_tentados,
                    alvos_persistidos=resultado.alvos_persistidos,
                    alvos_falhos=resultado.alvos_falhos,
                    alvos_nao_executados=resultado.alvos_nao_executados,
                    detalhe=resultado.detalhe,
                )
                self.latest[nome] = concluida
                duracao = round((time.monotonic() - inicio) * 1000)
                log.info("Etapa concluída.", extra={
                    "result": resultado.status, "duration_ms": duracao,
                    "attempt": tentativa.tentativa,
                })
                emit_stage(
                    flow=self.tipo_fluxo, stage=nome, status=resultado.status,
                    duration_ms=duracao,
                )
                if isinstance(resultado.payload, ResultadoColeta):
                    coleta = resultado.payload
                    emit_source(
                        source=coleta.fonte,
                        status=coleta.estado.value,
                        attempted=coleta.alvos_tentados,
                        persisted=coleta.registros_persistidos,
                        failed=coleta.alvos_falhos,
                    )
                self.parcial = self.parcial or resultado.degrada_execucao
                if critica and resultado.status in {
                    execucao.ETAPA_FALHA, execucao.ETAPA_BLOQUEADO,
                }:
                    raise FalhaCritica(f"etapa crítica {nome} terminou como {resultado.status}")
                return resultado
            except FalhaCritica:
                raise
            except Exception as exc:  # noqa: BLE001 - vira estado durável
                try:
                    falha = self.repo.falhar_etapa(
                        self.execution_id, nome, tentativa.tentativa, exc,
                    )
                    self.latest[nome] = falha
                except ValueError:
                    # A função pode ter concluído a etapa e a validação crítica
                    # ter levantado logo depois; nesse caso não há linha aberta.
                    pass
                duracao = round((time.monotonic() - inicio) * 1000)
                log.exception("Etapa falhou.", extra={
                    "result": "falha",
                    "duration_ms": duracao,
                    "attempt": tentativa.tentativa,
                })
                emit_stage(
                    flow=self.tipo_fluxo, stage=nome, status="falha",
                    duration_ms=duracao,
                )
                if critica:
                    raise FalhaCritica(f"etapa crítica {nome} falhou: {exc}") from exc
                self.parcial = True
                return ResultadoEtapaOperacional(
                    status=execucao.ETAPA_FALHA,
                    detalhe={"erro": f"{type(exc).__name__}: {exc}"},
                    degrada_execucao=True,
                )

    def finalizar(
        self, *, pulado: bool = False, detalhe: dict[str, Any] | None = None,
    ) -> ResultadoOperacao:
        status = (
            execucao.PULADO if pulado
            else execucao.PARCIAL if self.parcial
            else execucao.EXECUTADO
        )
        registro = self.repo.finalizar(
            self.execution_id, status, detalhe or {"janela_logica": self.janela},
        )
        emit_execution(
            flow=self.tipo_fluxo,
            status=registro.status,
            duration_ms=round((time.monotonic() - self.iniciado_monotonic) * 1000),
        )
        return ResultadoOperacao(0, registro.status, self.execution_id, self.janela,
                                  registro.detalhe)

    def falhar(self, erro: BaseException) -> ResultadoOperacao:
        registro = self.repo.finalizar(
            self.execution_id, execucao.FALHOU,
            {"janela_logica": self.janela, "tipo_erro": type(erro).__name__},
            erro,
        )
        emit_execution(
            flow=self.tipo_fluxo,
            status=registro.status,
            duration_ms=round((time.monotonic() - self.iniciado_monotonic) * 1000),
        )
        return ResultadoOperacao(1, registro.status, self.execution_id, self.janela,
                                  registro.detalhe)


def _executar_earnings() -> ResultadoColeta:
    from src.earnings.ingest import tickers_da_carteira
    from src.earnings.providers import construir_providers
    from src.earnings.service import EarningsEventService

    tickers = tickers_da_carteira()
    servico = EarningsEventService(providers=construir_providers(None))
    coleta = servico.coletar_com_resultado(tickers)
    eventos = servico.ingerir(tickers, coletado=coleta) if coleta.afirmacoes else []
    if coleta.resultado.estado == EstadoColeta.PULADO:
        return coleta.resultado
    return ResultadoColeta(
        coletor=coleta.resultado.coletor,
        fonte=coleta.resultado.fonte,
        estado=coleta.resultado.estado,
        detalhes=coleta.resultado.detalhes,
        motivo=coleta.resultado.motivo,
        contexto={**dict(coleta.resultado.contexto), "eventos_consolidados": len(eventos)},
    )


def _avaliar_politica(
    fluxo: str, resultados: list[ResultadoColeta],
) -> ResultadoEtapaOperacional:
    resultado = agregar(fluxo, resultados)
    estado = _status_coleta(resultado.estado)
    return ResultadoEtapaOperacional(
        status=estado,
        detalhe=resultado.como_dict(),
        degrada_execucao=resultado.estado == EstadoColeta.PARCIAL,
    )


def executar_intraday(
    *, agora: dt.datetime | None = None, janela: str | None = None,
    gatilho: str = "manual", forcar: bool = False, resume: bool = False,
    repetir_etapas_externas: frozenset[str] = frozenset(),
    minutos_resume: int = 60, repo: execucao.RepositorioExecucao | None = None,
) -> ResultadoOperacao:
    agora = agora or dt.datetime.now(dt.timezone.utc)
    janela = janela_logica("intraday", agora, janela)
    op = Orquestrador(
        "intraday", janela, gatilho, repo=repo, resume=resume,
        repetir_etapas_externas=repetir_etapas_externas,
        minutos_resume=minutos_resume,
    )
    try:
        duplicada = op.adquirir()
        if duplicada:
            return duplicada

        def calendario() -> ResultadoEtapaOperacional:
            from src.pregao.calendario import avaliar

            resultado = avaliar(agora)
            detalhe = {
                "em_pregao": resultado.em_pregao,
                "motivo": resultado.motivo,
                "dia_de_pregao": resultado.dia_de_pregao,
                "ano_conferido": resultado.ano_conferido,
                "forcado": bool(forcar and not resultado.em_pregao),
            }
            return ResultadoEtapaOperacional(
                status=(
                    execucao.ETAPA_SUCESSO
                    if resultado.em_pregao or forcar else execucao.ETAPA_PULADO
                ),
                detalhe=detalhe,
                payload=resultado,
            )

        janela_b3 = op.rodar_etapa(ETAPA_CALENDARIO, calendario, critica=True)
        if janela_b3.status == execucao.ETAPA_PULADO:
            return op.finalizar(pulado=True, detalhe=janela_b3.detalhe)

        from src.etl import fetch_quotes

        cotacoes = op.rodar_etapa(
            ETAPA_COTACOES,
            lambda: _etapa_de_coleta(fetch_quotes.main()),
        )
        politica = op.rodar_etapa(
            ETAPA_POLITICA,
            lambda: _avaliar_politica("intraday", [cotacoes.payload]),
            critica=True,
        )
        if politica.status == execucao.ETAPA_PULADO:
            return op.finalizar(pulado=True, detalhe=politica.detalhe)

        # UM RELÓGIO POR EXECUÇÃO. Ler o relógio de novo aqui carimbava as
        # linhas com um instante que não é o da execução: `janela` e `data`
        # saem de `agora`, e o agente lê o insumo POR DATA. Divergindo os
        # dois, a avaliação grava sugestão e desfecho num dia e a leitura
        # procura no outro — o insumo sai vazio, a etapa do agente é pulada
        # como "sem_avaliacao_persistida" e não há relatório do dia. Uma
        # execução que atravesse a virada do dia cai exatamente nisso.
        executado_em = agora

        def avaliar_carteira() -> ResultadoEtapaOperacional:
            from src.strategy.covered import executar_avaliacao_carteira

            resultados = executar_avaliacao_carteira(executado_em=executado_em)
            serializados = _serializar_avaliacoes(resultados)
            return ResultadoEtapaOperacional(
                detalhe={
                    "executado_em": executado_em.isoformat(),
                    "avaliacoes": serializados,
                    "pares_avaliados": len(resultados),
                    "sugestoes": sum(item.elegivel for item in resultados),
                },
                alvos_tentados=len(resultados),
                alvos_persistidos=sum(item.elegivel for item in resultados),
                payload=resultados,
            )

        avaliacao = op.rodar_etapa(
            ETAPA_AVALIACAO, avaliar_carteira, critica=True,
        )
        momento = dt.datetime.fromisoformat(avaliacao.detalhe["executado_em"])
        avaliacoes = avaliacao.payload or _avaliacoes_para_quant(
            avaliacao.detalhe.get("avaliacoes", [])
        )

        def quant() -> ResultadoEtapaOperacional:
            from src.quant.pipeline import enriquecer_execucao

            gravadas = enriquecer_execucao(
                momento, avaliacoes, propagar_erro=True,
            )
            return ResultadoEtapaOperacional(
                detalhe={"linhas_gravadas": gravadas},
                alvos_tentados=len(avaliacoes), alvos_persistidos=gravadas,
            )

        op.rodar_etapa(ETAPA_QUANT, quant)
        return op.finalizar()
    except ResumeRecusado as exc:
        log.error("Resume recusado: %s", exc)
        return ResultadoOperacao(1, "resume_recusado", op.execution_id, janela,
                                  {"erro": str(exc)})
    except Exception as exc:  # noqa: BLE001 - fecha a execução adquirida
        log.exception("Fluxo intraday falhou.")
        if op.execution_id is None:
            return ResultadoOperacao(1, execucao.FALHOU, None, janela,
                                      {"erro": str(exc)})
        return op.falhar(exc)


def executar_daily(
    *, agora: dt.datetime | None = None, janela: str | None = None,
    gatilho: str = "manual", resume: bool = False,
    repetir_etapas_externas: frozenset[str] = frozenset(),
    minutos_resume: int = 60, repo: execucao.RepositorioExecucao | None = None,
) -> ResultadoOperacao:
    agora = agora or dt.datetime.now(dt.timezone.utc)
    janela = janela_logica("daily", agora, janela)
    data = _data_da_janela(janela, agora)
    op = Orquestrador(
        "daily", janela, gatilho, repo=repo, resume=resume,
        repetir_etapas_externas=repetir_etapas_externas,
        minutos_resume=minutos_resume,
    )
    try:
        duplicada = op.adquirir()
        if duplicada:
            return duplicada

        from src.etl import fetch_candles, fetch_news, fetch_options, fetch_quotes

        fontes = [
            op.rodar_etapa(
                ETAPA_COTACOES,
                lambda: _etapa_de_coleta(fetch_quotes.main()),
            ).payload,
            op.rodar_etapa(
                ETAPA_CANDLES_1H,
                lambda: _etapa_de_coleta(fetch_candles.main(intervalo="1h")),
            ).payload,
            op.rodar_etapa(
                ETAPA_CANDLES_1D,
                lambda: _etapa_de_coleta(fetch_candles.main(intervalo="1d")),
            ).payload,
            op.rodar_etapa(
                ETAPA_OPCOES,
                lambda: _etapa_de_coleta(fetch_options.main()),
            ).payload,
            op.rodar_etapa(
                ETAPA_NOTICIAS,
                lambda: _etapa_de_coleta(fetch_news.main()),
            ).payload,
        ]
        earnings = op.rodar_etapa(
            ETAPA_EARNINGS,
            lambda: _etapa_de_coleta(_executar_earnings()),
        )
        fontes.append(earnings.payload)
        op.rodar_etapa(
            ETAPA_POLITICA,
            lambda: _avaliar_politica("daily", fontes),
            critica=True,
        )

        # UM RELÓGIO POR EXECUÇÃO. Ler o relógio de novo aqui carimbava as
        # linhas com um instante que não é o da execução: `janela` e `data`
        # saem de `agora`, e o agente lê o insumo POR DATA. Divergindo os
        # dois, a avaliação grava sugestão e desfecho num dia e a leitura
        # procura no outro — o insumo sai vazio, a etapa do agente é pulada
        # como "sem_avaliacao_persistida" e não há relatório do dia. Uma
        # execução que atravesse a virada do dia cai exatamente nisso.
        executado_em = agora

        def avaliar_carteira() -> ResultadoEtapaOperacional:
            from src.strategy.covered import executar_avaliacao_carteira

            resultados = executar_avaliacao_carteira(executado_em=executado_em)
            serializados = _serializar_avaliacoes(resultados)
            return ResultadoEtapaOperacional(
                detalhe={
                    "executado_em": executado_em.isoformat(),
                    "avaliacoes": serializados,
                    "pares_avaliados": len(resultados),
                    "sugestoes": sum(item.elegivel for item in resultados),
                },
                alvos_tentados=len(resultados),
                alvos_persistidos=sum(item.elegivel for item in resultados),
                payload=resultados,
            )

        avaliacao = op.rodar_etapa(
            ETAPA_AVALIACAO, avaliar_carteira, critica=True,
        )
        momento = dt.datetime.fromisoformat(avaliacao.detalhe["executado_em"])
        avaliacoes = avaliacao.payload or _avaliacoes_para_quant(
            avaliacao.detalhe.get("avaliacoes", [])
        )

        def quant() -> ResultadoEtapaOperacional:
            from src.quant.pipeline import enriquecer_execucao

            gravadas = enriquecer_execucao(
                momento, avaliacoes, propagar_erro=True,
            )
            return ResultadoEtapaOperacional(
                detalhe={"linhas_gravadas": gravadas},
                alvos_tentados=len(avaliacoes), alvos_persistidos=gravadas,
            )

        op.rodar_etapa(ETAPA_QUANT, quant)

        def relatorio_deterministico() -> ResultadoEtapaOperacional:
            from src.report.daily import gerar_relatorio
            from src.report.repository import por_execucao

            gerar_relatorio(
                data, execution_id=op.execution_id, exportar_arquivo=False,
            )
            persistido = por_execucao(op.execution_id)
            if persistido is None:
                raise RuntimeError("relatório determinístico não foi persistido")
            return ResultadoEtapaOperacional(
                detalhe={"relatorio_id": persistido.id, "data": data.isoformat()},
                alvos_persistidos=1,
            )

        op.rodar_etapa(
            ETAPA_RELATORIO, relatorio_deterministico, critica=True,
        )

        def relatorio_agente() -> ResultadoEtapaOperacional:
            from src.agente import dados
            from src.agente.entrega import escrever_arquivo
            from src.agente.relatorio import compor, gravar

            insumo = dados.coletar(data, executado_em=momento)
            if insumo.vazio:
                return ResultadoEtapaOperacional(
                    status=execucao.ETAPA_PULADO,
                    detalhe={"motivo": "sem_avaliacao_persistida"},
                )
            relatorio = compor(insumo)
            relatorio_id = gravar(data, relatorio, execution_id=op.execution_id)
            if relatorio_id is None:
                raise RuntimeError("relatório Anthropic não foi persistido")
            # Export local é secundário e não participa da durabilidade.
            if os.getenv("OPCOES_IA_EXPORTAR_RELATORIOS", "0") == "1":
                escrever_arquivo(data, relatorio)
            return ResultadoEtapaOperacional(
                detalhe={
                    "relatorio_agente_id": relatorio_id,
                    "insumo_resumo": relatorio.insumo_resumo,
                },
                alvos_persistidos=1,
                payload=relatorio,
            )

        agente = op.rodar_etapa(ETAPA_AGENTE, relatorio_agente)

        def notificar() -> ResultadoEtapaOperacional:
            from src.agente.notificar import notificar_relatorio
            from src.agente.relatorio import obter

            relatorio_id = agente.detalhe.get("relatorio_agente_id")
            if relatorio_id is None:
                return ResultadoEtapaOperacional(
                    status=execucao.ETAPA_PULADO,
                    detalhe={"motivo": "relatorio_anthropic_indisponivel"},
                    degrada_execucao=agente.status == execucao.ETAPA_FALHA,
                )
            relatorio = agente.payload or obter(relatorio_id)
            if relatorio is None:
                raise RuntimeError("relatório Anthropic persistido não foi encontrado")
            enviada = notificar_relatorio(
                data, relatorio, relatorio_id=relatorio_id,
            )
            return ResultadoEtapaOperacional(
                status=(execucao.ETAPA_SUCESSO if enviada else execucao.ETAPA_PULADO),
                detalhe={
                    "relatorio_agente_id": relatorio_id,
                    "enviada": enviada,
                    "motivo": None if enviada else "smtp_ausente_ou_reserva_duplicada",
                },
                alvos_tentados=1 if enviada else 0,
                alvos_persistidos=1 if enviada else 0,
                degrada_execucao=not enviada,
            )

        op.rodar_etapa(ETAPA_NOTIFICACAO, notificar)
        return op.finalizar()
    except ResumeRecusado as exc:
        log.error("Resume recusado: %s", exc)
        return ResultadoOperacao(1, "resume_recusado", op.execution_id, janela,
                                  {"erro": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.exception("Fluxo daily falhou.")
        if op.execution_id is None:
            return ResultadoOperacao(1, execucao.FALHOU, None, janela,
                                      {"erro": str(exc)})
        return op.falhar(exc)


def _enviar_alerta(data: dt.date, motivo: str) -> None:
    from src.agente.notificar import ConfigSMTP, NotificacaoErro, enviar

    config = ConfigSMTP.from_env()
    if config is None:
        raise NotificacaoErro(
            "alerta necessário, mas SMTP_HOST e SMTP_TO não estão configurados"
        )
    enviar(
        f"opcoes-ia - alerta operacional ({data.isoformat()})",
        "O pipeline automático precisa de atenção.\n\n"
        f"Motivo: {motivo}\n"
        "Consulte execucao_pipeline pelo tipo de fluxo e janela lógica.",
        config,
    )


def executar_alerta(
    *, agora: dt.datetime | None = None, janela: str | None = None,
    gatilho: str = "manual", resume: bool = False,
    repetir_etapas_externas: frozenset[str] = frozenset(),
    minutos_resume: int = 60, repo: execucao.RepositorioExecucao | None = None,
) -> ResultadoOperacao:
    agora = agora or dt.datetime.now(dt.timezone.utc)
    janela = janela_logica("alert", agora, janela)
    data = _data_da_janela(janela, agora)
    op = Orquestrador(
        "alert", janela, gatilho, repo=repo, resume=resume,
        repetir_etapas_externas=repetir_etapas_externas,
        minutos_resume=minutos_resume,
    )
    try:
        duplicada = op.adquirir()
    except ResumeRecusado as exc:
        return ResultadoOperacao(1, "resume_recusado", op.execution_id, janela,
                                  {"erro": str(exc)})
    except Exception as exc:  # banco fora: o alerta ainda usa o canal independente
        motivo = f"banco indisponível ao adquirir/verificar execução: {type(exc).__name__}: {exc}"
        try:
            _enviar_alerta(data, motivo)
        except Exception as smtp_exc:  # noqa: BLE001
            log.exception("Banco e canal de alerta indisponíveis.")
            return ResultadoOperacao(1, execucao.FALHOU, None, janela, {
                "erro_banco": str(exc), "erro_notificacao": str(smtp_exc),
            })
        return ResultadoOperacao(0, execucao.PARCIAL, None, janela, {"motivo": motivo})

    try:
        if duplicada:
            return duplicada

        def verificar() -> ResultadoEtapaOperacional:
            from src.pregao.calendario import avaliar

            try:
                calendario = avaliar(agora)
            except Exception as exc:  # calendário desconhecido também exige atenção
                return ResultadoEtapaOperacional(
                    detalhe={
                        "precisa_alertar": True,
                        "condicao": "calendario",
                        "motivo": f"calendário de pregão indisponível: {exc}",
                    },
                )
            if not calendario.dia_de_pregao:
                return ResultadoEtapaOperacional(
                    status=execucao.ETAPA_PULADO,
                    detalhe={"precisa_alertar": False, "motivo": calendario.motivo},
                )

            ambiente = os.getenv("OPCOES_IA_ENV", "local")
            alvo = op.repo.obter_por_chave(ambiente, "daily", data.isoformat())
            if alvo is None:
                condicao = "ausente"
                motivo = f"execução daily ausente para {data.isoformat()}"
            elif alvo.status == execucao.FALHOU:
                condicao = "falha"
                motivo = f"execução daily falhou ({alvo.execution_id})"
            elif alvo.status == execucao.ORFA:
                condicao = "orfa"
                motivo = f"execução daily órfã ({alvo.execution_id})"
            elif alvo.status == execucao.EXECUTANDO:
                op.repo.classificar_orfas(minutos=minutos_resume)
                atualizado = op.repo.obter(alvo.execution_id)
                if atualizado and atualizado.status == execucao.ORFA:
                    condicao = "orfa"
                    motivo = f"execução daily órfã ({alvo.execution_id})"
                else:
                    condicao = "executando"
                    motivo = f"execução daily ainda não concluiu ({alvo.execution_id})"
            else:
                return ResultadoEtapaOperacional(
                    detalhe={
                        "precisa_alertar": False,
                        "motivo": f"execução daily concluída como {alvo.status}",
                        "execution_id_alvo": str(alvo.execution_id),
                    },
                )
            return ResultadoEtapaOperacional(
                detalhe={
                    "precisa_alertar": True,
                    "condicao": condicao,
                    "motivo": motivo,
                },
            )

        verificacao = op.rodar_etapa(
            ETAPA_ALERTA_VERIFICACAO, verificar, critica=True,
        )
        if not verificacao.detalhe["precisa_alertar"]:
            return op.finalizar(
                pulado=verificacao.status == execucao.ETAPA_PULADO,
                detalhe=verificacao.detalhe,
            )

        emit_operational_alert(verificacao.detalhe["condicao"])

        def notificar_alerta() -> ResultadoEtapaOperacional:
            _enviar_alerta(data, verificacao.detalhe["motivo"])
            return ResultadoEtapaOperacional(
                detalhe={"motivo": verificacao.detalhe["motivo"]},
                alvos_tentados=1, alvos_persistidos=1,
            )

        op.rodar_etapa(
            ETAPA_ALERTA_NOTIFICACAO, notificar_alerta, critica=True,
        )
        return op.finalizar(detalhe=verificacao.detalhe)
    except Exception as exc:  # noqa: BLE001
        log.exception("Fluxo alert falhou.")
        return op.falhar(exc)
