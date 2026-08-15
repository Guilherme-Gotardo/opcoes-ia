"""Testes de score de confiança e resolução de conflitos.

Os cenários vêm da investigação real de 2026-08-15 — em especial o caso
VALE3, em que o yfinance e a CVM discordam em um dia porque a divulgação
saiu após o fechamento.
"""
import datetime as dt

import pytest

from src.earnings.confidence import (
    ProviderTier,
    score_da_fonte,
    tem_autoridade_para_confirmar,
    tier_do_provider,
)
from src.earnings.models import (
    EarningsEventSource,
    EarningsStatus,
    Session,
)
from src.earnings.resolution import aplicar, resolver

UTC = dt.timezone.utc
AGORA = dt.datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def src(provider, date=None, status=None, ticker="VALE3", **kw) -> EarningsEventSource:
    return EarningsEventSource(
        ticker=ticker,
        provider=provider,
        retrieved_at=kw.pop("retrieved_at", AGORA),
        confidence=kw.pop("confidence", 50),
        date=date,
        status=status,
        **kw,
    )


class TestTiers:
    def test_manual_e_ri_sao_oficiais(self):
        assert tier_do_provider("manual") == ProviderTier.OFICIAL
        assert tier_do_provider("ri") == ProviderTier.OFICIAL

    def test_cvm_e_regulatoria(self):
        assert tier_do_provider("cvm") == ProviderTier.REGULATORIA

    def test_yfinance_e_secundaria(self):
        assert tier_do_provider("yfinance") == ProviderTier.SECUNDARIA

    def test_provider_desconhecido_cai_no_tier_mais_conservador(self):
        assert tier_do_provider("provedor-novo-qualquer") == ProviderTier.SECUNDARIA

    def test_so_oficial_e_regulatoria_confirmam(self):
        assert tem_autoridade_para_confirmar("manual") is True
        assert tem_autoridade_para_confirmar("cvm") is True
        assert tem_autoridade_para_confirmar("eodhd") is False
        assert tem_autoridade_para_confirmar("yfinance") is False


class TestScoreDaFonte:
    def test_confirmacao_manual_pontua_na_faixa_confirmed(self):
        s = src("manual", dt.date(2026, 11, 6), EarningsStatus.CONFIRMED)
        assert score_da_fonte(s, AGORA) >= 95

    def test_fonte_secundaria_que_se_diz_confirmada_nao_e_promovida(self):
        """Declarar-se confirmada não confere autoridade."""
        s = src("yfinance", dt.date(2026, 11, 6), EarningsStatus.CONFIRMED)
        assert score_da_fonte(s, AGORA) < 95

    def test_divulgacao_pela_cvm_e_fato(self):
        s = src("cvm", dt.date(2026, 7, 30), EarningsStatus.RELEASED)
        assert score_da_fonte(s, AGORA) == 100

    def test_dado_velho_perde_pontos(self):
        recente = src("yfinance", dt.date(2026, 11, 6), EarningsStatus.ESTIMATED)
        velho = src(
            "yfinance", dt.date(2026, 11, 6), EarningsStatus.ESTIMATED,
            retrieved_at=AGORA - dt.timedelta(days=30),
        )
        assert score_da_fonte(velho, AGORA) < score_da_fonte(recente, AGORA)


class TestResolucaoSemConflito:
    def test_fonte_unica_estimada(self):
        r = resolver([src("yfinance", dt.date(2026, 10, 29), EarningsStatus.ESTIMATED)], AGORA)
        assert r.status == EarningsStatus.ESTIMATED
        assert r.date == dt.date(2026, 10, 29)
        assert not r.houve_conflito

    def test_sem_data_nenhuma(self):
        r = resolver([src("yfinance", None)], AGORA)
        assert r.date is None
        assert r.confidence == 0
        assert r.conflicts

    def test_lista_vazia(self):
        r = resolver([], AGORA)
        assert r.date is None
        assert r.confidence == 0


