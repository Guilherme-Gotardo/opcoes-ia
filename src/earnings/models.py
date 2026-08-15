"""Modelo de domínio do Earnings Event Service.

Este módulo é deliberadamente puro: sem I/O, sem banco, sem rede. Toda a
semântica de "o que é um evento de resultado e quanto ele merece confiança"
mora aqui, para poder ser testada sem infraestrutura — mesma separação já
usada em `src/strategy/covered.py`.

REGRA FUNDAMENTAL DESTE MÓDULO
------------------------------
Uma informação estimada NUNCA sobrescreve uma informação confirmada. Isso
não é convenção de código, é invariante estrutural: `AUTORIDADE` ordena os
status e `EarningsEvent.pode_ser_sobrescrito_por` é o único caminho de
atualização. Uma data errada é pior do que data nenhuma, porque "sem data"
bloqueia de forma conservadora enquanto uma data errada pode APROVAR uma
operação que deveria ser bloqueada por risco de resultado.
"""
import datetime as dt
from dataclasses import dataclass, field, replace
from enum import Enum


class EarningsStatus(str, Enum):
    """Estado de um evento de resultado.

    `ESTIMATED`  — alguém acha que vai ser nessa data. Ninguém confirmou.
    `CONFIRMED`  — a companhia (RI) ou evidência regulatória equivalente
                   confirmou a data.
    `RELEASED`   — o resultado já foi divulgado; a data é fato consumado.
    `RESCHEDULED`— havia uma data confirmada e ela mudou. Mantém autoridade
                   de confirmada, mas sinaliza que houve alteração.
    """

    ESTIMATED = "ESTIMATED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    RESCHEDULED = "RESCHEDULED"


#: Ordem de autoridade entre status. Um status só pode ser sobrescrito por
#: outro de autoridade MAIOR OU IGUAL. `RESCHEDULED` empata com `CONFIRMED`
#: de propósito: remarcar exige a mesma autoridade de confirmar.
AUTORIDADE: dict[EarningsStatus, int] = {
    EarningsStatus.ESTIMATED: 1,
    EarningsStatus.RESCHEDULED: 3,
    EarningsStatus.CONFIRMED: 3,
    EarningsStatus.RELEASED: 4,
}


class Session(str, Enum):
    """Momento do pregão em que o resultado sai.

    `UNKNOWN` não é ausência de informação a ser ignorada — é um estado que
    AMPLIA a janela de risco. Provado empiricamente na investigação de
    2026-08-15: a Vale divulgou em 30/07 após o fechamento e o Yahoo
    registrou `2026-07-31 00:00:00-04:00`. Sem a sessão, uma mesma
    divulgação aparece como dois dias diferentes.
    """

    BEFORE_OPEN = "BEFORE_OPEN"
    DURING_SESSION = "DURING_SESSION"
    AFTER_CLOSE = "AFTER_CLOSE"
    UNKNOWN = "UNKNOWN"


class ConfidenceBand(str, Enum):
    """Faixa qualitativa do score de confiança (0–100)."""

    CONFIRMED = "CONFIRMED"              # 95–100
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"  # 85–94
    ESTIMATED_HIGH = "ESTIMATED_HIGH"    # 60–84
    ESTIMATED_LOW = "ESTIMATED_LOW"      # 30–59
    UNKNOWN = "UNKNOWN"                  # 0–29


def faixa_de_confianca(score: int) -> ConfidenceBand:
    """Traduz o score numérico na faixa qualitativa correspondente."""
    if score >= 95:
        return ConfidenceBand.CONFIRMED
    if score >= 85:
        return ConfidenceBand.HIGH_CONFIDENCE
    if score >= 60:
        return ConfidenceBand.ESTIMATED_HIGH
    if score >= 30:
        return ConfidenceBand.ESTIMATED_LOW
    return ConfidenceBand.UNKNOWN


