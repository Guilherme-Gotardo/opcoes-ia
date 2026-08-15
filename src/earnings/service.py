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

from src.earnings.models import (
    EarningsEvent,
    EarningsEventSource,
    ModeloInvalido,
    fiscal_period_from_release_date,
)
from src.earnings.providers.base import EarningsProvider, ProviderIndisponivel
from src.earnings.repository import EarningsEventRepository
from src.earnings.resolution import aplicar, resolver

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


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
        coletado: dict[str, list[EarningsEventSource]] = {}
        for provider in self.providers:
            try:
                fontes = provider.get_upcoming_earnings(tickers)
            except ProviderIndisponivel as exc:
                log.warning("Provider %s indisponível: %s", provider.name, exc)
                continue
            except Exception as exc:  # noqa: BLE001 — isolamento proposital
                log.error("Provider %s falhou: %s", provider.name, exc)
                continue
            coletado[provider.name] = fontes
            log.info("Provider %s: %d evento(s).", provider.name, len(fontes))
        return coletado

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
    ) -> list[EarningsEvent]:
        """Ciclo completo: coleta → resolve → persiste.

        Nada é gravado sem passar por `aplicar`, que é onde a regra
        "estimativa não derruba confirmação" é aplicada.
        """
        agora = agora or dt.datetime.now(dt.timezone.utc)
        coletado = self.coletar(tickers)
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
