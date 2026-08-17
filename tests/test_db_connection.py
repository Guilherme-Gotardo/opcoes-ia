from unittest.mock import MagicMock, patch

from src.db.connection import get_connection


def test_conexao_exige_somente_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://usuario:senha@host/base")
    for nome in (
        "BRAPI_TOKEN", "OPLAB_TOKEN", "NEWS_API_KEY", "ANTHROPIC_API_KEY",
        "SMTP_HOST", "SMTP_TO",
    ):
        monkeypatch.delenv(nome, raising=False)

    conn = MagicMock()
    with patch("src.db.connection.psycopg.connect", return_value=conn) as connect:
        with get_connection() as obtida:
            assert obtida is conn

    connect.assert_called_once_with("postgresql://usuario:senha@host/base")
    conn.close.assert_called_once()
