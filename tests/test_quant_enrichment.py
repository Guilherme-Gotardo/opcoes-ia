"""Testes do enriquecimento quantitativo. Puros — sem banco e sem rede.

A validação central é contra REFERÊNCIA ANALÍTICA, não contra "o número que
saiu na primeira vez": a árvore CRR converge para Black-Scholes no caso
europeu, e é isso que os testes cobram. Um modelo que só concorda consigo
mesmo passaria por qualquer erro de unidade.
"""
import datetime as dt
import math

import pytest

from src.quant.enrichment import Enriquecimento, carregar_modelo, enriquecer
from src.quant.taxa import TaxaLivreRisco

pytest.importorskip("QuantLib", reason="enriquecimento exige QuantLib")

TAXA = TaxaLivreRisco(valor_aa=0.139, observada_em=dt.date(2026, 8, 14), fonte="teste")
AGORA = dt.datetime(2026, 8, 17, 12, 0, tzinfo=dt.timezone.utc)

BASE = dict(
    preco_objeto=40.0, strike=42.0, dias_vencimento=60,
    volatilidade_implicita=0.32, taxa=TAXA, agora=AGORA,
)


def _params(estilo_call="americana", estilo_put="europeia", **extra):
    return {
        "passos_arvore": 1024,
        "estilo_exercicio": {"CALL": estilo_call, "PUT": estilo_put},
        "dividend_yield_padrao": 0.0,
        "minimo_amostras_iv_percentil": 20,
        "minimo_opcoes_cadeia_skew": 3,
        **extra,
    }


def _black_scholes(tipo, s, k, r, q, sigma, t):
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    n = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))  # noqa: E731
    if tipo == "CALL":
        return s * math.exp(-q * t) * n(d1) - k * math.exp(-r * t) * n(d2)
    return k * math.exp(-r * t) * n(-d2) - s * math.exp(-q * t) * n(-d1)


# --- convergência contra a referência analítica ------------------------------

@pytest.mark.parametrize("tipo", ["CALL", "PUT"])
def test_crr_europeia_converge_para_black_scholes(tipo):
    r = enriquecer(tipo=tipo, params=_params("europeia", "europeia"), **BASE)
    esperado = _black_scholes(
        tipo, BASE["preco_objeto"], BASE["strike"], TAXA.valor_aa, 0.0,
        BASE["volatilidade_implicita"], BASE["dias_vencimento"] / 365.0,
    )
    # 1024 passos: erro da ordem de 1e-3. Tolerância maior mascararia um erro
    # de unidade; menor cobraria da árvore uma precisão que ela não tem.
    assert r.preco_teorico == pytest.approx(esperado, abs=2e-3)


def test_call_americana_sem_dividendo_vale_o_mesmo_que_europeia():
    """Exercer uma call americana antecipadamente nunca é ótimo sem
    dividendo — o prêmio de exercício antecipado é zero por construção. Se
    este teste falhar, a árvore está inventando valor."""
    americana = enriquecer(tipo="CALL", params=_params(estilo_call="americana"), **BASE)
    europeia = enriquecer(tipo="CALL", params=_params(estilo_call="europeia"), **BASE)
    assert americana.preco_teorico == pytest.approx(europeia.preco_teorico, abs=1e-9)


def test_put_americana_vale_mais_que_europeia():
    """A razão de o estilo ser POR CONTRATO. O plano assumia "opções B3 são
    americanas" para as duas pontas; aplicar isso numa put europeia da B3
    superestima o prêmio, e o viés cresce com o moneyness."""
    comum = {**BASE, "strike": 48.0}  # bem dentro do dinheiro, onde o viés é maior
    americana = enriquecer(tipo="PUT", params=_params(estilo_put="americana"), **comum)
    europeia = enriquecer(tipo="PUT", params=_params(estilo_put="europeia"), **comum)
    assert americana.preco_teorico > europeia.preco_teorico
    assert americana.preco_teorico / europeia.preco_teorico > 1.02


def test_probabilidades_de_call_e_put_somam_um():
    """P(S_T > K) + P(S_T < K) = 1. Pega inversão de sinal em d2."""
    call = enriquecer(tipo="CALL", params=_params(), **BASE)
    put = enriquecer(tipo="PUT", params=_params(), **BASE)
    soma = call.prob_exercicio_vencimento + put.prob_exercicio_vencimento
    assert soma == pytest.approx(1.0, abs=1e-12)


