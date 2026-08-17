"""Enriquecimento quantitativo — contexto numérico, nunca critério.

O QUE ISTO É
------------
Dado uma opção e os insumos de mercado, calcula gregas, preço teórico,
probabilidade de exercício no vencimento, percentil de IV e skew contra a
cadeia. É **função pura**: não abre banco, não faz rede, não lê relógio sem
receber. Quem junta os insumos é `src/quant/pipeline.py`.

O QUE ISTO NÃO É
----------------
Não é gate. Nada aqui aprova ou reprova operação — `strategy/covered.py`
segue determinístico e não importa este módulo. A separação é a razão de o
resultado ir para uma TABELA PRÓPRIA (`enriquecimento_quant`) em vez de
entrar em `criterios_json`: são naturezas diferentes de dado, e misturá-las
faria um número de contexto parecer um critério que alguém precisou passar.

Se um dia `prob_exercicio_vencimento` virar critério de verdade, ele entra
em `_CAMPOS_MERCADO_OBRIGATORIOS` e em `params.yaml` seguindo o padrão de
três estados que já existe — não por esta porta.

A REGRA QUE ATRAVESSA TUDO
--------------------------
Insumo ausente vira `None` + ressalva, nunca valor assumido. Sem IV não há
grega; sem taxa não há desconto; sem histórico não há percentil. A
alternativa — "usa 20% de vol que é o normal" — produziria um número com a
mesma aparência dos calculados de verdade, e ninguém auditando meses depois
distinguiria os dois.

UNIDADES (a fonte de erro mais provável neste arquivo)
------------------------------------------------------
- `volatilidade` e `taxa_livre_risco`: FRAÇÃO ao ano (0.32 = 32% a.a.).
- `theta`: por DIA CORRIDO. A QuantLib devolve por ano; dividimos por 365
  aqui, uma vez, para não haver duas convenções circulando.
- `vega`: por 1 PONTO PERCENTUAL de vol (0.01 na fração). A QuantLib não
  fornece vega para engine binomial — é diferença finita central aqui.
- `rho`: por 1 ponto percentual de taxa, mesma construção.
- `prob_exercicio_vencimento`: probabilidade RISCO-NEUTRA, entre 0 e 1.
"""
import datetime as dt
import functools
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import yaml

from src.quant.taxa import TaxaLivreRisco

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

ARQUIVO_MODELO = Path(__file__).resolve().parent / "modelo.yaml"

DIAS_NO_ANO = 365.0
#: Bumps das diferenças finitas: 1 ponto percentual de vol, 1 ponto
#: percentual de taxa. Grandes o bastante para o ruído da árvore não dominar,
#: pequenos o bastante para a derivada ainda ser local.
_BUMP_VOL = 0.01
_BUMP_TAXA = 0.01


class ModeloIndisponivel(RuntimeError):
    """QuantLib não está instalada. Enriquecimento é opcional por construção:
    o pipeline determinístico roda sem ele, e quem chama trata isto como
    'sem contexto quantitativo hoje', não como falha da avaliação."""


@dataclass(frozen=True)
class Enriquecimento:
    """Contexto quantitativo de UMA opção. Todo campo numérico é opcional —
    `None` quer dizer "não deu para calcular", e `ressalvas` diz por quê."""

    #: Grega do MODELO. Deliberadamente NÃO se chama `delta`: `opcoes.delta`
    #: vem do provedor e é o que o critério de gate usa. Ter os dois com o
    #: mesmo nome convidaria a trocar um pelo outro em alguma consulta, e a
    #: troca só apareceria como sugestão estranha meses depois.
    delta_modelo: float | None = None
    gamma: float | None = None
    theta_dia: float | None = None
    vega_pp: float | None = None
    rho_pp: float | None = None
    preco_teorico: float | None = None
    #: Probabilidade risco-neutra de terminar dentro do dinheiro NO
    #: VENCIMENTO. Não inclui exercício antecipado — ver a ressalva emitida
    #: para contratos americanos.
    prob_exercicio_vencimento: float | None = None
    #: Onde a IV de hoje cai na distribuição histórica do próprio ativo, em
    #: fração (0.8 = mais alta que 80% do histórico).
    iv_percentil_252d: float | None = None
    #: IV desta opção menos a IV média da cadeia no mesmo vencimento, em
    #: pontos de fração (0.03 = 3 pontos percentuais acima da cadeia).
    skew_vs_cadeia: float | None = None

    # --- auditoria: sem isto, o número não é reconstruível depois ---
    modelo: str = "indisponivel"
    estilo_exercicio: str | None = None
    taxa_livre_risco: float | None = None
    taxa_observada_em: dt.date | None = None
    volatilidade_usada: float | None = None
    calculado_em: dt.datetime | None = None
    ressalvas: tuple[str, ...] = field(default_factory=tuple)


