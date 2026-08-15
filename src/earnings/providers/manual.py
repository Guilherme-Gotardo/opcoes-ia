"""Provider de datas de resultado informadas por um humano.

É a única fonte com autoridade para `CONFIRMED` (junto da CVM, que só
consegue afirmar `RELEASED` depois do fato). A justificativa é a mesma que
sustenta o resto do projeto: a carteira já é um espelho manual, e a data
que o usuário lê no site de RI da companhia é mais confiável do que
qualquer estimativa de terceiro.

Lê de `earnings_manual_entries` — tabela editável — e PRODUZ
`EarningsEventSource`. A tabela é a origem; as fontes são o registro.
"""
import datetime as dt

from src.db.connection import get_connection
from src.earnings.models import EarningsEventSource, EarningsStatus, Session


class ManualProvider:
    """Entradas manuais como fonte de eventos de resultado."""

    name = "manual"

    def _consultar(self, tickers: list[str] | None, desde: dt.date | None,
                   ate: dt.date | None) -> list[EarningsEventSource]:
        clausulas = []
        params: list = []
        if tickers:
            clausulas.append("ticker = ANY(%s)")
            params.append([t.upper() for t in tickers])
        if desde is not None:
            clausulas.append("data_resultado >= %s")
            params.append(desde)
        if ate is not None:
            clausulas.append("data_resultado <= %s")
            params.append(ate)
        where = (" WHERE " + " AND ".join(clausulas)) if clausulas else ""

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, fiscal_period, data_resultado, hora_resultado, "
                "session, origem, atualizado_em FROM earnings_manual_entries"
                + where + " ORDER BY ticker, data_resultado",
                tuple(params),
            )
            linhas = cur.fetchall()

        fontes = []
        for ticker, periodo, data, hora, sessao, origem, atualizado_em in linhas:
            fontes.append(EarningsEventSource(
                ticker=ticker,
                provider=self.name,
                date=data,
                time=hora,
                session=Session(sessao),
                fiscal_period=periodo,
                # Uma entrada manual é sempre uma confirmação: o usuário
                # está afirmando que leu a data na fonte oficial. Se ele
                # não tem certeza, não deve registrar.
                status=EarningsStatus.CONFIRMED,
                source_url=origem,
                # `atualizado_em` e não `registrado_em`: corrigir uma
                # entrada renova a validade da informação, e a penalidade
                # por idade precisa contar a partir da correção.
                retrieved_at=atualizado_em,
                confidence=97,
            ))
        return fontes

    def get_upcoming_earnings(self, tickers: list[str]) -> list[EarningsEventSource]:
        hoje = dt.datetime.now(dt.timezone.utc).date()
        return self._consultar(tickers, desde=hoje, ate=None)

    def get_historical_earnings(
        self, ticker: str, start: dt.date, end: dt.date
    ) -> list[EarningsEventSource]:
        return self._consultar([ticker], desde=start, ate=end)
