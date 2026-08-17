"""Orquestração do Earnings Event Service.

Junta as peças: consulta os providers, agrupa as afirmações por evento,
manda resolver o conflito e persiste — sempre passando pelo portão de
precedência de `resolution.aplicar`, nunca gravando direto.

Falha de um provider é isolada: uma fonte fora do ar não pode derrubar a
ingestão das demais nem, pior, ser confundida com "esse ativo não tem
resultado próximo".
"""
import datetime as dt
import logging
from collections import defaultdict
from dataclasses import dataclass

from src.earnings.models import (
    EarningsEvent,
    EarningsEventSource,
    ModeloInvalido,
    fiscal_period_from_release_date,
)
from src.earnings.providers.base import EarningsProvider, ProviderIndisponivel
from src.earnings.repository import EarningsEventRepository
from src.earnings.resolution import aplicar, resolver
from src.etl.result import DetalheAlvo, EstadoAlvo, ResultadoColeta

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

CODIGO_UNIVERSO_VAZIO = "universo_vazio"
CODIGO_PROVIDER_INDISPONIVEL = "provider_indisponivel"
CODIGO_ERRO_PROVIDER = "erro_provider"
CODIGO_SEM_AFIRMACOES = "sem_afirmacoes"
CODIGO_NENHUM_PROVIDER = "nenhum_provider_configurado"


@dataclass(frozen=True)
class ColetaEarnings:
    """Afirmações e desfecho operacional de uma única consulta às fontes.

    Providers de earnings recebem o universo em lote e não informam se a
    exceção ocorreu para um ticker específico. Por isso os resultados usam
    alvos ``fonte:<provider>``: replicar a falha para cada ticker inventaria
    uma granularidade que o contrato do provider não oferece.
    """

    afirmacoes: dict[str, list[EarningsEventSource]]
    falhas: dict[str, Exception]
    resultados_por_provider: tuple[ResultadoColeta, ...]
    resultado: ResultadoColeta


