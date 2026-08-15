"""Smoke test: garante que params.yaml da skill é válido e tem as chaves
esperadas, para não quebrar silenciosamente quando alguém editar o arquivo."""
from pathlib import Path

import yaml

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
}


def test_params_existe_e_tem_chaves_esperadas():
    assert PARAMS_PATH.exists(), f"params.yaml não encontrado em {PARAMS_PATH}"
    dados = yaml.safe_load(PARAMS_PATH.read_text())
    assert CHAVES_ESPERADAS.issubset(dados.keys())


def test_delta_min_menor_que_delta_max():
    dados = yaml.safe_load(PARAMS_PATH.read_text())
    assert dados["delta_min"] < dados["delta_max"]