class RiskLevel(str, Enum):
    """Nível de risco de resultado para uma operação de opções."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ModeloInvalido(ValueError):
    """Levantado quando os dados de um evento/fonte não são utilizáveis.

    Falha alto em vez de normalizar silenciosamente: um evento malformado
    que vira `None` silencioso reaparece depois como "sem data", que o
    motor de opções interpreta como bloqueio — escondendo um bug de
    ingestão atrás de um comportamento que parece correto.
    """


@dataclass(frozen=True)
class EarningsEventSource:
    """O que UMA fonte afirmou, preservado exatamente como veio.

    Nunca é reescrita por consenso: quando duas fontes discordam, ambas as
    linhas permanecem. É o rastro de auditoria que permite responder "por
    que o sistema achava isso?" meses depois.
    """

    #: DESVIO DELIBERADO do modelo original: a especificação não previa
    #: `ticker` na fonte, só no evento. Mas um provider que responde em
    #: lote (`get_upcoming_earnings(tickers)`) devolve afirmações de vários
    #: ativos numa lista só, e sem o ticker não há como saber a qual evento
    #: cada uma pertence — a alternativa seria inferir pela data, que é
    #: exatamente o tipo de adivinhação que este serviço existe para
    #: eliminar.
    ticker: str
    provider: str
    retrieved_at: dt.datetime
    confidence: int
    date: dt.date | None = None
    time: dt.time | None = None
    status: EarningsStatus | None = None
    source_url: str | None = None
    fiscal_period: str | None = None
    session: Session | None = None

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ModeloInvalido("ticker é obrigatório em EarningsEventSource.")
        if not self.provider:
            raise ModeloInvalido("provider é obrigatório em EarningsEventSource.")
        if not 0 <= self.confidence <= 100:
            raise ModeloInvalido(
                f"confidence precisa estar entre 0 e 100 (recebido: {self.confidence})."
            )
        if self.retrieved_at.tzinfo is None:
            raise ModeloInvalido(
                "retrieved_at precisa ser timezone-aware (convenção do projeto: UTC)."
            )

    def idade_em_dias(self, agora: dt.datetime | None = None) -> float:
        """Há quantos dias esta informação foi coletada.

        Latência é dado: a CVM publica com ~7 dias de atraso e o yfinance
        fica cego logo após cada divulgação. Uma afirmação velha vale
        menos que uma nova.
        """
        agora = agora or dt.datetime.now(dt.timezone.utc)
        return (agora - self.retrieved_at).total_seconds() / 86400.0


@dataclass(frozen=True)
class EarningsEvent:
    """Um evento de resultado consolidado a partir de N fontes.

    `expected_*` e `confirmed_*` são campos separados de propósito: manter
    a estimativa depois de haver confirmação preserva a discordância em
    vez de apagá-la.
    """

    ticker: str
    fiscal_period: str
    status: EarningsStatus
    confidence: int
    first_seen_at: dt.datetime
    updated_at: dt.datetime
    company_name: str | None = None
    expected_date: dt.date | None = None
    confirmed_date: dt.date | None = None
    expected_time: dt.time | None = None
    confirmed_time: dt.time | None = None
    session: Session = Session.UNKNOWN
    sources: tuple[EarningsEventSource, ...] = field(default_factory=tuple)
    conflicts: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ModeloInvalido("ticker é obrigatório em EarningsEvent.")
        if not self.fiscal_period:
            raise ModeloInvalido(
                f"fiscal_period é obrigatório em EarningsEvent ({self.ticker}) — "
                "é ele que dá identidade ao evento."
            )
        if not 0 <= self.confidence <= 100:
            raise ModeloInvalido(
                f"confidence precisa estar entre 0 e 100 (recebido: {self.confidence})."
            )

    @property
    def id(self) -> str:
        """Identidade natural do evento: um resultado por trimestre fiscal."""
        return f"{self.ticker}:{self.fiscal_period}"

    @property
    def effective_date(self) -> dt.date | None:
        """A data que vale para decisão: a confirmada tem precedência."""
        return self.confirmed_date or self.expected_date

    @property
    def effective_time(self) -> dt.time | None:
        return self.confirmed_time or self.expected_time

    @property
    def is_confirmed(self) -> bool:
        """Só confirmado ou já divulgado conta como confirmado.

        `RESCHEDULED` NÃO entra: a data mudou e o novo valor merece uma
        confirmação própria antes de voltar a valer para decisão.
        """
        return self.status in (EarningsStatus.CONFIRMED, EarningsStatus.RELEASED)

    @property
    def band(self) -> ConfidenceBand:
        return faixa_de_confianca(self.confidence)

    @property
    def autoridade(self) -> int:
        return AUTORIDADE[self.status]

    def pode_ser_sobrescrito_por(self, novo_status: EarningsStatus) -> bool:
        """Único portão de atualização de status.

        Implementa a regra fundamental: `ESTIMATED` nunca derruba
        `CONFIRMED` nem `RELEASED`, independentemente de qual fonte chegou
        por último ou de quantas fontes concordam com a estimativa.
        """
        return AUTORIDADE[novo_status] >= self.autoridade

    def com_fonte(self, source: EarningsEventSource) -> "EarningsEvent":
        """Retorna uma cópia com mais uma fonte anexada (nunca muta)."""
        return replace(self, sources=self.sources + (source,))


def fiscal_period_from_release_date(data_divulgacao: dt.date) -> str:
    """Deriva o trimestre fiscal a partir da data de DIVULGAÇÃO.

    Regra: o trimestre reportado é o último que se encerrou ESTRITAMENTE
    antes da divulgação. Resultado do 2T sai em julho/agosto, então uma
    divulgação em 06/08/2026 reporta o trimestre encerrado em 30/06/2026
    → `2026Q2`.

    Isto é aritmética de calendário, não estimativa de valor de mercado —
    é determinístico e auditável. Só é usado quando a fonte não informa o
    período; a CVM informa (`Data_Referencia`) e nesse caso o valor real
    prevalece.

    Validado contra as divulgações reais de 2026-08-15:
    PETR4 06/08 → 2026Q2, ITUB4 04/08 → 2026Q2, ABEV3 30/07 → 2026Q2.
    """
    ano = data_divulgacao.year
    fim_de_trimestre = [
        (dt.date(ano - 1, 12, 31), f"{ano - 1}Q4"),
        (dt.date(ano, 3, 31), f"{ano}Q1"),
        (dt.date(ano, 6, 30), f"{ano}Q2"),
        (dt.date(ano, 9, 30), f"{ano}Q3"),
        (dt.date(ano, 12, 31), f"{ano}Q4"),
    ]
    anteriores = [rotulo for fim, rotulo in fim_de_trimestre if fim < data_divulgacao]
    if not anteriores:
        raise ModeloInvalido(
            f"não foi possível derivar o trimestre fiscal de {data_divulgacao}."
        )
    return anteriores[-1]
