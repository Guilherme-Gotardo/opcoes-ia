"""Provider secundário: Yahoo Finance via `yfinance`.

Papel: palpite de data FUTURA. Nunca confirmação. O tier em
`confidence.py` é `SECUNDARIA`, então nada que venha daqui alcança a faixa
`CONFIRMED` — mesmo que o Yahoo se declare seguro.

O QUE A PROVA REAL MOSTROU (2026-08-15, yfinance 1.6.0)
-------------------------------------------------------
Cobertura de data futura: 3 de 5 tickers da B3.
    VALE3 → 2026-10-29 · BBAS3 → 2026-11-11 · ABEV3 → 2026-10-29
    PETR4 → vazio      · ITUB4 → vazio
Os dois vazios são justamente os que acabaram de divulgar (06/08 e 04/08):
há uma janela cega logo depois de cada resultado. Cobertura parcial é o
caso NORMAL desta fonte, não um erro a ser tratado como falha.

POR QUE ESTE PROVIDER NÃO EMITE HORÁRIO NEM SESSÃO
--------------------------------------------------
Os horários retornados são placeholders, não dados. Medidos:
    ABEV3 → 02:00:00-04:00   (= 03:00 BRT, madrugada)
    VALE3 → 00:00:00-04:00   (= meia-noite)
E foi exatamente esse artefato que produziu a divergência real da VALE3: a
empresa divulgou em 30/07 após o fechamento, o carimbo de meia-noite
empurrou para 31/07, e o Yahoo passou a discordar da CVM em um dia.
Derivar `session` daqui geraria dado errado com aparência de dado bom —
pior que dado nenhum. Emitimos `session=None`, que vira `UNKNOWN` e
AMPLIA a janela de risco.
"""
import datetime as dt
import logging

from src.earnings.models import EarningsEventSource, EarningsStatus
from src.earnings.providers.base import ProviderIndisponivel

log = logging.getLogger(__name__)

SUFIXO_B3 = ".SA"


def _importar_yfinance():
    """Import tardio: `yfinance` é dependência opcional.

    Arrasta pandas/numpy, e o projeto precisa rodar sem ela — os providers
    `manual` e `cvm` não dependem disso. Ausência vira
    `ProviderIndisponivel`, que o serviço já trata como "não sabemos",
    distinto de "não há evento".
    """
    try:
        import yfinance  # noqa: PLC0415
    except ImportError as exc:
        raise ProviderIndisponivel(
            "yfinance não está instalado. Instale com `pip install yfinance` "
            "ou remova o YahooProvider da lista de providers."
        ) from exc
    return yfinance


def para_simbolo_yahoo(ticker: str) -> str:
    ticker = ticker.upper().strip()
    return ticker if ticker.endswith(SUFIXO_B3) else ticker + SUFIXO_B3


def de_simbolo_yahoo(simbolo: str) -> str:
    simbolo = simbolo.upper().strip()
    return simbolo[: -len(SUFIXO_B3)] if simbolo.endswith(SUFIXO_B3) else simbolo


class YahooProvider:
    """Estimativas de data de resultado vindas do Yahoo Finance."""

    name = "yfinance"

    def __init__(self, yf_module=None):
        self._yf = yf_module

    @property
    def yf(self):
        if self._yf is None:
            self._yf = _importar_yfinance()
        return self._yf

    def _agora(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)

    def _fonte(
        self, ticker: str, data: dt.date, status: EarningsStatus
    ) -> EarningsEventSource:
        return EarningsEventSource(
            ticker=ticker,
            provider=self.name,
            date=data,
            # Ver docstring do módulo: horário e sessão são deliberadamente
            # omitidos porque os valores desta fonte são placeholders.
            time=None,
            session=None,
            status=status,
            source_url=f"https://finance.yahoo.com/quote/{para_simbolo_yahoo(ticker)}/",
            retrieved_at=self._agora(),
            confidence=45,
        )

    def get_upcoming_earnings(self, tickers: list[str]) -> list[EarningsEventSource]:
        """Próximas divulgações conhecidas. Cobertura parcial é esperada."""
        fontes: list[EarningsEventSource] = []
        hoje = self._agora().date()

        for ticker in tickers:
            base = de_simbolo_yahoo(ticker)
            try:
                tk = self.yf.Ticker(para_simbolo_yahoo(ticker))
                datas = self._datas_futuras(tk, hoje)
            except ProviderIndisponivel:
                raise
            except Exception as exc:  # noqa: BLE001 — isolamento por ticker
                log.warning("yfinance falhou em %s: %s", base, exc)
                continue

            if not datas:
                log.info("yfinance não conhece data futura para %s.", base)
                continue
            for data in datas:
                fontes.append(self._fonte(base, data, EarningsStatus.ESTIMATED))
        return fontes

    def _datas_futuras(self, tk, hoje: dt.date) -> list[dt.date]:
        """Datas futuras conhecidas, via `calendar` e `earnings_dates`.

        As duas superfícies discordam entre si em alguns tickers, então
        unimos e deduplicamos em vez de confiar numa só.
        """
        encontradas: set[dt.date] = set()

        calendario = getattr(tk, "calendar", None) or {}
        for valor in _como_lista(calendario.get("Earnings Date")):
            data = _como_data(valor)
            if data and data >= hoje:
                encontradas.add(data)

        tabela = getattr(tk, "earnings_dates", None)
        if tabela is not None and len(tabela) > 0:
            for indice, linha in tabela.iterrows():
                data = _como_data(indice)
                if data is None or data < hoje:
                    continue
                # `Reported EPS` vazio é o ÚNICO discriminante desta fonte
                # entre "já saiu" e "ainda vai sair" — não há flag própria.
                if not _esta_vazio(linha.get("Reported EPS")):
                    continue
                encontradas.add(data)

        return sorted(encontradas)

    def get_historical_earnings(
        self, ticker: str, start: dt.date, end: dt.date
    ) -> list[EarningsEventSource]:
        base = de_simbolo_yahoo(ticker)
        try:
            tk = self.yf.Ticker(para_simbolo_yahoo(ticker))
            tabela = getattr(tk, "earnings_dates", None)
        except ProviderIndisponivel:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("yfinance falhou no histórico de %s: %s", base, exc)
            return []

        if tabela is None or len(tabela) == 0:
            return []

        fontes = []
        for indice, linha in tabela.iterrows():
            data = _como_data(indice)
            if data is None or not (start <= data <= end):
                continue
            já_saiu = not _esta_vazio(linha.get("Reported EPS"))
            fontes.append(self._fonte(
                base, data,
                EarningsStatus.RELEASED if já_saiu else EarningsStatus.ESTIMATED,
            ))
        return fontes


def _como_lista(valor) -> list:
    if valor is None:
        return []
    if isinstance(valor, (list, tuple, set)):
        return list(valor)
    return [valor]


def _como_data(valor) -> dt.date | None:
    if valor is None:
        return None
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    to_pydatetime = getattr(valor, "to_pydatetime", None)
    if callable(to_pydatetime):
        try:
            return to_pydatetime().date()
        except Exception:  # noqa: BLE001
            return None
    if isinstance(valor, str):
        try:
            return dt.date.fromisoformat(valor[:10])
        except ValueError:
            return None
    return None


def _esta_vazio(valor) -> bool:
    """`True` para None e NaN, sem exigir pandas importado."""
    if valor is None:
        return True
    return valor != valor  # NaN é o único valor diferente de si mesmo