@functools.cache
def carregar_modelo(caminho: Path | None = None) -> dict:
    caminho = caminho or ARQUIVO_MODELO
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    passos = dados.get("passos_arvore")
    if not isinstance(passos, int) or passos < 2:
        raise ValueError(
            f"{caminho.name}: `passos_arvore` deve ser inteiro >= 2, veio {passos!r}."
        )
    return dados


def _quantlib():
    try:
        import QuantLib as ql  # noqa: PLC0415 — import opcional, adiado de propósito
    except ImportError as e:  # pragma: no cover - depende do ambiente
        raise ModeloIndisponivel(
            "QuantLib não instalada. `pip install QuantLib` para habilitar o "
            "enriquecimento quantitativo; sem ela o pipeline determinístico "
            "segue funcionando, apenas sem contexto de modelo."
        ) from e
    return ql


def _estilo(tipo: str, params: dict) -> str:
    return (params.get("estilo_exercicio") or {}).get(tipo.upper(), "europeia")


def _montar(ql, *, tipo, estilo, preco_objeto, strike, vencimento, hoje,
            volatilidade, taxa_aa, dividend_yield):
    """Opção QuantLib apreçada por árvore CRR, pronta para consulta."""
    calendario = ql.NullCalendar()
    contagem = ql.Actual365Fixed()
    ql.Settings.instance().evaluationDate = hoje

    payoff = ql.PlainVanillaPayoff(
        ql.Option.Call if tipo.upper() == "CALL" else ql.Option.Put, strike
    )
    exercicio = (
        ql.AmericanExercise(hoje, vencimento)
        if estilo == "americana"
        else ql.EuropeanExercise(vencimento)
    )

    spot = ql.QuoteHandle(ql.SimpleQuote(preco_objeto))
    curva_taxa = ql.YieldTermStructureHandle(
        ql.FlatForward(hoje, taxa_aa, contagem)
    )
    curva_div = ql.YieldTermStructureHandle(
        ql.FlatForward(hoje, dividend_yield, contagem)
    )
    superficie_vol = ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(hoje, calendario, volatilidade, contagem)
    )
    processo = ql.BlackScholesMertonProcess(spot, curva_div, curva_taxa, superficie_vol)

    opcao = ql.VanillaOption(payoff, exercicio)
    return opcao, processo


def _preco(ql, passos, **kwargs) -> float:
    opcao, processo = _montar(ql, **kwargs)
    opcao.setPricingEngine(ql.BinomialVanillaEngine(processo, "crr", passos))
    return opcao.NPV()


def _prob_itm_no_vencimento(
    tipo: str, s: float, k: float, r: float, q: float, sigma: float, t: float
) -> float | None:
    """P(S_T > K) para call, P(S_T < K) para put, sob a medida risco-neutra.

    É N(d2) do Black-Scholes — analítico, sem árvore. Vale para americana
    também, mas medindo só o vencimento: quem chama emite a ressalva sobre
    exercício antecipado.
    """
    if t <= 0 or sigma <= 0 or s <= 0 or k <= 0:
        return None
    d2 = (math.log(s / k) + (r - q - 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
    # CDF normal padrão via erf — evita depender da QuantLib para uma conta
    # de uma linha, e mantém esta função testável isoladamente.
    n = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))  # noqa: E731
    return n(d2) if tipo.upper() == "CALL" else n(-d2)


def _percentil(valor: float, amostra: Sequence[float]) -> float:
    """Fração da amostra estritamente abaixo de `valor`."""
    return sum(1 for x in amostra if x < valor) / len(amostra)


