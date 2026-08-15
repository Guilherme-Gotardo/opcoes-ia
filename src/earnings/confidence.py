"""Score de confiança (0–100) de um evento de resultado.

As faixas seguem a especificação do serviço:

    95–100  CONFIRMED        confirmação oficial (RI) ou evidência regulatória
    85–94   HIGH_CONFIDENCE  duas fontes independentes concordam
    60–84   ESTIMATED_HIGH   uma fonte confiável, sem confirmação oficial
    30–59   ESTIMATED_LOW    apenas uma fonte secundária
    0–29    UNKNOWN          conflito, dado velho ou insuficiente

Por que o tier do provedor importa mais que a quantidade de fontes: a
investigação de 2026-08-15 mostrou que nenhuma API comercial distingue data
confirmada de estimada — todas derivam da ausência do EPS realizado, que é
a mesma heurística que o yfinance entrega de graça. Concordância entre duas
fontes que copiam o mesmo consenso não é confirmação independente, é o
mesmo palpite contado duas vezes. Por isso `CONFIRMED` exige autoridade, não
volume.
"""
import datetime as dt
from enum import IntEnum

from src.earnings.models import EarningsEventSource, EarningsStatus


class ProviderTier(IntEnum):
    """Autoridade de um provedor. Menor é mais confiável."""

    OFICIAL = 1      # RI da companhia, ou entrada manual conferida por humano
    REGULATORIA = 2  # CVM — evidência de que o documento foi entregue
    COMERCIAL = 3    # EODHD, Twelve Data, FMP, Dados de Mercado
    SECUNDARIA = 4   # yfinance e afins: sem contrato, sem garantia


#: Registro de tiers. Provedor desconhecido cai em SECUNDARIA de propósito:
#: o default precisa ser o mais conservador, para que adicionar um provider
#: novo sem registrá-lo aqui nunca infle a confiança por descuido.
PROVIDER_TIERS: dict[str, ProviderTier] = {
    "manual": ProviderTier.OFICIAL,
    "ri": ProviderTier.OFICIAL,
    "cvm": ProviderTier.REGULATORIA,
    "eodhd": ProviderTier.COMERCIAL,
    "twelvedata": ProviderTier.COMERCIAL,
    "fmp": ProviderTier.COMERCIAL,
    "dadosdemercado": ProviderTier.COMERCIAL,
    "yfinance": ProviderTier.SECUNDARIA,
}

TIER_PADRAO = ProviderTier.SECUNDARIA

#: Score-base por tier quando a fonte NÃO carrega confirmação.
SCORE_BASE_ESTIMATIVA: dict[ProviderTier, int] = {
    ProviderTier.OFICIAL: 80,
    ProviderTier.REGULATORIA: 75,
    ProviderTier.COMERCIAL: 65,
    ProviderTier.SECUNDARIA: 45,
}

SCORE_CONFIRMADO = 97
SCORE_DIVULGADO = 100
SCORE_MAXIMO_SEM_AUTORIDADE = 94  # teto de quem não é OFICIAL/REGULATORIA
BONUS_SEGUNDA_FONTE_CONCORDANTE = 20
SCORE_CONFLITO_SEM_AUTORIDADE = 25

#: A partir de quantos dias uma coleta começa a perder valor, e quanto
#: perde por dia. Calibrado nos dois atrasos reais medidos: a CVM publica
#: com ~7 dias de defasagem e o yfinance fica cego logo após a divulgação.
DIAS_ANTES_DE_ENVELHECER = 7
PENALIDADE_POR_DIA_VELHO = 2
PENALIDADE_MAXIMA_POR_IDADE = 30


def tier_do_provider(provider: str) -> ProviderTier:
    return PROVIDER_TIERS.get(provider.strip().lower(), TIER_PADRAO)


def tem_autoridade_para_confirmar(provider: str) -> bool:
    """Só fonte oficial ou regulatória pode elevar um evento a CONFIRMED."""
    return tier_do_provider(provider) <= ProviderTier.REGULATORIA


def penalidade_por_idade(source: EarningsEventSource, agora: dt.datetime | None = None) -> int:
    """Quanto o score cai porque a informação é velha."""
    idade = source.idade_em_dias(agora)
    if idade <= DIAS_ANTES_DE_ENVELHECER:
        return 0
    excedente = idade - DIAS_ANTES_DE_ENVELHECER
    return int(min(PENALIDADE_MAXIMA_POR_IDADE, excedente * PENALIDADE_POR_DIA_VELHO))


def score_da_fonte(source: EarningsEventSource, agora: dt.datetime | None = None) -> int:
    """Confiança que UMA fonte merece isoladamente.

    Uma fonte sem autoridade que se declara `CONFIRMED` não é promovida:
    ela é tratada como estimativa e fica limitada ao teto de estimativa do
    seu tier. Declarar-se confirmada não confere autoridade.
    """
    provider_tier = tier_do_provider(source.provider)

    if source.status == EarningsStatus.RELEASED:
        # Divulgação já ocorrida é fato observável, não previsão — mesmo
        # vindo de fonte secundária, o evento aconteceu.
        bruto = SCORE_DIVULGADO if provider_tier <= ProviderTier.REGULATORIA else 90
    elif source.status == EarningsStatus.CONFIRMED and tem_autoridade_para_confirmar(source.provider):
        bruto = SCORE_CONFIRMADO
    else:
        bruto = SCORE_BASE_ESTIMATIVA[provider_tier]

    return max(0, min(100, bruto - penalidade_por_idade(source, agora)))


def _sem_autoridade(sources: list[EarningsEventSource]) -> bool:
    return not any(tem_autoridade_para_confirmar(s.provider) for s in sources)


def score_consolidado(
    sources: list[EarningsEventSource],
    data_vencedora: dt.date | None,
    houve_conflito: bool,
    agora: dt.datetime | None = None,
) -> int:
    """Confiança do evento consolidado, dadas todas as fontes conhecidas.

    `data_vencedora` é a data que a resolução de conflitos elegeu; apenas
    as fontes que concordam com ela contribuem para o score. As demais
    permanecem registradas no evento como rastro, mas não sustentam a
    confiança de uma data que elas não afirmam.
    """
    if not sources or data_vencedora is None:
        return 0

    concordantes = [s for s in sources if s.date == data_vencedora]
    if not concordantes:
        return 0

    melhor = max(score_da_fonte(s, agora) for s in concordantes)

    # Concordância só vale como reforço entre provedores DISTINTOS: o mesmo
    # provider consultado duas vezes não é uma segunda opinião.
    provedores_distintos = {s.provider.strip().lower() for s in concordantes}
    if len(provedores_distintos) >= 2:
        melhor += BONUS_SEGUNDA_FONTE_CONCORDANTE

    if _sem_autoridade(concordantes):
        # Sem fonte oficial/regulatória o evento não alcança a faixa
        # CONFIRMED, por mais provedores comerciais que concordem.
        melhor = min(melhor, SCORE_MAXIMO_SEM_AUTORIDADE)
        if houve_conflito:
            melhor = min(melhor, SCORE_CONFLITO_SEM_AUTORIDADE)

    return max(0, min(100, melhor))
