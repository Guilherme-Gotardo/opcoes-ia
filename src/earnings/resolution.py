"""Resolução de conflitos entre fontes de um mesmo evento de resultado.

Regras, na ordem em que são aplicadas:

1. Nunca escolher silenciosamente a primeira resposta.
2. Registrar TODAS as fontes, inclusive as perdedoras.
3. Priorizar fonte oficial/regulatória sobre comercial/secundária.
4. Havendo confirmação com autoridade, ela vence.
5. Não havendo, escolher por peso e marcar o evento como `ESTIMATED`.
6. Registrar o conflito em texto legível, para observabilidade.

E a invariante que atravessa tudo: uma informação `ESTIMATED` nunca
substitui uma `CONFIRMED` ou `RELEASED` já estabelecida.
"""
import datetime as dt
from dataclasses import dataclass

from src.earnings.confidence import (
    score_da_fonte,
    score_consolidado,
    tem_autoridade_para_confirmar,
    tier_do_provider,
)
from src.earnings.models import (
    EarningsEvent,
    EarningsEventSource,
    EarningsStatus,
    ModeloInvalido,
    Session,
)


@dataclass(frozen=True)
class ResolucaoEvento:
    """Resultado de consolidar N fontes num único veredito."""

    date: dt.date | None
    time: dt.time | None
    session: Session
    status: EarningsStatus
    confidence: int
    conflicts: tuple[str, ...]

    @property
    def houve_conflito(self) -> bool:
        return bool(self.conflicts)


def _descreve_conflito(por_data: dict[dt.date, list[EarningsEventSource]]) -> str:
    partes = []
    for data in sorted(por_data):
        provedores = ", ".join(sorted({s.provider for s in por_data[data]}))
        partes.append(f"{data.isoformat()} ({provedores})")
    return "datas divergentes entre fontes: " + " vs ".join(partes)


def _peso_da_data(sources: list[EarningsEventSource], agora: dt.datetime | None) -> tuple:
    """Chave de desempate quando nenhuma fonte tem autoridade.

    Ordem: melhor tier disponível, depois número de provedores distintos,
    depois coleta mais recente. Deliberadamente NÃO usa "quem chegou
    primeiro".
    """
    melhor_tier = min(tier_do_provider(s.provider) for s in sources)
    provedores_distintos = len({s.provider.strip().lower() for s in sources})
    coleta_mais_recente = max(s.retrieved_at for s in sources)
    return (-melhor_tier, provedores_distintos, coleta_mais_recente)


def _resolver_sessao(vencedoras: list[EarningsEventSource]) -> Session:
    """Sessão vinda da fonte de maior autoridade que a informe.

    Ausência vira `UNKNOWN`, nunca um chute. `UNKNOWN` amplia a janela de
    risco em `EarningsRiskService` — foi o que o caso VALE3 (divulgação
    após o fechamento aparecendo como o dia seguinte) mostrou ser
    necessário.
    """
    com_sessao = [
        s for s in vencedoras
        if s.session is not None and s.session != Session.UNKNOWN
    ]
    if not com_sessao:
        return Session.UNKNOWN
    com_sessao.sort(key=lambda s: tier_do_provider(s.provider))
    return com_sessao[0].session


def resolver(
    sources: list[EarningsEventSource],
    agora: dt.datetime | None = None,
) -> ResolucaoEvento:
    """Consolida várias afirmações sobre o mesmo evento num veredito."""
    com_data = [s for s in sources if s.date is not None]
    if not com_data:
        return ResolucaoEvento(
            date=None, time=None, session=Session.UNKNOWN,
            status=EarningsStatus.ESTIMATED, confidence=0,
            conflicts=("nenhuma fonte informou data",),
        )

    por_data: dict[dt.date, list[EarningsEventSource]] = {}
    for s in com_data:
        por_data.setdefault(s.date, []).append(s)

    conflicts: list[str] = []
    if len(por_data) > 1:
        conflicts.append(_descreve_conflito(por_data))

    # (4) Autoridade vence: divulgado primeiro, depois confirmado.
    divulgadas = [
        s for s in com_data
        if s.status == EarningsStatus.RELEASED and tem_autoridade_para_confirmar(s.provider)
    ]
    confirmadas = [
        s for s in com_data
        if s.status == EarningsStatus.CONFIRMED and tem_autoridade_para_confirmar(s.provider)
    ]

    if divulgadas:
        vencedora = max(divulgadas, key=lambda s: (score_da_fonte(s, agora), s.retrieved_at))
        status = EarningsStatus.RELEASED
    elif confirmadas:
        vencedora = max(confirmadas, key=lambda s: (score_da_fonte(s, agora), s.retrieved_at))
        status = EarningsStatus.CONFIRMED
    else:
        # (5) Sem autoridade: escolhe por peso, mas o evento continua estimado.
        melhor_data = max(por_data, key=lambda d: _peso_da_data(por_data[d], agora))
        vencedora = max(por_data[melhor_data], key=lambda s: score_da_fonte(s, agora))
        status = EarningsStatus.ESTIMATED

    data_vencedora = vencedora.date
    vencedoras = por_data[data_vencedora]

    if len(por_data) > 1:
        perdedoras = sorted(d for d in por_data if d != data_vencedora)
        conflicts.append(
            f"data adotada {data_vencedora.isoformat()} "
            f"({vencedora.provider}, {status.value}); "
            f"descartada(s): {', '.join(d.isoformat() for d in perdedoras)}"
        )

    confidence = score_consolidado(
        com_data, data_vencedora, houve_conflito=len(por_data) > 1, agora=agora
    )

    tempos = [s.time for s in vencedoras if s.time is not None]

    return ResolucaoEvento(
        date=data_vencedora,
        time=tempos[0] if tempos else None,
        session=_resolver_sessao(vencedoras),
        status=status,
        confidence=confidence,
        conflicts=tuple(conflicts),
    )


