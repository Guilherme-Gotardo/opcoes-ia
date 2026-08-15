"""Traduz um evento de resultado em risco para o motor de opções.

Esta é a única superfície que a análise de opções deve enxergar. Ela não
sabe — e não pode saber — se o dado veio de CVM, yfinance, EODHD ou de
digitação manual. Recebe um veredito normalizado e responde às quatro
perguntas do serviço:

    Existe resultado próximo? A data é confirmada ou estimada?
    Qual a confiança? A operação atravessa o evento?

Os limiares moram em `skills/covered-options-strategy/params.yaml`, nunca
no código — mesma regra dos demais critérios de risco do projeto.
"""
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.earnings.models import EarningsEvent, RiskLevel, Session

PARAMS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "covered-options-strategy" / "params.yaml"
)

#: Defaults conservadores usados quando `params.yaml` não define o limiar.
#: Conservador aqui significa "classifica risco mais alto, não mais baixo".
DEFAULTS = {
    "earnings_risco_critical_dias": 1,
    "earnings_risco_high_dias": 3,
    "earnings_risco_medium_dias": 7,
    "earnings_risco_low_dias": 15,
    "earnings_confianca_minima": 60,
}


class ParametroInvalido(ValueError):
    """Limiar de risco malformado em `params.yaml`."""


@dataclass(frozen=True)
class EarningsRisk:
    """Risco de resultado para um ativo, na visão do motor de opções."""

    ticker: str
    earnings_date: dt.date | None
    days_to_earnings: int | None
    risk: RiskLevel
    confirmed: bool
    session: Session
    confidence: int
    #: `False` quando não há dado utilizável (sem evento, ou confiança
    #: abaixo do mínimo). O motor de opções DEVE tratar isso como
    #: "critério não verificável", nunca como "sem risco".
    reliable: bool
    reason: str

    def crosses_event(self, expiry: dt.date) -> bool | None:
        """A operação que vence em `expiry` atravessa o evento?

        Retorna `None` quando não há dado confiável — que é diferente de
        `False`. Confundir os dois é exatamente o erro que este serviço
        existe para impedir.
        """
        if not self.reliable or self.earnings_date is None:
            return None
        return self.earnings_date <= expiry


def carregar_params(path: Path | None = None) -> dict:
    """Carrega os limiares, preenchendo com os defaults conservadores.

    `path` existe para os testes exercitarem arquivos malformados sem
    precisar mexer no `params.yaml` do projeto.
    """
    path = path or PARAMS_PATH
    dados = {}
    if path.exists():
        dados = yaml.safe_load(path.read_text()) or {}

    params = dict(DEFAULTS)
    for chave, default in DEFAULTS.items():
        if chave not in dados:
            continue
        valor = dados[chave]
        if not isinstance(valor, int) or isinstance(valor, bool) or valor < 0:
            raise ParametroInvalido(
                f"{chave} precisa ser um inteiro não negativo em params.yaml "
                f"(recebido: {valor!r})."
            )
        params[chave] = valor

    ordem = [
        params["earnings_risco_critical_dias"],
        params["earnings_risco_high_dias"],
        params["earnings_risco_medium_dias"],
        params["earnings_risco_low_dias"],
    ]
    if ordem != sorted(ordem):
        raise ParametroInvalido(
            "os limiares de risco de earnings precisam ser crescentes "
            f"(critical <= high <= medium <= low); recebido: {ordem}."
        )
    return params


def _classificar(dias: int, params: dict) -> RiskLevel:
    if dias < 0:
        return RiskLevel.NONE
    if dias <= params["earnings_risco_critical_dias"]:
        return RiskLevel.CRITICAL
    if dias <= params["earnings_risco_high_dias"]:
        return RiskLevel.HIGH
    if dias <= params["earnings_risco_medium_dias"]:
        return RiskLevel.MEDIUM
    if dias <= params["earnings_risco_low_dias"]:
        return RiskLevel.LOW
    return RiskLevel.NONE


class EarningsRiskService:
    """Converte `EarningsEvent` em `EarningsRisk`."""

    def __init__(self, params: dict | None = None) -> None:
        self.params = params or carregar_params()

    def avaliar(
        self,
        ticker: str,
        evento: EarningsEvent | None,
        referencia: dt.date | None = None,
    ) -> EarningsRisk:
        referencia = referencia or dt.datetime.now(dt.timezone.utc).date()
        minima = self.params["earnings_confianca_minima"]

        if evento is None or evento.effective_date is None:
            return EarningsRisk(
                ticker=ticker, earnings_date=None, days_to_earnings=None,
                risk=RiskLevel.NONE, confirmed=False, session=Session.UNKNOWN,
                confidence=0, reliable=False,
                reason="nenhum evento de resultado registrado para o ativo",
            )

        if evento.confidence < minima:
            return EarningsRisk(
                ticker=ticker, earnings_date=evento.effective_date,
                days_to_earnings=(evento.effective_date - referencia).days,
                risk=RiskLevel.NONE, confirmed=evento.is_confirmed,
                session=evento.session, confidence=evento.confidence,
                reliable=False,
                reason=(
                    f"confiança {evento.confidence} abaixo do mínimo {minima} "
                    f"({evento.band.value}) — equivale a não ter data"
                ),
            )

        dias = (evento.effective_date - referencia).days

        # Sessão desconhecida torna a data ambígua em ±1 dia: uma divulgação
        # após o fechamento aparece como o dia seguinte em algumas fontes
        # (comprovado com VALE3 em 30/07/2026). Encurtamos a distância para
        # classificar pelo pior caso, nunca pelo melhor.
        dias_efetivos = dias - 1 if evento.session == Session.UNKNOWN else dias

        risco = _classificar(dias_efetivos, self.params)
        if evento.session == Session.UNKNOWN and risco != RiskLevel.NONE:
            motivo = (
                f"resultado em {evento.effective_date} ({dias} dia(s)); "
                "sessão desconhecida, janela ampliada em 1 dia"
            )
        else:
            motivo = f"resultado em {evento.effective_date} ({dias} dia(s))"

        return EarningsRisk(
            ticker=ticker,
            earnings_date=evento.effective_date,
            days_to_earnings=dias,
            risk=risco,
            confirmed=evento.is_confirmed,
            session=evento.session,
            confidence=evento.confidence,
            reliable=True,
            reason=motivo,
        )