def enriquecer(
    *,
    tipo: str,
    preco_objeto: float | None,
    strike: float | None,
    dias_vencimento: int | None,
    volatilidade_implicita: float | None,
    taxa: TaxaLivreRisco | None,
    ivs_historicas: Sequence[float] = (),
    ivs_da_cadeia: Sequence[float] = (),
    params: dict | None = None,
    agora: dt.datetime | None = None,
) -> Enriquecimento:
    """Contexto quantitativo de uma opção. Nunca levanta por dado faltante."""
    params = params if params is not None else carregar_modelo()
    agora = agora or dt.datetime.now(dt.timezone.utc)
    ressalvas: list[str] = []
    estilo = _estilo(tipo, params)

    def vazio(motivo: str) -> Enriquecimento:
        return Enriquecimento(
            modelo="indisponivel", estilo_exercicio=estilo, calculado_em=agora,
            ressalvas=(*ressalvas, motivo),
        )

    faltando = [
        nome for nome, valor in (
            ("preço do ativo-objeto", preco_objeto),
            ("strike", strike),
            ("dias até o vencimento", dias_vencimento),
            ("volatilidade implícita", volatilidade_implicita),
        ) if valor is None
    ]
    if faltando:
        return vazio(f"sem modelo: faltam {', '.join(faltando)}")
    if taxa is None:
        return vazio("sem modelo: taxa livre de risco indisponível")
    if dias_vencimento <= 0:
        return vazio(f"sem modelo: opção vencida ou vencendo hoje ({dias_vencimento}d)")
    if volatilidade_implicita <= 0 or preco_objeto <= 0 or strike <= 0:
        return vazio(
            "sem modelo: preço, strike e volatilidade precisam ser positivos "
            f"(veio preço={preco_objeto}, strike={strike}, "
            f"vol={volatilidade_implicita})"
        )

    dividend_yield = float(params.get("dividend_yield_padrao", 0.0))
    if dividend_yield == 0.0 and estilo == "americana" and tipo.upper() == "CALL":
        # O exercício antecipado de uma call americana sem dividendo nunca é
        # ótimo — com q=0 o modelo devolve exatamente o preço europeu. Dizer
        # isso evita que alguém leia "americana" e conclua que o prêmio de
        # exercício antecipado foi considerado quando ele é zero por
        # construção.
        ressalvas.append(
            "sem dividend yield coletado (q=0): o valor de exercício "
            "antecipado da call americana é nulo por construção, e o preço "
            "teórico coincide com o europeu"
        )

    ql = _quantlib()
    passos = int(params["passos_arvore"])
    hoje_ql = ql.Date(agora.day, agora.month, agora.year)
    vencimento_ql = hoje_ql + int(dias_vencimento)
    base = {
        "tipo": tipo, "estilo": estilo, "preco_objeto": float(preco_objeto),
        "strike": float(strike), "vencimento": vencimento_ql, "hoje": hoje_ql,
        "dividend_yield": dividend_yield,
    }
    sigma = float(volatilidade_implicita)
    r = float(taxa.valor_aa)

    opcao, processo = _montar(ql, volatilidade=sigma, taxa_aa=r, **base)
    opcao.setPricingEngine(ql.BinomialVanillaEngine(processo, "crr", passos))

    preco_teorico = opcao.NPV()
    delta, gamma, theta_ano = opcao.delta(), opcao.gamma(), opcao.theta()

    # A engine binomial não fornece vega nem rho — a QuantLib levanta
    # "vega not provided". Diferença finita CENTRAL: dois reapreçamentos por
    # grega, e o erro de truncamento cancela em primeira ordem.
    def bump(chave, delta_valor):
        alto = _preco(ql, passos, **{**base, "volatilidade": sigma, "taxa_aa": r,
                                     chave: (sigma if chave == "volatilidade" else r) + delta_valor})
        baixo = _preco(ql, passos, **{**base, "volatilidade": sigma, "taxa_aa": r,
                                      chave: (sigma if chave == "volatilidade" else r) - delta_valor})
        return (alto - baixo) / (2 * delta_valor)

    vega_unitario = bump("volatilidade", _BUMP_VOL)
    rho_unitario = bump("taxa_aa", _BUMP_TAXA)

    prob = _prob_itm_no_vencimento(
        tipo, float(preco_objeto), float(strike), r, dividend_yield,
        sigma, dias_vencimento / DIAS_NO_ANO,
    )
    if prob is not None and estilo == "americana":
        ressalvas.append(
            "prob_exercicio_vencimento mede apenas o VENCIMENTO; num "
            "contrato americano o exercício antecipado não está incluído"
        )

    # --- percentil de IV e skew: dependem de amostra, não do modelo ---
    minimo_percentil = int(params.get("minimo_amostras_iv_percentil", 20))
    iv_percentil = None
    if len(ivs_historicas) >= minimo_percentil:
        iv_percentil = _percentil(sigma, ivs_historicas)
    elif ivs_historicas:
        ressalvas.append(
            f"percentil de IV omitido: {len(ivs_historicas)} amostra(s) "
            f"históricas, mínimo {minimo_percentil}"
        )
    else:
        ressalvas.append("percentil de IV omitido: sem histórico de IV do ativo")

    minimo_cadeia = int(params.get("minimo_opcoes_cadeia_skew", 3))
    skew = None
    outras = [iv for iv in ivs_da_cadeia if iv is not None]
    if len(outras) >= minimo_cadeia:
        skew = sigma - (sum(outras) / len(outras))
    else:
        ressalvas.append(
            f"skew omitido: {len(outras)} opção(ões) na cadeia do mesmo "
            f"vencimento, mínimo {minimo_cadeia}"
        )

    return Enriquecimento(
        delta_modelo=delta,
        gamma=gamma,
        theta_dia=theta_ano / DIAS_NO_ANO,
        vega_pp=vega_unitario * 0.01,
        rho_pp=rho_unitario * 0.01,
        preco_teorico=preco_teorico,
        prob_exercicio_vencimento=prob,
        iv_percentil_252d=iv_percentil,
        skew_vs_cadeia=skew,
        modelo=f"CRR-binomial-{passos}",
        estilo_exercicio=estilo,
        taxa_livre_risco=r,
        taxa_observada_em=taxa.observada_em,
        volatilidade_usada=sigma,
        calculado_em=agora,
        ressalvas=tuple(ressalvas),
    )
