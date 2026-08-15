"""Helper de conexão com o Postgres. Uso: `with get_connection() as conn: ...`"""
from contextlib import contextmanager

import psycopg

from src.config import get_settings


@contextmanager
def get_connection():
    settings = get_settings()
    conn = psycopg.connect(settings.database_url)
    try:
        yield conn
    finally:
        conn.close()
