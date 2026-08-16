"""Testes do ETL de candles.

O foco é o que já quebrou de verdade neste projeto: mapeamento de campo do
provedor (o bug de `fetch_quotes` em 2026-08-14) e gravação parcial. A
chamada HTTP e o banco são dublados — o que se prova é a tradução do formato
e a recusa do que está incompleto.
"""
import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from src.etl import fetch_candles
from src.etl.fetch_candles import FormatoRespostaInvalido, _vela, fetch_um, upsert

PONTO = {
    "date": 1786734000, "open": 41.96, "high": 42.01,
    "low": 41.92, "close": 41.98, "volume": 4007300,
}


def _resposta(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


# --- tradução do formato ----------------------------------------------------

def test_vela_traduz_epoch_para_utc():
    ticker, abertura_em, o, h, l, c, vol = _vela(PONTO, "PETR4")
    assert ticker == "PETR4"
    assert abertura_em.tzinfo is dt.timezone.utc
    assert (o, h, l, c) == (41.96, 42.01, 41.92, 41.98)
    assert vol == 4007300


@pytest.mark.parametrize("faltando", ["date", "open", "high", "low", "close"])
def test_vela_incompleta_e_recusada(faltando):
    """Meia vela é pior do que vela nenhuma: o gráfico desenharia como se
    fosse dado bom."""
    ponto = {**PONTO, faltando: None}
    with pytest.raises(FormatoRespostaInvalido, match=faltando):
        _vela(ponto, "PETR4")


def test_volume_ausente_e_aceito():
    """Volume é opcional na tabela — só ele não invalida a vela."""
    _, _, _, _, _, _, vol = _vela({**PONTO, "volume": None}, "PETR4")
    assert vol is None


# --- chamada ----------------------------------------------------------------

def test_fetch_um_pede_range_e_interval():
    with patch.object(fetch_candles, "requests") as req, \
         patch.object(fetch_candles, "get_settings") as cfg:
        cfg.return_value.brapi_token = "t"
        req.get.return_value = _resposta(
            {"results": [{"historicalDataPrice": [PONTO]}]}
        )
        pontos = fetch_um("PETR4", "1h", "5d")

    assert pontos == [PONTO]
    _, kwargs = req.get.call_args
    assert kwargs["params"] == {"range": "5d", "interval": "1h"}


def test_historico_vazio_nao_e_erro():
    """`range=1d` devolveu lista vazia contra a API real — dia sem pregão
    não é formato inválido."""
    with patch.object(fetch_candles, "requests") as req, \
         patch.object(fetch_candles, "get_settings") as cfg:
        cfg.return_value.brapi_token = "t"
        req.get.return_value = _resposta(
            {"results": [{"historicalDataPrice": []}]}
        )
        assert fetch_um("PETR4", "1h", "1d") == []


def test_resposta_sem_historico_e_formato_invalido():
    with patch.object(fetch_candles, "requests") as req, \
         patch.object(fetch_candles, "get_settings") as cfg:
        cfg.return_value.brapi_token = "t"
        req.get.return_value = _resposta({"results": [{"symbol": "PETR4"}]})
        with pytest.raises(FormatoRespostaInvalido, match="historicalDataPrice"):
            fetch_um("PETR4", "1h", "5d")


# --- gravação ---------------------------------------------------------------

def test_upsert_atualiza_a_mesma_janela():
    """A vela do período corrente ainda se move; recoletar corrige a linha
    em vez de criar uma segunda verdade para a mesma janela."""
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    with patch.object(fetch_candles, "get_connection") as gc:
        gc.return_value.__enter__.return_value = conn
        gravadas = upsert("PETR4", "1h", [PONTO])

    assert gravadas == 1
    sql = cur.execute.call_args[0][0]
    assert "ON CONFLICT (ticker, intervalo, abertura_em) DO UPDATE" in sql
    assert conn.commit.called


def test_upsert_de_lista_vazia_nao_toca_o_banco():
    with patch.object(fetch_candles, "get_connection") as gc:
        assert upsert("PETR4", "1h", []) == 0
        assert not gc.called


def test_upsert_recusa_o_lote_inteiro_se_uma_vela_estiver_incompleta():
    """As velas são traduzidas ANTES de abrir transação: gravar metade do
    lote deixaria um buraco silencioso no meio da série."""
    with patch.object(fetch_candles, "get_connection") as gc:
        with pytest.raises(FormatoRespostaInvalido):
            upsert("PETR4", "1h", [PONTO, {**PONTO, "close": None}])
        assert not gc.called, "nenhuma conexão aberta antes de validar o lote"


# --- orquestração -----------------------------------------------------------

def test_intervalo_sem_janela_conhecida_nao_chama_a_api():
    with patch.object(fetch_candles, "fetch_um") as f, \
         patch.object(fetch_candles, "_tickers_da_carteira", return_value=["PETR4"]):
        fetch_candles.main(intervalo="42x")
    assert not f.called, "combinação inválida não gasta request"


def test_ticker_nao_cadastrado_nao_gasta_request():
    """`candles.ticker` tem FK para `ativos`: sem cadastro o INSERT seria
    recusado, e o request teria sido gasto à toa."""
    with patch.object(fetch_candles, "tickers_cadastrados", return_value=set()), \
         patch.object(fetch_candles, "fetch_um") as f:
        fetch_candles.main(tickers=["XPTO3"], intervalo="1h")
    assert not f.called