def test_prob_itm_e_menor_que_delta_na_call():
    """N(d2) < N(d1) sempre. Se inverterem, este teste cai."""
    call = enriquecer(tipo="CALL", params=_params(), **BASE)
    assert call.prob_exercicio_vencimento < call.delta_modelo


def test_gregas_tem_os_sinais_certos_na_call():
    r = enriquecer(tipo="CALL", params=_params(), **BASE)
    assert 0 < r.delta_modelo < 1
    assert r.gamma > 0
    assert r.theta_dia < 0, "opção comprada perde valor com o tempo"
    assert r.vega_pp > 0
    assert r.rho_pp > 0, "call ganha com juro maior"


def test_rho_da_put_e_negativo():
    assert enriquecer(tipo="PUT", params=_params(), **BASE).rho_pp < 0


def test_delta_cai_conforme_o_strike_sobe():
    deltas = [
        enriquecer(tipo="CALL", params=_params(), **{**BASE, "strike": k}).delta_modelo
        for k in (36.0, 40.0, 44.0, 48.0)
    ]
    assert deltas == sorted(deltas, reverse=True)


def test_vega_esta_por_ponto_percentual_e_nao_por_unidade():
    """A grega mais fácil de errar em 100x. Compara com a diferença finita
    explícita de 1 p.p. de vol."""
    base_preco = enriquecer(tipo="CALL", params=_params(), **BASE).preco_teorico
    mais_vol = enriquecer(
        tipo="CALL", params=_params(),
        **{**BASE, "volatilidade_implicita": BASE["volatilidade_implicita"] + 0.01},
    ).preco_teorico
    r = enriquecer(tipo="CALL", params=_params(), **BASE)
    assert r.vega_pp == pytest.approx(mais_vol - base_preco, rel=0.05)


def test_theta_esta_por_dia_e_nao_por_ano():
    """Theta por ano é ~365x maior. Uma opção de 40 reais não perde dezenas
    de reais por dia."""
    r = enriquecer(tipo="CALL", params=_params(), **BASE)
    assert -0.5 < r.theta_dia < 0


# --- dado ausente vira None + ressalva, nunca valor assumido -----------------

@pytest.mark.parametrize(
    "campo,rotulo",
    [
        ("preco_objeto", "preço do ativo-objeto"),
        ("strike", "strike"),
        ("dias_vencimento", "dias até o vencimento"),
        ("volatilidade_implicita", "volatilidade implícita"),
    ],
)
def test_insumo_ausente_nao_vira_estimativa(campo, rotulo):
    r = enriquecer(tipo="CALL", params=_params(), **{**BASE, campo: None})
    assert r.preco_teorico is None
    assert r.delta_modelo is None
    assert r.modelo == "indisponivel"
    assert any(rotulo in m for m in r.ressalvas), r.ressalvas


def test_sem_taxa_nao_calcula():
    r = enriquecer(tipo="CALL", params=_params(), **{**BASE, "taxa": None})
    assert r.preco_teorico is None
    assert any("taxa livre de risco" in m for m in r.ressalvas)


def test_estilo_e_registrado_mesmo_quando_nao_da_para_calcular():
    """Sem isto, uma linha vazia não diria nem qual premissa teria valido."""
    r = enriquecer(tipo="PUT", params=_params(), **{**BASE, "taxa": None})
    assert r.estilo_exercicio == "europeia"


@pytest.mark.parametrize("dias", [0, -3])
def test_opcao_vencida_nao_e_apreçada(dias):
    r = enriquecer(tipo="CALL", params=_params(), **{**BASE, "dias_vencimento": dias})
    assert r.preco_teorico is None
    assert any("vencida" in m for m in r.ressalvas)


@pytest.mark.parametrize(
    "campo,valor", [("volatilidade_implicita", 0.0), ("preco_objeto", -1.0), ("strike", 0.0)]
)
def test_valores_nao_positivos_sao_recusados(campo, valor):
    r = enriquecer(tipo="CALL", params=_params(), **{**BASE, campo: valor})
    assert r.preco_teorico is None
    assert any("positivos" in m for m in r.ressalvas)


# --- percentil de IV e skew --------------------------------------------------

