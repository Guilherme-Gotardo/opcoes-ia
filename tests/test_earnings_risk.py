"""Testes do EarningsRiskService — a superfície que o motor de opções usa."""
import datetime as dt

import pytest

from src.earnings.models import EarningsEvent, EarningsStatus, RiskLevel, Session
from src.earnings.risk import EarningsRiskService, ParametroInvalido, carregar_params

UTC = dt.timezone.utc
AGORA = dt.datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
HOJE = dt.date(2026, 8, 15)

PARAMS = {
    "earnings_risco_critical_dias": 1,
    "earnings_risco_high_dias": 3,
    "earnings_risco_medium_dias": 7,
    "earnings_risco_low_dias": 15,
    "earnings_confianca_minima": 60,
}


def evento(data, *, confidence=97, status=EarningsStatus.CONFIRMED,
           session=Session.AFTER_CLOSE) -> EarningsEvent:
    return EarningsEvent(
        ticker="VALE3", fiscal_period="2026Q3", status=status,
        confidence=confidence, confirmed_date=data, session=session,
        first_seen_at=AGORA, updated_at=AGORA,
    )


@pytest.fixture
def service():
    return EarningsRiskService(params=dict(PARAMS))


class TestSemDado:
    def test_evento_ausente_nao_e_confiavel(self, service):
        r = service.avaliar("VALE3", None, HOJE)
        assert r.reliable is False
        assert r.risk == RiskLevel.NONE
        assert "nenhum evento" in r.reason

    def test_risco_none_sem_dado_nao_significa_sem_risco(self, service):
        """`reliable=False` é o que o motor precisa olhar, não `risk`."""
        r = service.avaliar("VALE3", None, HOJE)
        assert r.risk == RiskLevel.NONE and r.reliable is False

    def test_confianca_abaixo_do_minimo_equivale_a_nao_ter_data(self, service):
        r = service.avaliar("VALE3", evento(dt.date(2026, 8, 17), confidence=45), HOJE)
        assert r.reliable is False
        assert "abaixo do mínimo" in r.reason


class TestClassificacao:
    @pytest.mark.parametrize("dias,esperado", [
        (0, RiskLevel.CRITICAL),
        (1, RiskLevel.CRITICAL),
        (2, RiskLevel.HIGH),
        (3, RiskLevel.HIGH),
        (5, RiskLevel.MEDIUM),
        (7, RiskLevel.MEDIUM),
        (10, RiskLevel.LOW),
        (15, RiskLevel.LOW),
        (30, RiskLevel.NONE),
    ])
    def test_faixas_com_sessao_conhecida(self, service, dias, esperado):
        e = evento(HOJE + dt.timedelta(days=dias), session=Session.AFTER_CLOSE)
        assert service.avaliar("VALE3", e, HOJE).risk == esperado

    def test_evento_passado_nao_gera_risco(self, service):
        e = evento(HOJE - dt.timedelta(days=5))
        r = service.avaliar("VALE3", e, HOJE)
        assert r.risk == RiskLevel.NONE
        assert r.days_to_earnings == -5


class TestSessaoDesconhecida:
    """Sessão UNKNOWN amplia a janela — lição do caso VALE3."""

    def test_unknown_classifica_pelo_pior_caso(self, service):
        conhecida = evento(HOJE + dt.timedelta(days=4), session=Session.AFTER_CLOSE)
        desconhecida = evento(HOJE + dt.timedelta(days=4), session=Session.UNKNOWN)
        assert service.avaliar("V", conhecida, HOJE).risk == RiskLevel.MEDIUM
        assert service.avaliar("V", desconhecida, HOJE).risk == RiskLevel.HIGH

    def test_motivo_explica_a_ampliacao(self, service):
        e = evento(HOJE + dt.timedelta(days=4), session=Session.UNKNOWN)
        assert "sessão desconhecida" in service.avaliar("V", e, HOJE).reason

    def test_days_to_earnings_reporta_a_distancia_real(self, service):
        """A ampliação afeta a classificação, não o número informado."""
        e = evento(HOJE + dt.timedelta(days=4), session=Session.UNKNOWN)
        assert service.avaliar("V", e, HOJE).days_to_earnings == 4


class TestCrossesEvent:
    def test_operacao_que_atravessa_o_evento(self, service):
        e = evento(HOJE + dt.timedelta(days=10))
        r = service.avaliar("VALE3", e, HOJE)
        assert r.crosses_event(HOJE + dt.timedelta(days=20)) is True

    def test_operacao_que_vence_antes_do_evento(self, service):
        e = evento(HOJE + dt.timedelta(days=30))
        r = service.avaliar("VALE3", e, HOJE)
        assert r.crosses_event(HOJE + dt.timedelta(days=20)) is False

    def test_sem_dado_confiavel_retorna_none_e_nao_false(self, service):
        """None != False: confundir os dois é o bug que o serviço evita."""
        r = service.avaliar("VALE3", None, HOJE)
        assert r.crosses_event(HOJE + dt.timedelta(days=20)) is None


class TestConfirmado:
    def test_estimado_marca_confirmed_false(self, service):
        e = evento(HOJE + dt.timedelta(days=10), status=EarningsStatus.ESTIMATED,
                   confidence=70)
        assert service.avaliar("VALE3", e, HOJE).confirmed is False

    def test_confirmado_marca_confirmed_true(self, service):
        e = evento(HOJE + dt.timedelta(days=10), status=EarningsStatus.CONFIRMED)
        assert service.avaliar("VALE3", e, HOJE).confirmed is True


class TestParametros:
    def _escrever(self, tmp_path, dados: dict):
        import yaml as _yaml
        p = tmp_path / "params.yaml"
        p.write_text(_yaml.safe_dump(dados))
        return p

    def test_limiares_fora_de_ordem_falham_alto(self, tmp_path):
        p = self._escrever(tmp_path, {**PARAMS, "earnings_risco_high_dias": 99})
        with pytest.raises(ParametroInvalido, match="crescentes"):
            carregar_params(p)

    def test_valor_nao_inteiro_falha_alto(self, tmp_path):
        p = self._escrever(tmp_path, {**PARAMS, "earnings_confianca_minima": "muito"})
        with pytest.raises(ParametroInvalido, match="inteiro"):
            carregar_params(p)

    def test_valor_negativo_falha_alto(self, tmp_path):
        p = self._escrever(tmp_path, {**PARAMS, "earnings_risco_low_dias": -1})
        with pytest.raises(ParametroInvalido, match="não negativo"):
            carregar_params(p)

    def test_arquivo_ausente_usa_defaults_conservadores(self, tmp_path):
        params = carregar_params(tmp_path / "nao-existe.yaml")
        assert params["earnings_confianca_minima"] == 60
        assert params["earnings_risco_critical_dias"] == 1

    def test_params_do_projeto_sao_validos(self):
        """O params.yaml real precisa carregar sem erro."""
        params = carregar_params()
        assert params["earnings_confianca_minima"] == 60