def aplicar(
    existente: EarningsEvent | None,
    ticker: str,
    fiscal_period: str,
    resolucao: ResolucaoEvento,
    sources: list[EarningsEventSource],
    company_name: str | None = None,
    agora: dt.datetime | None = None,
) -> EarningsEvent:
    """Constrói ou atualiza o evento, respeitando a regra fundamental.

    Se `existente` já é `CONFIRMED`/`RELEASED` e a nova resolução é apenas
    `ESTIMATED`, a data confirmada é PRESERVADA — a estimativa entra só
    como fonte e como conflito registrado. É aqui que "uma data errada é
    pior que data nenhuma" vira código.
    """
    agora = agora or dt.datetime.now(dt.timezone.utc)

    if existente is None:
        confirmada = resolucao.status in (EarningsStatus.CONFIRMED, EarningsStatus.RELEASED)
        return EarningsEvent(
            ticker=ticker,
            fiscal_period=fiscal_period,
            company_name=company_name,
            status=resolucao.status,
            confidence=resolucao.confidence,
            expected_date=None if confirmada else resolucao.date,
            confirmed_date=resolucao.date if confirmada else None,
            expected_time=None if confirmada else resolucao.time,
            confirmed_time=resolucao.time if confirmada else None,
            session=resolucao.session,
            sources=tuple(sources),
            conflicts=resolucao.conflicts,
            first_seen_at=agora,
            updated_at=agora,
        )

    todas_as_fontes = tuple(existente.sources) + tuple(sources)

    if not existente.pode_ser_sobrescrito_por(resolucao.status):
        # Rebaixamento barrado. A informação divergente NÃO é perdida:
        # vira fonte registrada e conflito explícito.
        aviso = (
            f"{resolucao.status.value} de {resolucao.date} ignorado: "
            f"evento já está {existente.status.value} em "
            f"{existente.effective_date}"
        )
        return EarningsEvent(
            ticker=existente.ticker,
            fiscal_period=existente.fiscal_period,
            company_name=existente.company_name or company_name,
            status=existente.status,
            confidence=existente.confidence,
            expected_date=resolucao.date if resolucao.date != existente.confirmed_date else existente.expected_date,
            confirmed_date=existente.confirmed_date,
            expected_time=existente.expected_time,
            confirmed_time=existente.confirmed_time,
            session=existente.session,
            sources=todas_as_fontes,
            conflicts=existente.conflicts + (aviso,),
            first_seen_at=existente.first_seen_at,
            updated_at=agora,
        )

    # Autoridade suficiente para atualizar. Remarcação é detectada quando
    # uma data confirmada já existia e mudou.
    novo_status = resolucao.status
    conflitos = existente.conflicts + resolucao.conflicts
    if (
        existente.confirmed_date is not None
        and resolucao.date is not None
        and resolucao.date != existente.confirmed_date
        and resolucao.status == EarningsStatus.CONFIRMED
    ):
        novo_status = EarningsStatus.RESCHEDULED
        conflitos = conflitos + (
            f"remarcado: {existente.confirmed_date.isoformat()} → "
            f"{resolucao.date.isoformat()}",
        )

    confirmada = novo_status in (
        EarningsStatus.CONFIRMED, EarningsStatus.RELEASED, EarningsStatus.RESCHEDULED
    )
    return EarningsEvent(
        ticker=existente.ticker,
        fiscal_period=existente.fiscal_period,
        company_name=company_name or existente.company_name,
        status=novo_status,
        confidence=resolucao.confidence,
        expected_date=existente.expected_date if confirmada else resolucao.date,
        confirmed_date=resolucao.date if confirmada else existente.confirmed_date,
        expected_time=existente.expected_time if confirmada else resolucao.time,
        confirmed_time=resolucao.time if confirmada else existente.confirmed_time,
        session=resolucao.session if resolucao.session != Session.UNKNOWN else existente.session,
        sources=todas_as_fontes,
        conflicts=conflitos,
        first_seen_at=existente.first_seen_at,
        updated_at=agora,
    )
