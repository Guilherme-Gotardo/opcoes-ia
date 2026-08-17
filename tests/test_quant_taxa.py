"""Testes da taxa livre de risco. A rede é dublada — o objetivo é a
tradução da resposta do BCB, não a disponibilidade do BCB.

O que estes testes protegem: a taxa é o único insumo do modelo que vem de
fora e não passa pelo ETL. Um erro de unidade aqui (percentual lido como
fração) não quebraria nada visivelmente — só deslocaria todo preço teórico e
toda probabilidade, em silêncio.
"""
import datetime as dt
from unittest.mock import patch

import pytest
import requests

from src.quant import taxa as mod


class _Resp:
    def __init__(self, payload, erro=None):
        self._payload = payload
        self._erro = erro

    def raise_for_status(self):
        if self._erro:
            raise self._erro

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _com(payload, erro=None):
    return patch.object(mod.requests, "get", return_value=_Resp(payload, erro))


def test_converte_percentual_para_fracao():
    """13.90% a.a. tem que virar 0.139, não 13.90. O modelo consome fração,
    e um fator 100 aqui produziria probabilidades absurdas sem erro nenhum."""
    with _com([{"data": "14/08/2026", "valor": "13.90"}]):
        t = mod.buscar()
    assert t.valor_aa == pytest.approx(0.139)
    assert t.observada_em == dt.date(2026, 8, 14)
    assert "1178" in t.fonte


def test_le_a_data_no_formato_brasileiro():
    """dd/MM/yyyy. Interpretado como MM/dd, 03/08 viraria 8 de março e a
    idade da taxa ficaria meses errada."""
    with _com([{"data": "03/08/2026", "valor": "10.50"}]):
        assert mod.buscar().observada_em == dt.date(2026, 8, 3)


def test_usa_o_ultimo_registro_da_serie():
    with _com([{"data": "13/08/2026", "valor": "13.75"},
               {"data": "14/08/2026", "valor": "13.90"}]):
        assert mod.buscar().observada_em == dt.date(2026, 8, 14)


@pytest.mark.parametrize("payload", [[], None])
def test_serie_vazia_devolve_none(payload):
    with _com(payload):
        assert mod.buscar() is None


@pytest.mark.parametrize(
    "registro",
    [
        {"data": "14/08/2026"},                    # sem valor
        {"valor": "13.90"},                        # sem data
        {"data": "2026-08-14", "valor": "13.90"},  # formato ISO, não o do SGS
        {"data": "14/08/2026", "valor": "treze"},
    ],
)
def test_formato_inesperado_devolve_none_em_vez_de_lixo(registro):
    with _com([registro]):
        assert mod.buscar() is None


@pytest.mark.parametrize("valor", ["0", "-1.5", "100", "1390"])
def test_valor_fora_da_faixa_plausivel_e_recusado(valor):
    """1390 seria a Selic em pontos-base — erro de unidade que passaria
    despercebido se a única checagem fosse "é número?"."""
    with _com([{"data": "14/08/2026", "valor": valor}]):
        assert mod.buscar() is None


def test_falha_de_rede_devolve_none_e_nao_levanta():
    """Quem chama decide o fallback. Levantar aqui derrubaria o
    enriquecimento inteiro por um timeout."""
    with patch.object(mod.requests, "get", side_effect=requests.Timeout("estourou")):
        assert mod.buscar() is None


def test_erro_http_devolve_none():
    with _com([], erro=requests.HTTPError("500")):
        assert mod.buscar() is None


def test_json_invalido_devolve_none():
    with _com(ValueError("não é json")):
        assert mod.buscar() is None


def test_idade_em_dias():
    t = mod.TaxaLivreRisco(0.139, dt.date(2026, 8, 10), "teste")
    assert t.idade_em_dias(dt.date(2026, 8, 17)) == 7
