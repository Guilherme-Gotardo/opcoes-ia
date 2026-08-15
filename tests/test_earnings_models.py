"""Testes do modelo de domínio de earnings — puros, sem banco."""
import datetime as dt

import pytest

from src.earnings.models import (
    AUTORIDADE,
    ConfidenceBand,
    EarningsEvent,
    EarningsEventSource,
    EarningsStatus,
    ModeloInvalido,
    Session,
    faixa_de_confianca,
    fiscal_period_from_release_date,
)

UTC = dt.timezone.utc
AGORA = dt.datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def fonte(**kwargs) -> EarningsEventSource:
    base = dict(
        ticker="PETR4", provider="yfinance", retrieved_at=AGORA, confidence=45,
    )
    base.update(kwargs)
    return EarningsEventSource(**base)


def evento(**kwargs) -> EarningsEvent:
    base = dict(
        ticker="PETR4", fiscal_period="2026Q3",
        status=EarningsStatus.ESTIMATED, confidence=45,
        first_seen_at=AGORA, updated_at=AGORA,
    )
    base.update(kwargs)
    return EarningsEvent(**base)


class TestValidacao:
    def test_source_exige_ticker(self):
        with pytest.raises(ModeloInvalido, match="ticker"):
            fonte(ticker="")

    def test_source_exige_retrieved_at_com_timezone(self):
        with pytest.raises(ModeloInvalido, match="timezone-aware"):
            fonte(retrieved_at=dt.datetime(2026, 8, 15, 12, 0))

    def test_source_rejeita_confianca_fora_da_faixa(self):
        with pytest.raises(ModeloInvalido, match="entre 0 e 100"):
            fonte(confidence=101)

    def test_evento_exige_fiscal_period(self):
        with pytest.raises(ModeloInvalido, match="fiscal_period"):
            evento(fiscal_period="")


class TestIdentidade:
    def test_id_e_ticker_mais_periodo(self):
        assert evento().id == "PETR4:2026Q3"


class TestDataEfetiva:
    def test_confirmada_tem_precedencia_sobre_estimada(self):
        e = evento(
            expected_date=dt.date(2026, 11, 4),
            confirmed_date=dt.date(2026, 11, 6),
        )
        assert e.effective_date == dt.date(2026, 11, 6)

    def test_usa_estimada_quando_nao_ha_confirmada(self):
        e = evento(expected_date=dt.date(2026, 11, 4))
        assert e.effective_date == dt.date(2026, 11, 4)

    def test_sem_nenhuma_data_efetiva_e_none(self):
        assert evento().effective_date is None


class TestAutoridade:
    """A regra fundamental: estimativa nunca derruba confirmação."""

    def test_estimativa_nao_sobrescreve_confirmado(self):
        e = evento(status=EarningsStatus.CONFIRMED)
        assert e.pode_ser_sobrescrito_por(EarningsStatus.ESTIMATED) is False

    def test_estimativa_nao_sobrescreve_divulgado(self):
        e = evento(status=EarningsStatus.RELEASED)
        assert e.pode_ser_sobrescrito_por(EarningsStatus.ESTIMATED) is False

    def test_confirmado_nao_sobrescreve_divulgado(self):
        e = evento(status=EarningsStatus.RELEASED)
        assert e.pode_ser_sobrescrito_por(EarningsStatus.CONFIRMED) is False

    def test_confirmado_sobrescreve_estimativa(self):
        e = evento(status=EarningsStatus.ESTIMATED)
        assert e.pode_ser_sobrescrito_por(EarningsStatus.CONFIRMED) is True

    def test_divulgado_sobrescreve_confirmado(self):
        e = evento(status=EarningsStatus.CONFIRMED)
        assert e.pode_ser_sobrescrito_por(EarningsStatus.RELEASED) is True

    def test_remarcacao_tem_mesma_autoridade_que_confirmacao(self):
        assert AUTORIDADE[EarningsStatus.RESCHEDULED] == AUTORIDADE[EarningsStatus.CONFIRMED]


class TestIsConfirmed:
    def test_remarcado_nao_conta_como_confirmado(self):
        """A data mudou; o novo valor precisa de confirmação própria."""
        assert evento(status=EarningsStatus.RESCHEDULED).is_confirmed is False

    def test_confirmado_e_divulgado_contam(self):
        assert evento(status=EarningsStatus.CONFIRMED).is_confirmed is True
        assert evento(status=EarningsStatus.RELEASED).is_confirmed is True


class TestFaixasDeConfianca:
    @pytest.mark.parametrize("score,esperado", [
        (100, ConfidenceBand.CONFIRMED),
        (95, ConfidenceBand.CONFIRMED),
        (94, ConfidenceBand.HIGH_CONFIDENCE),
        (85, ConfidenceBand.HIGH_CONFIDENCE),
        (84, ConfidenceBand.ESTIMATED_HIGH),
        (60, ConfidenceBand.ESTIMATED_HIGH),
        (59, ConfidenceBand.ESTIMATED_LOW),
        (30, ConfidenceBand.ESTIMATED_LOW),
        (29, ConfidenceBand.UNKNOWN),
        (0, ConfidenceBand.UNKNOWN),
    ])
    def test_fronteiras_das_faixas(self, score, esperado):
        assert faixa_de_confianca(score) == esperado


class TestPeriodoFiscal:
    """Validado contra as divulgações reais medidas em 2026-08-15."""

    @pytest.mark.parametrize("divulgacao,esperado", [
        (dt.date(2026, 8, 6), "2026Q2"),    # PETR4 real
        (dt.date(2026, 8, 4), "2026Q2"),    # ITUB4 real
        (dt.date(2026, 7, 30), "2026Q2"),   # ABEV3 e VALE3 reais
        (dt.date(2026, 11, 6), "2026Q3"),
        (dt.date(2026, 3, 5), "2025Q4"),    # resultado anual sai em março
        (dt.date(2026, 5, 11), "2026Q1"),
    ])
    def test_deriva_trimestre_da_data_de_divulgacao(self, divulgacao, esperado):
        assert fiscal_period_from_release_date(divulgacao) == esperado

    def test_divulgacao_no_proprio_fim_do_trimestre_pega_o_anterior(self):
        """30/06 não divulga o 2T — o trimestre ainda não fechou."""
        assert fiscal_period_from_release_date(dt.date(2026, 6, 30)) == "2026Q1"


class TestIdade:
    def test_idade_em_dias(self):
        f = fonte(retrieved_at=AGORA - dt.timedelta(days=10))
        assert f.idade_em_dias(AGORA) == pytest.approx(10.0)


class TestImutabilidade:
    def test_com_fonte_nao_muta_o_original(self):
        original = evento()
        novo = original.com_fonte(fonte())
        assert original.sources == ()
        assert len(novo.sources) == 1