class TestResolucaoComConflito:
    """O caso VALE3 real: yfinance diz 31/07, CVM diz 30/07."""

    def test_cvm_vence_o_yahoo_e_registra_o_conflito(self):
        fontes = [
            src("yfinance", dt.date(2026, 7, 31), EarningsStatus.ESTIMATED),
            src("cvm", dt.date(2026, 7, 30), EarningsStatus.RELEASED),
        ]
        r = resolver(fontes, AGORA)
        assert r.date == dt.date(2026, 7, 30)
        assert r.status == EarningsStatus.RELEASED
        assert r.houve_conflito
        assert any("2026-07-31" in c for c in r.conflicts)

    def test_ordem_das_fontes_nao_muda_o_resultado(self):
        a = [
            src("yfinance", dt.date(2026, 7, 31), EarningsStatus.ESTIMATED),
            src("cvm", dt.date(2026, 7, 30), EarningsStatus.RELEASED),
        ]
        b = list(reversed(a))
        assert resolver(a, AGORA).date == resolver(b, AGORA).date

    def test_duas_secundarias_em_conflito_derrubam_a_confianca(self):
        fontes = [
            src("yfinance", dt.date(2026, 8, 20), EarningsStatus.ESTIMATED),
            src("fmp", dt.date(2026, 8, 21), EarningsStatus.ESTIMATED),
        ]
        r = resolver(fontes, AGORA)
        assert r.status == EarningsStatus.ESTIMATED
        assert r.confidence <= 30
        assert r.houve_conflito

    def test_duas_fontes_concordantes_sobem_a_confianca(self):
        fontes = [
            src("yfinance", dt.date(2026, 8, 20), EarningsStatus.ESTIMATED),
            src("eodhd", dt.date(2026, 8, 20), EarningsStatus.ESTIMATED),
        ]
        r = resolver(fontes, AGORA)
        assert not r.houve_conflito
        assert r.confidence >= 85

    def test_concordancia_sem_autoridade_nao_alcanca_faixa_confirmed(self):
        fontes = [
            src("yfinance", dt.date(2026, 8, 20), EarningsStatus.ESTIMATED),
            src("eodhd", dt.date(2026, 8, 20), EarningsStatus.ESTIMATED),
            src("fmp", dt.date(2026, 8, 20), EarningsStatus.ESTIMATED),
        ]
        assert resolver(fontes, AGORA).confidence < 95

    def test_mesmo_provider_duas_vezes_nao_e_segunda_opiniao(self):
        fontes = [
            src("yfinance", dt.date(2026, 8, 20), EarningsStatus.ESTIMATED),
            src("yfinance", dt.date(2026, 8, 20), EarningsStatus.ESTIMATED,
                retrieved_at=AGORA - dt.timedelta(hours=1)),
        ]
        uma_so = resolver([fontes[0]], AGORA)
        assert resolver(fontes, AGORA).confidence == uma_so.confidence


class TestSessao:
    def test_sessao_vem_da_fonte_de_maior_autoridade(self):
        fontes = [
            src("yfinance", dt.date(2026, 7, 30), EarningsStatus.ESTIMATED,
                session=Session.BEFORE_OPEN),
            src("manual", dt.date(2026, 7, 30), EarningsStatus.CONFIRMED,
                session=Session.AFTER_CLOSE),
        ]
        assert resolver(fontes, AGORA).session == Session.AFTER_CLOSE

    def test_ausencia_de_sessao_vira_unknown_e_nao_chute(self):
        r = resolver([src("yfinance", dt.date(2026, 7, 30))], AGORA)
        assert r.session == Session.UNKNOWN


class TestAplicarPrecedencia:
    """O portão onde a regra fundamental vira código."""

    def _confirmado(self):
        r = resolver(
            [src("manual", dt.date(2026, 8, 20), EarningsStatus.CONFIRMED)], AGORA
        )
        return aplicar(None, "VALE3", "2026Q3", r,
                       [src("manual", dt.date(2026, 8, 20), EarningsStatus.CONFIRMED)],
                       agora=AGORA)

    def test_estimativa_posterior_nao_derruba_confirmacao(self):
        confirmado = self._confirmado()
        nova = [src("yfinance", dt.date(2026, 8, 21), EarningsStatus.ESTIMATED)]
        atualizado = aplicar(
            confirmado, "VALE3", "2026Q3", resolver(nova, AGORA), nova, agora=AGORA
        )
        assert atualizado.confirmed_date == dt.date(2026, 8, 20)
        assert atualizado.status == EarningsStatus.CONFIRMED

    def test_informacao_conflitante_e_preservada_nas_fontes(self):
        confirmado = self._confirmado()
        nova = [src("yfinance", dt.date(2026, 8, 21), EarningsStatus.ESTIMATED)]
        atualizado = aplicar(
            confirmado, "VALE3", "2026Q3", resolver(nova, AGORA), nova, agora=AGORA
        )
        datas_afirmadas = {s.date for s in atualizado.sources}
        assert dt.date(2026, 8, 21) in datas_afirmadas
        assert any("ignorado" in c for c in atualizado.conflicts)

    def test_divulgacao_sobrescreve_confirmacao(self):
        confirmado = self._confirmado()
        nova = [src("cvm", dt.date(2026, 8, 20), EarningsStatus.RELEASED)]
        atualizado = aplicar(
            confirmado, "VALE3", "2026Q3", resolver(nova, AGORA), nova, agora=AGORA
        )
        assert atualizado.status == EarningsStatus.RELEASED

    def test_mudanca_de_data_confirmada_vira_remarcacao(self):
        confirmado = self._confirmado()
        nova = [src("manual", dt.date(2026, 8, 27), EarningsStatus.CONFIRMED)]
        atualizado = aplicar(
            confirmado, "VALE3", "2026Q3", resolver(nova, AGORA), nova, agora=AGORA
        )
        assert atualizado.status == EarningsStatus.RESCHEDULED
        assert atualizado.confirmed_date == dt.date(2026, 8, 27)
        assert any("remarcado" in c for c in atualizado.conflicts)

    def test_first_seen_at_e_preservado_na_atualizacao(self):
        confirmado = self._confirmado()
        depois = AGORA + dt.timedelta(days=1)
        nova = [src("cvm", dt.date(2026, 8, 20), EarningsStatus.RELEASED,
                    retrieved_at=depois)]
        atualizado = aplicar(
            confirmado, "VALE3", "2026Q3", resolver(nova, depois), nova, agora=depois
        )
        assert atualizado.first_seen_at == confirmado.first_seen_at
        assert atualizado.updated_at == depois
