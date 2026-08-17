"""Testes de src.etl.fetch_options — validação defensiva do formato da
resposta e isolamento de falha por ticker (não dependem de Postgres real)."""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.etl import fetch_options
from src.etl.fetch_options import (
    CHAVES_ESPERADAS,
    FormatoRespostaInvalido,
    RecursoIndisponivelNoPlano,
    _validar_formato,
    fetch,
    main,
    upsert,
)
from src.etl.result import EstadoAlvo, EstadoColeta

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
    settings = MagicMock(oplab_token="token")

    def fake_fetch(ticker):
        if ticker == "VALE3":
            raise RuntimeError("timeout na API")
        return [OPCAO_VALIDA]

    with patch.object(fetch_options, "get_options_settings", return_value=settings), \
         patch.object(fetch_options, "fetch", side_effect=fake_fetch), \
         patch.object(fetch_options, "upsert", return_value=1) as mock_upsert:
        resultado = main(tickers=["PETR4", "VALE3", "ITUB4"])

    # PETR4 e ITUB4 continuam sendo processados mesmo com VALE3 falhando
    chamados = [call.args[0] for call in mock_upsert.call_args_list]
    assert chamados == ["PETR4", "ITUB4"]
    assert resultado.estado == EstadoColeta.PARCIAL
    assert resultado.alvos_falhos == 1


def test_main_lista_vazia_explicita_nao_consulta_universo():
    with patch.object(fetch_options, "_tickers_objeto_da_carteira") as universo, \
         patch.object(fetch_options, "get_options_settings") as settings:
        resultado = main(tickers=[])

    assert resultado.estado == EstadoColeta.PULADO
    assert resultado.motivo == "universo_vazio"
    universo.assert_not_called()
    settings.assert_not_called()


def test_main_sem_token_bloqueia_todos_sem_http():
    settings = MagicMock(oplab_token="")
    with patch.object(fetch_options, "get_options_settings", return_value=settings) as get_settings, \
         patch.object(fetch_options.requests, "get") as http_get:
        resultado = main(tickers=["PETR4", "VALE3"])

    assert resultado.estado == EstadoColeta.BLOQUEADO
    assert [item.estado for item in resultado.detalhes] == [
        EstadoAlvo.BLOQUEADO, EstadoAlvo.BLOQUEADO,
    ]
    assert resultado.alvos_tentados == 0
    get_settings.assert_called_once_with()
    http_get.assert_not_called()


def test_fetch_classifica_codigo_conhecido_de_plano():
    settings = MagicMock(oplab_token="token")
    resposta = MagicMock(status_code=403)
    resposta.json.return_value = {"code": "FEATURE_NOT_AVAILABLE"}
    with patch.object(fetch_options, "get_options_settings", return_value=settings), \
         patch.object(fetch_options.requests, "get", return_value=resposta):
        with pytest.raises(RecursoIndisponivelNoPlano):
            fetch("PETR4")
    resposta.raise_for_status.assert_not_called()


@pytest.mark.parametrize("status_code", [401, 403])
def test_fetch_nao_classifica_erro_de_autorizacao_generico_como_bloqueio(status_code):
    settings = MagicMock(oplab_token="token")
    resposta = MagicMock(status_code=status_code)
    resposta.json.return_value = {"message": "forbidden"}
    resposta.raise_for_status.side_effect = requests.HTTPError(str(status_code))
    with patch.object(fetch_options, "get_options_settings", return_value=settings), \
         patch.object(fetch_options.requests, "get", return_value=resposta):
        with pytest.raises(requests.HTTPError):
            fetch("PETR4")


def test_main_sucesso_bloqueio_e_erro_e_parcial():
    settings = MagicMock(oplab_token="token")

    def fake_fetch(ticker):
        if ticker == "VALE3":
            raise RecursoIndisponivelNoPlano("upgrade necessário")
        if ticker == "ITUB4":
            raise requests.Timeout("timeout")
        return []

    with patch.object(fetch_options, "get_options_settings", return_value=settings), \
         patch.object(fetch_options, "fetch", side_effect=fake_fetch), \
         patch.object(fetch_options, "upsert", return_value=0):
        resultado = main(tickers=["PETR4", "VALE3", "ITUB4"])

    assert resultado.estado == EstadoColeta.PARCIAL
    assert [item.estado for item in resultado.detalhes] == [
        EstadoAlvo.SUCESSO, EstadoAlvo.BLOQUEADO, EstadoAlvo.FALHA,
    ]
    assert resultado.registros_persistidos == 0


def test_main_erros_ordinarios_em_todos_os_tickers_sao_falha():
    settings = MagicMock(oplab_token="token")
    with patch.object(fetch_options, "get_options_settings", return_value=settings), \
         patch.object(fetch_options, "fetch", side_effect=requests.Timeout("timeout")):
        resultado = main(tickers=["PETR4", "VALE3"])

    assert resultado.estado == EstadoColeta.FALHA
    assert resultado.alvos_falhos == 2