class EarningsEventService:
    """Descobre, normaliza, resolve e armazena eventos de resultado."""

    def __init__(
        self,
        providers: list[EarningsProvider] | None = None,
        repository: EarningsEventRepository | None = None,
    ) -> None:
        self.providers = providers or []
        self.repository = repository or EarningsEventRepository()

    # ------------------------------------------------------------------
    # Ingestão
    # ------------------------------------------------------------------
    def coletar(self, tickers: list[str]) -> dict[str, list[EarningsEventSource]]:
        """Consulta todos os providers, isolando falha por fonte.

        Retorna o que cada provider afirmou, sem consolidar. Providers que
        falharam simplesmente não contribuem — e o motivo vai para o log,
        porque "não sabemos" precisa ser distinguível de "não há evento".
        """
        return self.coletar_com_resultado(tickers).afirmacoes

    def coletar_com_resultado(self, tickers: list[str]) -> ColetaEarnings:
        """Consulta cada provider uma vez e preserva sucessos e exceções.

        Diferente do contrato legado de :meth:`coletar`, uma lista vazia de
        uma fonte continua registrada como sucesso e uma exceção fica
        disponível ao orquestrador com código estável. Universo vazio é
        ``pulado`` antes de qualquer chamada externa.
        """
        if not tickers:
            resultados = tuple(
                ResultadoColeta.pulado(
                    "earnings", provider.name, CODIGO_UNIVERSO_VAZIO
                )
                for provider in self.providers
            )
            return ColetaEarnings(
                afirmacoes={},
                falhas={},
                resultados_por_provider=resultados,
                resultado=ResultadoColeta.pulado(
                    "earnings", "providers", CODIGO_UNIVERSO_VAZIO
                ),
            )

        coletado: dict[str, list[EarningsEventSource]] = {}
        falhas: dict[str, Exception] = {}
        resultados: list[ResultadoColeta] = []
        detalhes_agregados: list[DetalheAlvo] = []
        for provider in self.providers:
            try:
                fontes = list(provider.get_upcoming_earnings(tickers))
            except ProviderIndisponivel as exc:
                log.warning("Provider %s indisponível: %s", provider.name, exc)
                codigo = CODIGO_PROVIDER_INDISPONIVEL
                erro = exc
            except Exception as exc:  # noqa: BLE001 — isolamento proposital
                log.error("Provider %s falhou: %s", provider.name, exc)
                codigo = CODIGO_ERRO_PROVIDER
                erro = exc
            else:
                coletado[provider.name] = fontes
                detalhe = DetalheAlvo(
                    ticker=f"fonte:{provider.name}",
                    estado=EstadoAlvo.SUCESSO,
                    codigo_motivo=CODIGO_SEM_AFIRMACOES if not fontes else None,
                    detalhe=(
                        "provider respondeu sem afirmações"
                        if not fontes else None
                    ),
                )
                contexto = {
                    "granularidade_alvo": "fonte",
                    "afirmacoes_coletadas": len(fontes),
                }
                resultados.append(ResultadoColeta.de_detalhes(
                    "earnings", provider.name, [detalhe], contexto=contexto
                ))
                detalhes_agregados.append(detalhe)
                log.info("Provider %s: %d evento(s).", provider.name, len(fontes))
                continue

            falhas[provider.name] = erro
            detalhe = DetalheAlvo(
                ticker=f"fonte:{provider.name}",
                estado=EstadoAlvo.FALHA,
                codigo_motivo=codigo,
                detalhe=str(erro),
            )
            resultados.append(ResultadoColeta.de_detalhes(
                "earnings",
                provider.name,
                [detalhe],
                contexto={"granularidade_alvo": "fonte"},
            ))
            detalhes_agregados.append(detalhe)

        if detalhes_agregados:
            resultado_agregado = ResultadoColeta.de_detalhes(
                "earnings",
                "providers",
                detalhes_agregados,
                contexto={
                    "granularidade_alvo": "fonte",
                    "afirmacoes_por_provider": {
                        nome: len(fontes) for nome, fontes in coletado.items()
                    },
                },
            )
        else:
            resultado_agregado = ResultadoColeta.pulado(
                "earnings", "providers", CODIGO_NENHUM_PROVIDER
            )

        return ColetaEarnings(
            afirmacoes=coletado,
            falhas=falhas,
            resultados_por_provider=tuple(resultados),
            resultado=resultado_agregado,
        )

    def _agrupar(
        self, coletado: dict[str, list[EarningsEventSource]], tickers: list[str]
    ) -> dict[tuple[str, str], list[EarningsEventSource]]:
        """Agrupa afirmações por (ticker, trimestre fiscal).

        O ticker vem do provider via `fiscal_period` quando disponível; se
        a fonte não informa o período, ele é derivado da data por
        aritmética de calendário — determinística e documentada em
        `models.fiscal_period_from_release_date`.
        """
        alvo = {t.upper() for t in tickers}
        grupos: dict[tuple[str, str], list[EarningsEventSource]] = defaultdict(list)

        for provider_name, fontes in coletado.items():
            for fonte in fontes:
                if fonte.date is None:
                    continue
                if fonte.ticker.upper() not in alvo:
                    log.debug(
                        "Ignorando %s de %s: fora dos tickers pedidos.",
                        fonte.ticker, provider_name,
                    )
                    continue
                periodo = fonte.fiscal_period
                if not periodo:
                    try:
                        periodo = fiscal_period_from_release_date(fonte.date)
                    except ModeloInvalido as exc:
                        log.warning(
                            "Descartando afirmação de %s sem período derivável: %s",
                            provider_name, exc,
                        )
                        continue
                grupos[(fonte.ticker.upper(), periodo)].append(fonte)
        return grupos

    def ingerir(
        self,
        tickers: list[str],
        agora: dt.datetime | None = None,
        coletado: (
            dict[str, list[EarningsEventSource]] | ColetaEarnings | None
        ) = None,
    ) -> list[EarningsEvent]:
        """Ciclo completo: coleta → resolve → persiste.

        Nada é gravado sem passar por `aplicar`, que é onde a regra
        "estimativa não derruba confirmação" é aplicada.

        `coletado` permite reaproveitar uma coleta já feita pelo chamador.
        Existe porque quem opera o comando precisa saber QUAIS fontes
        responderam — informação que `coletar()` produz e este método
        descarta. Sem isso, o entrypoint teria de consultar tudo duas vezes
        (o provider da CVM baixa o dump IPE) ou duplicar esta orquestração.
        """
        agora = agora or dt.datetime.now(dt.timezone.utc)
        if coletado is None:
            coletado = self.coletar(tickers)
        elif isinstance(coletado, ColetaEarnings):
            coletado = coletado.afirmacoes
        grupos = self._agrupar(coletado, tickers)

        atualizados: list[EarningsEvent] = []
        for (ticker, periodo), fontes in sorted(grupos.items()):
            evento = self.registrar(ticker, periodo, fontes, agora=agora)
            atualizados.append(evento)
        log.info("Eventos consolidados: %d.", len(atualizados))
        return atualizados

    def registrar(
        self,
        ticker: str,
        fiscal_period: str,
        fontes: list[EarningsEventSource],
        company_name: str | None = None,
        agora: dt.datetime | None = None,
    ) -> EarningsEvent:
        """Consolida `fontes` no evento (ticker, período) e persiste."""
        ticker = ticker.upper()
        existente = self.repository.get(ticker, fiscal_period)
        resolucao = resolver(fontes, agora=agora)
        evento = aplicar(
            existente=existente,
            ticker=ticker,
            fiscal_period=fiscal_period,
            resolucao=resolucao,
            sources=fontes,
            company_name=company_name,
            agora=agora,
        )
        self.repository.salvar(evento)
        if evento.conflicts:
            log.warning(
                "Conflito em %s: %s", evento.id, " | ".join(evento.conflicts)
            )
        return evento

    # ------------------------------------------------------------------
    # Consulta — é isto que o motor de opções usa (via EarningsRiskService)
    # ------------------------------------------------------------------
    def proximo_evento(
        self, ticker: str, referencia: dt.date | None = None
    ) -> EarningsEvent | None:
        referencia = referencia or dt.datetime.now(dt.timezone.utc).date()
        return self.repository.proximo_evento(ticker, referencia)
