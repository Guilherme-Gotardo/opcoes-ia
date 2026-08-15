"""Persistência de eventos de resultado e das fontes que os sustentam.

O repositório é deliberadamente burro: grava e lê, sem decidir nada. Toda
regra de precedência vive em `resolution.py`, para que ela seja testável
sem banco e para que não exista um segundo lugar — silencioso — onde uma
estimativa possa derrubar uma confirmação.
"""
import datetime as dt
import json

from src.db.connection import get_connection
from src.earnings.models import (
    EarningsEvent,
    EarningsEventSource,
    EarningsStatus,
    Session,
)

_COLUNAS_EVENTO = """
    id, ticker, fiscal_period, company_name,
    expected_date, confirmed_date, expected_time, confirmed_time,
    session, status, confidence, conflicts, first_seen_at, updated_at
"""


def _linha_para_evento(row: tuple, sources: tuple[EarningsEventSource, ...]) -> EarningsEvent:
    (
        _id, ticker, fiscal_period, company_name,
        expected_date, confirmed_date, expected_time, confirmed_time,
        session, status, confidence, conflicts, first_seen_at, updated_at,
    ) = row
    if isinstance(conflicts, str):
        conflicts = json.loads(conflicts)
    return EarningsEvent(
        ticker=ticker,
        fiscal_period=fiscal_period,
        company_name=company_name,
        expected_date=expected_date,
        confirmed_date=confirmed_date,
        expected_time=expected_time,
        confirmed_time=confirmed_time,
        session=Session(session),
        status=EarningsStatus(status),
        confidence=confidence,
        conflicts=tuple(conflicts or ()),
        sources=sources,
        first_seen_at=first_seen_at,
        updated_at=updated_at,
    )


def _linha_para_fonte(row: tuple, ticker: str) -> EarningsEventSource:
    (
        provider, reported_date, reported_time, status, session,
        fiscal_period, source_url, confidence, retrieved_at,
    ) = row
    return EarningsEventSource(
        ticker=ticker,
        provider=provider,
        date=reported_date,
        time=reported_time,
        status=EarningsStatus(status) if status else None,
        session=Session(session) if session else None,
        fiscal_period=fiscal_period,
        source_url=source_url,
        confidence=confidence,
        retrieved_at=retrieved_at,
    )


class EarningsEventRepository:
    """Acesso a `earnings_events` e `earnings_event_sources`."""

    def _carregar_fontes(self, cur, event_id: str, ticker: str) -> tuple[EarningsEventSource, ...]:
        cur.execute(
            "SELECT provider, reported_date, reported_time, status, session, "
            "fiscal_period, source_url, confidence, retrieved_at "
            "FROM earnings_event_sources WHERE event_id = %s "
            "ORDER BY retrieved_at",
            (event_id,),
        )
        return tuple(_linha_para_fonte(r, ticker) for r in cur.fetchall())

    def get(self, ticker: str, fiscal_period: str) -> EarningsEvent | None:
        event_id = f"{ticker.upper()}:{fiscal_period}"
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUNAS_EVENTO} FROM earnings_events WHERE id = %s",
                (event_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return _linha_para_evento(row, self._carregar_fontes(cur, event_id, row[1]))

    def proximo_evento(
        self, ticker: str, referencia: dt.date
    ) -> EarningsEvent | None:
        """Próximo evento com data igual ou posterior à referência.

        Datas passadas são ignoradas de propósito: um evento vencido que
        não foi atualizado precisa voltar a ser "desconhecido", nunca
        continuar aprovando o critério com um valor obsoleto.
        """
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUNAS_EVENTO} FROM earnings_events "
                "WHERE ticker = %s "
                "AND COALESCE(confirmed_date, expected_date) >= %s "
                "ORDER BY COALESCE(confirmed_date, expected_date) ASC LIMIT 1",
                (ticker.upper(), referencia),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return _linha_para_evento(row, self._carregar_fontes(cur, row[0], row[1]))

    def listar_por_ticker(self, ticker: str) -> list[EarningsEvent]:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUNAS_EVENTO} FROM earnings_events "
                "WHERE ticker = %s ORDER BY fiscal_period",
                (ticker.upper(),),
            )
            linhas = cur.fetchall()
            return [
                _linha_para_evento(r, self._carregar_fontes(cur, r[0], r[1]))
                for r in linhas
            ]

    def salvar(self, evento: EarningsEvent) -> None:
        """Grava o evento e todas as suas fontes.

        As fontes usam `ON CONFLICT DO NOTHING` sobre
        (event_id, provider, retrieved_at): reingerir a mesma coleta não
        duplica o rastro, mas uma coleta nova do mesmo provider entra como
        linha adicional — o histórico de afirmações é preservado.
        """
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO earnings_events (
                    id, ticker, fiscal_period, company_name,
                    expected_date, confirmed_date, expected_time, confirmed_time,
                    session, status, confidence, conflicts,
                    first_seen_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET
                    company_name   = EXCLUDED.company_name,
                    expected_date  = EXCLUDED.expected_date,
                    confirmed_date = EXCLUDED.confirmed_date,
                    expected_time  = EXCLUDED.expected_time,
                    confirmed_time = EXCLUDED.confirmed_time,
                    session        = EXCLUDED.session,
                    status         = EXCLUDED.status,
                    confidence     = EXCLUDED.confidence,
                    conflicts      = EXCLUDED.conflicts,
                    updated_at     = EXCLUDED.updated_at
                """,
                (
                    evento.id, evento.ticker, evento.fiscal_period, evento.company_name,
                    evento.expected_date, evento.confirmed_date,
                    evento.expected_time, evento.confirmed_time,
                    evento.session.value, evento.status.value, evento.confidence,
                    json.dumps(list(evento.conflicts)),
                    evento.first_seen_at, evento.updated_at,
                ),
            )
            for s in evento.sources:
                cur.execute(
                    """
                    INSERT INTO earnings_event_sources (
                        event_id, provider, reported_date, reported_time,
                        status, session, fiscal_period, source_url,
                        confidence, retrieved_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (event_id, provider, retrieved_at) DO NOTHING
                    """,
                    (
                        evento.id, s.provider, s.date, s.time,
                        s.status.value if s.status else None,
                        s.session.value if s.session else None,
                        s.fiscal_period, s.source_url, s.confidence, s.retrieved_at,
                    ),
                )
            conn.commit()
