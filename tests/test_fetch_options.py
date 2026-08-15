"""Testes de src.etl.fetch_options — validação defensiva do formato da
resposta e isolamento de falha por ticker (não dependem de Postgres real)."""
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from src.etl import fetch_options
from src.etl.fetch_options import (
    CHAVES_ESPERADAS,
    FormatoRespostaInvalido,
    _validar_formato,
    main,
    upsert,
)

OPCAO_VALIDA = {
    "symbol": "PETRJ380", "type": "CALL", "strike": 38.0, "due_date": "2026-09-21",
    "close": 0.85, "delta": 0.28, "gamma": 0.02, "theta": -0.03, "vega": 0.05,
    "rho": 0.01, "volatility": 0.35, "iv_rank": 61.0,
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


def test_validar_formato_aceita_opcao_completa():
    _validar_formato("PETR4", [OPCAO_VALIDA])  # não deve levantar


def test_validar_formato_rejeita_chave_faltando():
    incompleta = dict(OPCAO_VALIDA)
    del incompleta["delta"]
    with pytest.raises(FormatoRespostaInvalido):
        _validar_formato("PETR4", [incompleta])


def test_chaves_esperadas_cobre_gregas_e_iv():
    assert {"delta", "gamma", "theta", "vega", "rho", "volatility", "iv_rank"} <= CHAVES_ESPERADAS


def test_upsert_nao_grava_quando_formato_invalido():
    incompleta = dict(OPCAO_VALIDA)
    del incompleta["iv_rank"]
    cursor = _FakeCursor()
    fake_conn = _FakeConnection(cursor)
    with patch("src.etl.fetch_options.get_connection", _patched_get_connection(fake_conn)):
        with pytest.raises(FormatoRespostaInvalido):
            upsert("PETR4", [incompleta])
    assert cursor.queries == []
    assert not fake_conn.committed


def test_upsert_grava_quando_formato_valido():
    cursor = _FakeCursor()
    fake_conn = _FakeConnection(cursor)
    with patch("src.etl.fetch_options.get_connection", _patched_get_connection(fake_conn)):
        total = upsert("PETR4", [OPCAO_VALIDA])
    assert total == 1
    assert fake_conn.committed
    assert "INSERT INTO opcoes" in cursor.queries[0][0]


def test_main_isola_falha_por_ticker(caplog):
    def fake_fetch(ticker):
        if ticker == "VALE3":
            raise RuntimeError("timeout na API")
        return [OPCAO_VALIDA]

    with patch.object(fetch_options, "fetch", side_effect=fake_fetch), \
         patch.object(fetch_options, "upsert", return_value=1) as mock_upsert:
        main(tickers=["PETR4", "VALE3", "ITUB4"])

    # PETR4 e ITUB4 continuam sendo processados mesmo com VALE3 falhando
    chamados = [call.args[0] for call in mock_upsert.call_args_list]
    assert chamados == ["PETR4", "ITUB4"]
