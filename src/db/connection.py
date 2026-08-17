"""Helper de conexão com o Postgres. Uso: `with get_connection() as conn: ...`"""
from contextlib import contextmanager

import psycopg

from src.config import get_database_settings
from src.observability.metrics import emit_neon_connection_error


@contextmanager
def get_connection():
    settings = get_database_settings()
    try:
        conn = psycopg.connect(settings.database_url)
    except psycopg.Error:
        emit_neon_connection_error()
        raise
    try:
        yield conn
    finally:
        conn.close()
