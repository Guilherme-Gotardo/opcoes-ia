"""Contrato que todo provedor de datas de resultado precisa cumprir.

Um provider é burro de propósito: ele traduz a resposta da sua fonte para
`EarningsEventSource` e para por aí. Ele NÃO decide qual data vale, não
compara com outras fontes e não atribui status de confirmação além do que
a própria fonte afirma. Consolidação é responsabilidade de
`src/earnings/resolution.py`; autoridade é de `src/earnings/confidence.py`.

Manter os providers assim é o que permite trocar uma fonte sem tocar na
lógica de decisão — e o que impede que um provedor novo, mal calibrado,
promova sozinho uma estimativa a confirmação.
"""
import datetime as dt
from typing import Protocol, runtime_checkable

from src.earnings.models import EarningsEventSource


@runtime_checkable
class EarningsProvider(Protocol):
    """Fonte de datas de divulgação de resultado."""

    name: str

    def get_upcoming_earnings(
        self, tickers: list[str]
    ) -> list[EarningsEventSource]:
        """Próximas divulgações conhecidas para os tickers pedidos.

        Deve retornar lista vazia — nunca levantar — quando a fonte não
        conhece nenhum dos tickers. Cobertura parcial é o caso NORMAL: na
        prova de 2026-08-15 o yfinance cobriu 3 de 5 tickers da B3.
        """
        ...

    def get_historical_earnings(
        self, ticker: str, start: dt.date, end: dt.date
    ) -> list[EarningsEventSource]:
        """Divulgações já ocorridas no intervalo."""
        ...


class ProviderIndisponivel(RuntimeError):
    """A fonte não pôde ser consultada (rede, plano, credencial).

    Distinta de "a fonte respondeu e não conhece o ticker": esta indica que
    NÃO SABEMOS, e o chamador não deve interpretar o silêncio como ausência
    de evento.
    """
