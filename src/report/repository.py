"""Persistência durável do relatório determinístico em Postgres."""
import datetime as dt
import uuid
from dataclasses import dataclass

from src.db.connection import get_connection


@dataclass(frozen=True)
class RelatorioDeterministico:
    id: int
    execution_id: uuid.UUID
    data: dt.date
    conteudo: str
    formato: str
    gerado_em: dt.datetime


_COLUNAS = "id, execution_id, data, conteudo, formato, gerado_em"


def _relatorio(row) -> RelatorioDeterministico:
    return RelatorioDeterministico(*row)


def salvar(
    execution_id: uuid.UUID | str, data: dt.date, conteudo: str,
) -> RelatorioDeterministico:
    """Grava uma linha por execução; reprocessamento atualiza a mesma linha."""
    if not conteudo:
        raise ValueError("conteúdo do relatório não pode ser vazio")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO relatorios_deterministicos (execution_id, data, conteudo)
            VALUES (%s, %s, %s)
            ON CONFLICT (execution_id) DO UPDATE
            SET data = EXCLUDED.data, conteudo = EXCLUDED.conteudo, gerado_em = now()
            RETURNING {_COLUNAS}
            """,
            (execution_id, data, conteudo),
        )
        row = cur.fetchone()
        conn.commit()
    return _relatorio(row)


def por_execucao(
    execution_id: uuid.UUID | str,
) -> RelatorioDeterministico | None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUNAS} FROM relatorios_deterministicos "
            "WHERE execution_id = %s",
            (execution_id,),
        )
        row = cur.fetchone()
    return _relatorio(row) if row else None


def por_id(relatorio_id: int) -> RelatorioDeterministico | None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLUNAS} FROM relatorios_deterministicos WHERE id = %s",
            (relatorio_id,),
        )
        row = cur.fetchone()
    return _relatorio(row) if row else None
