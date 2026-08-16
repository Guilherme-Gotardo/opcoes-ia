"""Testes do cálculo de resultado por operação.

Módulo puro: sem banco e sem rede. Os parâmetros entram como dicionário,
com custos zerados na maioria dos casos para isolar a conta que está sendo
verificada.
"""
import pytest

from src.fiscal.calculo import (
    ParametroFiscalInvalido,
    avaliar_operacao,
    resultado_da_opcao,
)

SEM_CUSTO = {
    "aliquota_opcoes_pct": 15.0,
    "aliquota_day_trade_pct": 20.0,
    "aliquota_acoes_pct": 15.0,
    "corretagem_por_operacao": 0.0,
    "emolumentos_pct": 0.0,
}


def _operacao(**kwargs):
    base = dict(
        quantidade=-100, premio_unitario=1.15, motivo_fechamento="expirada",
        preco_fechamento=None, strike=45.0, preco_medio_acao=32.5,
        params=SEM_CUSTO,
    )
    return avaliar_operacao(**{**base, **kwargs})


# --- opção isolada ----------------------------------------------------------

def test_call_lancada_que_expira_fica_com_o_premio_inteiro():
    r = _operacao(motivo_fechamento="expirada")
    assert r.resultado_bruto == pytest.approx(115.0)   # 100 × 1,15
    assert r.imposto == pytest.approx(17.25)           # 15% de 115
    assert r.resultado_liquido == pytest.approx(97.75)


def test_recompra_desconta_o_custo_de_saida():
    r = _operacao(motivo_fechamento="recomprada", preco_fechamento=0.40)
    assert r.resultado_bruto == pytest.approx(75.0)    # 115 − 40
    assert r.resultado_liquido == pytest.approx(63.75)


def test_recompra_com_prejuizo_nao_gera_imposto():
    """Prejuízo não vira crédito aqui — compensação é da apuração mensal,
    que este módulo declaradamente não faz."""
    r = _operacao(motivo_fechamento="recomprada", preco_fechamento=2.00)
    assert r.resultado_bruto == pytest.approx(-85.0)
    assert r.imposto == 0.0
    assert r.resultado_liquido == pytest.approx(-85.0)


def test_day_trade_usa_a_aliquota_maior():
    comum = resultado_da_opcao(-100, 1.15, 0.0, SEM_CUSTO, day_trade=False)
    day = resultado_da_opcao(-100, 1.15, 0.0, SEM_CUSTO, day_trade=True)
    assert comum.aliquota_pct == 15.0
    assert day.aliquota_pct == 20.0
    assert day.imposto > comum.imposto


def test_opcao_comprada_inverte_o_sinal():
    """Comprada paga o prêmio na entrada e recebe na saída."""
    perna = resultado_da_opcao(100, 1.00, 1.60, SEM_CUSTO)
    assert perna.resultado_bruto == pytest.approx(60.0)


# --- exercício: duas categorias ---------------------------------------------

def test_exercicio_separa_as_duas_pernas():
    """A isenção mensal vale para ação e não para opção — somar as pernas
    antes de tributar produziria um número que não segue regra nenhuma."""
    r = _operacao(motivo_fechamento="exercida", strike=45.0, preco_medio_acao=32.5)
    nomes = [p.nome for p in r.pernas]
    assert nomes == ["opção", "ação entregue ao strike"]

    opcao, acao = r.pernas
    assert opcao.resultado_bruto == pytest.approx(115.0)
    assert acao.resultado_bruto == pytest.approx(1250.0)   # (45 − 32,5) × 100
    assert r.resultado_bruto == pytest.approx(1365.0)
    # Impostos calculados por perna, não sobre o total.
    assert r.imposto == pytest.approx(17.25 + 187.5)


def test_exercicio_sem_preco_medio_declara_a_lacuna():
    r = _operacao(motivo_fechamento="exercida", preco_medio_acao=None)
    assert len(r.pernas) == 1, "só a perna da opção"
    assert any("ficou de fora" in m for m in r.ressalvas)


def test_recompra_sem_preco_avisa_que_superestima():
    """Silenciar aqui mostraria lucro maior do que o real."""
    r = _operacao(motivo_fechamento="recomprada", preco_fechamento=None)
    assert any("SUPERESTIMADO" in m for m in r.ressalvas)


# --- garantias de honestidade ----------------------------------------------

def test_toda_saida_e_marcada_como_estimativa():
    assert _operacao().estimativa is True


def test_operacao_aberta_nao_inventa_resultado_realizado():
    r = _operacao(motivo_fechamento=None)
    assert r.pernas == []
    assert r.resultado_liquido == 0.0
    assert any("em aberto" in m for m in r.ressalvas)


def test_motivo_desconhecido_falha_alto():
    with pytest.raises(ParametroFiscalInvalido, match="motivo_fechamento"):
        _operacao(motivo_fechamento="virou_po")


def test_aliquota_invalida_falha_alto():
    """Alíquota lida errado mudaria em silêncio o número que decide se a
    operação valeu a pena."""
    with pytest.raises(ParametroFiscalInvalido, match="aliquota_opcoes_pct"):
        _operacao(params={**SEM_CUSTO, "aliquota_opcoes_pct": "quinze"})
    with pytest.raises(ParametroFiscalInvalido):
        _operacao(params={**SEM_CUSTO, "aliquota_opcoes_pct": -5})


def test_custos_entram_na_base_do_imposto():
    """Emolumentos reduzem o ganho ANTES de tributar, não depois."""
    com_custo = {**SEM_CUSTO, "corretagem_por_operacao": 5.0}
    r = _operacao(motivo_fechamento="expirada", params=com_custo)
    assert r.custos == pytest.approx(5.0)
    assert r.imposto == pytest.approx((115.0 - 5.0) * 0.15)
    assert r.resultado_liquido == pytest.approx(115.0 - 5.0 - r.imposto)
