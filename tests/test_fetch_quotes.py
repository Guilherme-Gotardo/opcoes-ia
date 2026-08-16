"""Testes de src.etl.fetch_quotes — validação defensiva do formato da
resposta da Brapi, isolamento de falha por ticker e respeito ao orçamento
diário de requests (não dependem de Postgres real)."""
import logging
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from src.etl import fetch_quotes
from src.etl.fetch_quotes import FormatoRespostaInvalido, _extrair_campos, main, upsert

COTACAO_VALIDA = {
    "requestedSymbol": "PETR4",
    "symbol": "PETR4",
    "data": {"regularMarketPrice": 42.09, "regularMarketVolume": 34089900},
}


class _FakeCursor:
    def __init__(self):
        self.queries = []

    def execute(self, query, params=()):
        self.queries.append((query, params))

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


def test_extrair_campos_aceita_cotacao_completa():
    symbol, preco, volume = _extrair_campos(COTACAO_VALIDA)
    assert symbol == "PETR4"
    assert preco == 42.09
    assert volume == 34089900


def test_extrair_campos_rejeita_data_ausente():
    incompleta = {"symbol": "PETR4"}
    with pytest.raises(FormatoRespostaInvalido):
        _extrair_campos(incompleta)


def test_extrair_campos_rejeita_preco_ausente():
    incompleta = {"symbol": "PETR4", "data": {"regularMarketVolume": 100}}
    with pytest.raises(FormatoRespostaInvalido):
        _extrair_campos(incompleta)


def test_upsert_nao_grava_quando_formato_invalido():
    cursor = _FakeCursor()
    fake_conn = _FakeConnection(cursor)
    with patch("src.etl.fetch_quotes.get_connection", _patched_get_connection(fake_conn)):
        with pytest.raises(FormatoRespostaInvalido):
            upsert([{"symbol": "PETR4"}])
    assert cursor.queries == []
    assert not fake_conn.committed


def test_upsert_grava_quando_formato_valido():
    cursor = _FakeCursor()
    fake_conn = _FakeConnection(cursor)
    with patch("src.etl.fetch_quotes.get_connection", _patched_get_connection(fake_conn)):
        total = upsert([COTACAO_VALIDA])
    assert total == 1
    assert fake_conn.committed
    assert "INSERT INTO cotacoes" in cursor.queries[0][0]
    assert cursor.queries[0][1] == ("PETR4", 42.09, 34089900)


class _FakeSettings:
    brapi_requests_dia_maximo = 600


def _todos_cadastrados(tickers):
    """Dublê de `tickers_cadastrados`: por padrão, todo ticker existe em
    `ativos` — o caso do não cadastrado tem teste próprio."""
    return {t.upper() for t in tickers}


def test_main_isola_falha_por_ticker(caplog):
    def fake_fetch_um(ticker):
        if ticker == "VALE3":
            raise RuntimeError("timeout na Brapi")
        return dict(COTACAO_VALIDA, symbol=ticker)

    cursor = _FakeCursor()
    fake_conn = _FakeConnection(cursor)
    with patch("src.etl.fetch_quotes.get_connection", _patched_get_connection(fake_conn)), \
         patch.object(fetch_quotes, "get_settings", return_value=_FakeSettings()), \
         patch.object(fetch_quotes, "orcamento_restante_hoje", return_value=1000), \
         patch.object(fetch_quotes, "tickers_cadastrados", side_effect=_todos_cadastrados), \
         patch.object(fetch_quotes, "fetch_um", side_effect=fake_fetch_um), \
         patch.object(fetch_quotes, "upsert", return_value=1) as mock_upsert:
        main(tickers=["PETR4", "VALE3", "ITUB4"])

    # PETR4 e ITUB4 continuam sendo processados mesmo com VALE3 falhando
    processados = [call.args[0][0]["symbol"] for call in mock_upsert.call_args_list]
    assert processados == ["PETR4", "ITUB4"]


def test_main_respeita_orcamento_diario(caplog):
    with patch("src.etl.fetch_quotes.get_connection", _patched_get_connection(_FakeConnection(_FakeCursor()))), \
         patch.object(fetch_quotes, "get_settings", return_value=_FakeSettings()), \
         patch.object(fetch_quotes, "orcamento_restante_hoje", return_value=1), \
         patch.object(fetch_quotes, "tickers_cadastrados", side_effect=_todos_cadastrados), \
         patch.object(fetch_quotes, "fetch_um", return_value=COTACAO_VALIDA) as mock_fetch, \
         patch.object(fetch_quotes, "upsert", return_value=1):
        main(tickers=["PETR4", "VALE3", "ITUB4"])

    # só o primeiro ticker cabe no orçamento (restante=1) — os outros dois
    # ficam de fora, sem nenhuma chamada à Brapi para eles
    chamados = [call.args[0] for call in mock_fetch.call_args_list]
    assert chamados == ["PETR4"]


def test_ticker_nao_cadastrado_nao_derruba_os_demais(caplog):
    """Sem o ativo em `ativos`, o INSERT em `cotacoes` violaria a FK. Antes
    desta verificação, o usuário via a mensagem crua do Postgres, que não
    diz o que fazer."""
    cursor = _FakeCursor()
    fake_conn = _FakeConnection(cursor)
    with caplog.at_level(logging.ERROR), \
         patch("src.etl.fetch_quotes.get_connection", _patched_get_connection(fake_conn)), \
         patch.object(fetch_quotes, "get_settings", return_value=_FakeSettings()), \
         patch.object(fetch_quotes, "orcamento_restante_hoje", return_value=1000), \
         patch.object(fetch_quotes, "tickers_cadastrados", return_value={"PETR4"}), \
         patch.object(fetch_quotes, "fetch_um", side_effect=lambda t: dict(COTACAO_VALIDA, symbol=t)), \
         patch.object(fetch_quotes, "upsert", return_value=1) as mock_upsert:
        main(tickers=["PETR4", "XXXX9"])

    processados = [call.args[0][0]["symbol"] for call in mock_upsert.call_args_list]
    assert processados == ["PETR4"], "o cadastrado continua sendo coletado"

    texto = caplog.text
    assert "XXXX9" in texto
    assert "não cadastrado" in texto
    assert "src.assets.manage add" in texto, "precisa dizer como resolver"
    assert "cotacoes_ticker_fkey" not in texto, "erro cru do banco não vaza"


def test_nenhum_ticker_cadastrado_encerra_sem_gastar_request():
    with patch("src.etl.fetch_quotes.get_connection", _patched_get_connection(_FakeConnection(_FakeCursor()))), \
         patch.object(fetch_quotes, "get_settings", return_value=_FakeSettings()), \
         patch.object(fetch_quotes, "orcamento_restante_hoje", return_value=1000), \
         patch.object(fetch_quotes, "tickers_cadastrados", return_value=set()), \
         patch.object(fetch_quotes, "fetch_um") as mock_fetch:
        main(tickers=["XXXX9"])

    mock_fetch.assert_not_called()