def test_percentil_de_iv_mede_a_posicao_na_distribuicao():
    historico = [0.10 + i * 0.01 for i in range(40)]  # 0.10 .. 0.49
    r = enriquecer(
        tipo="CALL", params=_params(), ivs_historicas=historico,
        **{**BASE, "volatilidade_implicita": 0.30},
    )
    # 20 das 40 observações estão abaixo de 0.30
    assert r.iv_percentil_252d == pytest.approx(0.5)


def test_percentil_omitido_com_amostra_curta():
    r = enriquecer(tipo="CALL", params=_params(), ivs_historicas=[0.2] * 5, **BASE)
    assert r.iv_percentil_252d is None
    assert any("mínimo 20" in m for m in r.ressalvas)
    # mas o resto do modelo saiu: uma amostra curta não invalida as gregas
    assert r.delta_modelo is not None


def test_skew_compara_com_a_media_da_cadeia():
    r = enriquecer(
        tipo="CALL", params=_params(), ivs_da_cadeia=[0.28, 0.30, 0.32, 0.30],
        **{**BASE, "volatilidade_implicita": 0.35},
    )
    assert r.skew_vs_cadeia == pytest.approx(0.35 - 0.30)


def test_skew_omitido_com_cadeia_rasa():
    r = enriquecer(tipo="CALL", params=_params(), ivs_da_cadeia=[0.30], **BASE)
    assert r.skew_vs_cadeia is None
    assert any("skew omitido" in m for m in r.ressalvas)


# --- auditoria ---------------------------------------------------------------

def test_resultado_carrega_o_que_permite_reconstruir_a_conta():
    r = enriquecer(tipo="CALL", params=_params(), **BASE)
    assert r.modelo == "CRR-binomial-1024"
    assert r.estilo_exercicio == "americana"
    assert r.taxa_livre_risco == TAXA.valor_aa
    assert r.taxa_observada_em == TAXA.observada_em
    assert r.volatilidade_usada == BASE["volatilidade_implicita"]
    assert r.calculado_em == AGORA


def test_americana_avisa_que_prob_nao_inclui_exercicio_antecipado():
    r = enriquecer(tipo="CALL", params=_params(estilo_call="americana"), **BASE)
    assert any("exercício antecipado não está incluído" in m for m in r.ressalvas)


def test_europeia_nao_emite_a_ressalva_de_exercicio_antecipado():
    r = enriquecer(tipo="PUT", params=_params(), **BASE)
    assert not any("exercício antecipado" in m for m in r.ressalvas)


def test_enriquecimento_vazio_e_o_default_do_dataclass():
    """Uma linha "não deu para calcular" precisa ser construível sem passar
    quinze `None` na mão — é o caminho usado quando a opção nem existe."""
    vazio = Enriquecimento()
    assert vazio.modelo == "indisponivel"
    assert vazio.preco_teorico is None
    assert vazio.ressalvas == ()


def test_motor_de_decisao_nao_depende_do_modelo_quantitativo():
    """A garantia central do plano, verificada em vez de prometida.

    `strategy/covered.py` não pode importar `src.quant`. O orquestrador chama
    o enriquecimento como outra etapa, depois do commit da avaliação.
    """
    import ast
    from pathlib import Path

    fonte = Path("src/strategy/covered.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)

    def nomes_importados(no):
        if isinstance(no, ast.Import):
            return [a.name for a in no.names]
        if isinstance(no, ast.ImportFrom):
            return [no.module or ""]
        return []

    topo = [
        nome
        for no in arvore.body                      # só o nível do módulo
        for nome in nomes_importados(no)
    ]
    assert not any(n.startswith("src.quant") for n in topo), (
        f"covered.py importa src.quant no topo do módulo: {topo}. "
        "O enriquecimento pertence ao orquestrador, fora do motor de decisão."
    )
    assert "src.quant" not in fonte


def test_modelo_do_repositorio_carrega_e_e_coerente():
    """O arquivo real: um `modelo.yaml` quebrado só apareceria no primeiro
    disparo com opção coletada."""
    carregar_modelo.cache_clear()
    p = carregar_modelo()
    assert p["passos_arvore"] >= 2
    assert set(p["estilo_exercicio"]) == {"CALL", "PUT"}
    assert set(p["estilo_exercicio"].values()) <= {"americana", "europeia"}
    carregar_modelo.cache_clear()
