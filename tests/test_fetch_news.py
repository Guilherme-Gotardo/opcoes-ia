"""Testes de src.etl.fetch_news — comportamento explícito quando não
configurado, deduplicação por url e isolamento de falha por ticker."""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from src.etl import fetch_news
from src.etl.fetch_news import main, upsert
from src.etl.result import EstadoAlvo, EstadoColeta

ARTIGO = {
    "title": "PETR4 sobe com alta do petróleo",
    "url": "https://exemplo.com/petr4-alta",
    "publishedAt": "2026-08-14T10:00:00Z",
    "source": {"name": "Exemplo News"},
}


class _FakeCursor:
    def __init__(self, urls_existentes=None):
        self.urls_existentes = urls_existentes or set()
        self.queries = []

    def execute(self, query, params=()):
        self.queries.append((query, params))
        self._last_params = params

    def fetchone(self):
        # usado por _noticia_ja_existe: SELECT 1 ... WHERE ticker=%s AND url=%s
        _, url = self._last_params
        return (1,) if url in self.urls_existentes else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def _patched_get_connection(fake_conn):
    @contextmanager
    def _fake():
        yield fake_conn

    return _fake


def test_upsert_insere_noticia_nova():
    cursor = _FakeCursor()
    fake_conn = _FakeConnection(cursor)
    with patch("src.etl.fetch_news.get_connection", _patched_get_connection(fake_conn)):
        total = upsert("PETR4", [ARTIGO])
    assert total == 1
    assert fake_conn.committed
    insert_query = [q for q, _ in cursor.queries if "INSERT" in q]
    assert len(insert_query) == 1


def test_upsert_deduplica_por_url_existente():
    cursor = _FakeCursor(urls_existentes={ARTIGO["url"]})
    fake_conn = _FakeConnection(cursor)
    with patch("src.etl.fetch_news.get_connection", _patched_get_connection(fake_conn)):
        total = upsert("PETR4", [ARTIGO])
    assert total == 0
    assert not any("INSERT" in q for q, _ in cursor.queries)


def test_main_sem_news_api_key_nao_chama_fetch():
    settings = MagicMock(news_api_key="")
    with patch("src.etl.fetch_news.get_news_settings", return_value=settings), \
         patch.object(fetch_news, "fetch") as mock_fetch:
        resultado = main(tickers=["PETR4"])
    mock_fetch.assert_not_called()
    assert resultado.estado == EstadoColeta.PULADO
    assert resultado.motivo == "fonte_nao_configurada"


def test_main_isola_falha_por_ticker():
    settings = MagicMock(news_api_key="uma-chave")

    def fake_fetch(ticker):
        if ticker == "VALE3":
            raise RuntimeError("rate limit")
        return [ARTIGO]

    with patch("src.etl.fetch_news.get_news_settings", return_value=settings), \
         patch.object(fetch_news, "fetch", side_effect=fake_fetch), \
         patch.object(fetch_news, "upsert", return_value=1) as mock_upsert:
        resultado = main(tickers=["PETR4", "VALE3", "ITUB4"])

    chamados = [call.args[0] for call in mock_upsert.call_args_list]
    assert chamados == ["PETR4", "ITUB4"]
    assert resultado.estado == EstadoColeta.PARCIAL
    assert resultado.alvos_falhos == 1


def test_main_consulta_carteira_e_watchlist_quando_universo_nao_e_explicito():
    settings = MagicMock(news_api_key="uma-chave")
    with patch.object(fetch_news, "get_news_settings", return_value=settings), \
         patch.object(fetch_news, "universo_de_analise", return_value=["PETR4"]) as universo, \
         patch.object(fetch_news, "fetch", return_value=[]), \
         patch.object(fetch_news, "upsert", return_value=0):
        resultado = main()

    universo.assert_called_once_with()
    assert resultado.estado == EstadoColeta.SUCESSO


def test_main_universo_vazio_e_pulado_sem_chamada_externa():
    settings = MagicMock(news_api_key="uma-chave")
    with patch.object(fetch_news, "get_news_settings", return_value=settings), \
         patch.object(fetch_news, "fetch") as mock_fetch:
        resultado = main(tickers=[])

    assert resultado.estado == EstadoColeta.PULADO
    assert resultado.motivo == "universo_vazio"
    mock_fetch.assert_not_called()


def test_main_resposta_vazia_ou_totalmente_deduplicada_e_sucesso():
    settings = MagicMock(news_api_key="uma-chave")
    with patch.object(fetch_news, "get_news_settings", return_value=settings), \
         patch.object(fetch_news, "fetch", side_effect=[[], [ARTIGO]]), \
         patch.object(fetch_news, "upsert", side_effect=[0, 0]):
        resultado = main(tickers=["PETR4", "VALE3"])

    assert resultado.estado == EstadoColeta.SUCESSO
    assert resultado.registros_persistidos == 0
    assert [item.estado for item in resultado.detalhes] == [
        EstadoAlvo.SUCESSO, EstadoAlvo.SUCESSO,
    ]


def test_main_falha_em_todos_os_tickers_e_falha_total():
    settings = MagicMock(news_api_key="uma-chave")
    with patch.object(fetch_news, "get_news_settings", return_value=settings), \
         patch.object(fetch_news, "fetch", side_effect=RuntimeError("provider fora")):
        resultado = main(tickers=["PETR4", "VALE3"])

    assert resultado.estado == EstadoColeta.FALHA
    assert resultado.alvos_falhos == 2
