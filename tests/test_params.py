"""Smoke test: garante que params.yaml da skill é válido e tem as chaves
esperadas, para não quebrar silenciosamente quando alguém editar o arquivo.

Também exercita a validação dos parâmetros que mudam postura de risco —
valor malformado precisa falhar alto, nunca cair no padrão em silêncio."""
from pathlib import Path

import pytest
import yaml

from src.market.valuation import (
    DEFAULT_FRESCOR_HORAS,
    ParametroInvalido,
    frescor_maximo_horas,
)

PARAMS_PATH = (
    Path(__file__).parent.parent
    / "skills" / "covered-options-strategy" / "params.yaml"
)

CHAVES_ESPERADAS = {
    "iv_rank_minimo",
    "delta_min",
    "delta_max",
    "dias_vencimento_min",
    "dias_vencimento_max",
    "premio_minimo_pct",
    "exposicao_maxima_pct_ativo",
    "dias_bloqueio_antes_resultado",
    "cotacao_frescor_maximo_horas",
}


def test_params_existe_e_tem_chaves_esperadas():
    assert PARAMS_PATH.exists(), f"params.yaml não encontrado em {PARAMS_PATH}"
    dados = yaml.safe_load(PARAMS_PATH.read_text())
    assert CHAVES_ESPERADAS.issubset(dados.keys())


def test_delta_min_menor_que_delta_max():
    dados = yaml.safe_load(PARAMS_PATH.read_text())
    assert dados["delta_min"] < dados["delta_max"]


# --- Janela de frescor de cotação ------------------------------------------

def test_frescor_do_arquivo_real_e_aceito_pelo_leitor():
    dados = yaml.safe_load(PARAMS_PATH.read_text())
    assert frescor_maximo_horas(dados) == float(dados["cotacao_frescor_maximo_horas"])


def test_frescor_ausente_cai_no_padrao_conservador():
    assert frescor_maximo_horas({}) == float(DEFAULT_FRESCOR_HORAS)


def test_frescor_valido_e_respeitado():
    assert frescor_maximo_horas({"cotacao_frescor_maximo_horas": 12}) == 12.0
    assert frescor_maximo_horas({"cotacao_frescor_maximo_horas": 6.5}) == 6.5


@pytest.mark.parametrize("valor", [0, -5, "muitas", None, True, float("inf")])
def test_frescor_invalido_falha_alto_em_vez_de_usar_o_padrao(valor):
    """Cair no padrão aqui mudaria a postura de risco sem o usuário
    perceber — mesma regra de `politica_resultado_desconhecido`."""
    with pytest.raises(ParametroInvalido):
        frescor_maximo_horas({"cotacao_frescor_maximo_horas": valor})
