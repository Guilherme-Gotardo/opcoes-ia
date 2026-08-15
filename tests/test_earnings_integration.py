"""Testes de integração do Earnings Event Service contra o Postgres real.

Pulados automaticamente quando não há banco acessível, para que `pytest`
continue verde numa máquina sem `docker compose up -d db`.

Os dados usados aqui NÃO são inventados: são as divulgações reais medidas
na investigação de 2026-08-15 (yfinance 1.6.0 e dump IPE da CVM), incluindo
a divergência genuína da VALE3.
"""
import datetime as dt
import os

import pytest

psycopg = pytest.importorskip("psycopg")

from src.earnings.models import EarningsEventSource, EarningsStatus, Session  # noqa: E402
from src.earnings.repository import EarningsEventRepository  # noqa: E402
from src.earnings.risk import EarningsRiskService  # noqa: E402
from src.earnings.service import EarningsEventService  # noqa: E402

UTC = dt.timezone.utc
AGORA = dt.datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
HOJE = dt.date(2026, 8, 15)

#: Divulgações reais do 2T26, conforme medido. A coluna CVM vem de
#: `Data_Entrega` na categoria «Dados Econômico-Financeiros»; a coluna
#: yfinance vem de `earnings_dates`.
DIVULGACOES_REAIS_2T26 = [
    # ticker,  cvm,                  yfinance,             concordam
    ("PETR4", dt.date(2026, 8, 6),  dt.date(2026, 8, 6),  True),
    ("ITUB4", dt.date(2026, 8, 4),  dt.date(2026, 8, 4),  True),
    ("ABEV3", dt.date(2026, 7, 30), dt.date(2026, 7, 30), True),
    ("VALE3", dt.date(2026, 7, 30), dt.date(2026, 7, 31), False),
]

PREFIXO_TESTE = "ZZ"  # tickers sintéticos, para não colidir com dado real


def _banco_disponivel() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.earnings_events')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _banco_disponivel(),
    reason="Postgres indisponível ou migração 001 não aplicada "
           "(docker compose up -d db && psql -f src/db/migrations/001_earnings_events.sql)",
)


@pytest.fixture
def repo():
    r = EarningsEventRepository()
    yield r
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM earnings_events WHERE ticker LIKE %s", (PREFIXO_TESTE + "%",))
        conn.commit()


def src(ticker, provider, date, status, **kw) -> EarningsEventSource:
    return EarningsEventSource(
        ticker=ticker, provider=provider, date=date, status=status,
        retrieved_at=kw.pop("retrieved_at", AGORA),
        confidence=kw.pop("confidence", 50), **kw,
    )


class TestPersistencia:
    def test_grava_e_le_evento_com_fontes(self, repo):
        svc = EarningsEventService(repository=repo)
        t = PREFIXO_TESTE + "PET"
        svc.registrar(t, "2026Q2", [src(t, "cvm", dt.date(2026, 8, 6), EarningsStatus.RELEASED)], agora=AGORA)

        lido = repo.get(t, "2026Q2")
        assert lido is not None
        assert lido.confirmed_date == dt.date(2026, 8, 6)
        assert lido.status == EarningsStatus.RELEASED
        assert len(lido.sources) == 1
        assert lido.sources[0].provider == "cvm"

    def test_reingerir_a_mesma_coleta_nao_duplica_fonte(self, repo):
        svc = EarningsEventService(repository=repo)
        t = PREFIXO_TESTE + "DUP"
        fonte = src(t, "cvm", dt.date(2026, 8, 6), EarningsStatus.RELEASED)
        svc.registrar(t, "2026Q2", [fonte], agora=AGORA)
        svc.registrar(t, "2026Q2", [fonte], agora=AGORA)
        assert len(repo.get(t, "2026Q2").sources) == 1


class TestConflitoRealVale3:
    """yfinance diz 31/07, CVM diz 30/07. A CVM está certa."""

    def test_cvm_vence_mesmo_chegando_depois(self, repo):
        svc = EarningsEventService(repository=repo)
        t = PREFIXO_TESTE + "VAL"

        svc.registrar(t, "2026Q2",
                      [src(t, "yfinance", dt.date(2026, 7, 31), EarningsStatus.ESTIMATED)],
                      agora=AGORA)
        svc.registrar(t, "2026Q2",
                      [src(t, "cvm", dt.date(2026, 7, 30), EarningsStatus.RELEASED)],
                      agora=AGORA + dt.timedelta(hours=1))

        e = repo.get(t, "2026Q2")
        assert e.confirmed_date == dt.date(2026, 7, 30)
        assert e.status == EarningsStatus.RELEASED

    def test_a_data_perdedora_continua_registrada(self, repo):
        svc = EarningsEventService(repository=repo)
        t = PREFIXO_TESTE + "VA2"
        svc.registrar(t, "2026Q2",
                      [src(t, "yfinance", dt.date(2026, 7, 31), EarningsStatus.ESTIMATED)],
                      agora=AGORA)
        svc.registrar(t, "2026Q2",
                      [src(t, "cvm", dt.date(2026, 7, 30), EarningsStatus.RELEASED)],
                      agora=AGORA + dt.timedelta(hours=1))

        e = repo.get(t, "2026Q2")
        datas = {s.date for s in e.sources}
        assert datas == {dt.date(2026, 7, 30), dt.date(2026, 7, 31)}, (
            "a afirmação descartada precisa sobreviver como rastro de auditoria"
        )

    def test_estimativa_posterior_nao_derruba_o_divulgado(self, repo):
        svc = EarningsEventService(repository=repo)
        t = PREFIXO_TESTE + "VA3"
        svc.registrar(t, "2026Q2",
                      [src(t, "cvm", dt.date(2026, 7, 30), EarningsStatus.RELEASED)],
                      agora=AGORA)
        svc.registrar(t, "2026Q2",
                      [src(t, "yfinance", dt.date(2026, 7, 31), EarningsStatus.ESTIMATED)],
                      agora=AGORA + dt.timedelta(days=1))

        e = repo.get(t, "2026Q2")
        assert e.confirmed_date == dt.date(2026, 7, 30)
        assert e.status == EarningsStatus.RELEASED
        assert any("ignorado" in c for c in e.conflicts)


class TestConcordanciaReal:
    @pytest.mark.parametrize("ticker,cvm,yf,concordam", DIVULGACOES_REAIS_2T26)
    def test_divulgacoes_medidas_em_2026_08_15(self, repo, ticker, cvm, yf, concordam):
        svc = EarningsEventService(repository=repo)
        t = PREFIXO_TESTE + ticker[:3]
        fontes = [
            src(t, "yfinance", yf, EarningsStatus.ESTIMATED),
            src(t, "cvm", cvm, EarningsStatus.RELEASED),
        ]
        e = svc.registrar(t, "2026Q2", fontes, agora=AGORA)

        assert e.confirmed_date == cvm, "a evidência regulatória define a data"
        assert bool(e.conflicts) is not concordam


class TestProximoEvento:
    def test_ignora_evento_passado(self, repo):
        svc = EarningsEventService(repository=repo)
        t = PREFIXO_TESTE + "PAS"
        svc.registrar(t, "2026Q2",
                      [src(t, "cvm", dt.date(2026, 7, 30), EarningsStatus.RELEASED)],
                      agora=AGORA)
        assert repo.proximo_evento(t, HOJE) is None, (
            "evento vencido precisa voltar a ser desconhecido, "
            "nunca seguir aprovando o critério com valor obsoleto"
        )

    def test_encontra_evento_futuro(self, repo):
        svc = EarningsEventService(repository=repo)
        t = PREFIXO_TESTE + "FUT"
        svc.registrar(t, "2026Q3",
                      [src(t, "manual", dt.date(2026, 11, 6), EarningsStatus.CONFIRMED,
                           session=Session.AFTER_CLOSE)],
                      agora=AGORA)
        e = repo.proximo_evento(t, HOJE)
        assert e is not None and e.effective_date == dt.date(2026, 11, 6)


class TestEntradaManual:
    """CLI + ManualProvider contra o banco real."""

    @pytest.fixture
    def limpar_manuais(self):
        yield
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM earnings_manual_entries WHERE ticker LIKE %s",
                        (PREFIXO_TESTE + "%",))
            conn.commit()

    def test_registra_e_o_provider_le_de_volta(self, limpar_manuais):
        from src.earnings.manage import add_data_resultado
        from src.earnings.providers.manual import ManualProvider

        t = PREFIXO_TESTE + "MAN"
        periodo = add_data_resultado(
            t, dt.date(2099, 11, 6), sessao=Session.AFTER_CLOSE,
            origem="https://exemplo/ri",
        )
        assert periodo == "2099Q3"

        fontes = ManualProvider().get_upcoming_earnings([t])
        assert len(fontes) == 1
        assert fontes[0].status == EarningsStatus.CONFIRMED
        assert fontes[0].session == Session.AFTER_CLOSE
        assert fontes[0].confidence == 97

    def test_regravar_o_mesmo_trimestre_e_correcao_nao_duplicata(self, limpar_manuais):
        from src.earnings.manage import add_data_resultado, list_datas_resultado
        from src.earnings.providers.manual import ManualProvider

        t = PREFIXO_TESTE + "COR"
        add_data_resultado(t, dt.date(2099, 11, 6), fiscal_period="2099Q3")
        add_data_resultado(t, dt.date(2099, 11, 13), fiscal_period="2099Q3")

        assert len(list_datas_resultado(t)) == 1
        fontes = ManualProvider().get_upcoming_earnings([t])
        assert len(fontes) == 1
        assert fontes[0].date == dt.date(2099, 11, 13), "a correção precisa prevalecer"

    def test_data_invalida_e_rejeitada_sem_gravar(self, limpar_manuais):
        from src.earnings.manage import EntradaInvalida, _parse_data, list_datas_resultado

        with pytest.raises(EntradaInvalida, match="AAAA-MM-DD"):
            _parse_data("06/11/2026")
        assert list_datas_resultado(PREFIXO_TESTE + "INV") == []

    def test_sessao_invalida_e_rejeitada(self):
        from src.earnings.manage import EntradaInvalida, _parse_sessao

        with pytest.raises(EntradaInvalida, match="sessão inválida"):
            _parse_sessao("DEPOIS_DO_ALMOCO")

    def test_remover_entrada_inexistente_falha_alto(self):
        from src.earnings.manage import EntradaInvalida, remove_data_resultado

        with pytest.raises(EntradaInvalida, match="nenhuma entrada"):
            remove_data_resultado(PREFIXO_TESTE + "NAO", "2099Q9")

    def test_manual_vence_yfinance_no_mesmo_evento(self, repo, limpar_manuais):
        """A combinação que a Fase 2 entrega: RI confirma, Yahoo ecoa."""
        from src.earnings.manage import add_data_resultado
        from src.earnings.providers.manual import ManualProvider

        t = PREFIXO_TESTE + "MIX"
        add_data_resultado(t, dt.date(2099, 10, 29), fiscal_period="2099Q3",
                           sessao=Session.AFTER_CLOSE)

        fontes = ManualProvider().get_upcoming_earnings([t])
        fontes.append(src(t, "yfinance", dt.date(2099, 10, 30), EarningsStatus.ESTIMATED))

        e = EarningsEventService(repository=repo).registrar(
            t, "2099Q3", fontes, agora=AGORA
        )
        assert e.confirmed_date == dt.date(2099, 10, 29)
        assert e.status == EarningsStatus.CONFIRMED
        assert e.session == Session.AFTER_CLOSE
        assert dt.date(2099, 10, 30) in {s.date for s in e.sources}


class TestFluxoAteORisco:
    """Do registro até a resposta que o motor de opções consome."""

    def test_evento_confirmado_proximo_vira_risco_alto(self, repo):
        svc = EarningsEventService(repository=repo)
        risco_svc = EarningsRiskService()
        t = PREFIXO_TESTE + "RSK"
        svc.registrar(t, "2026Q3",
                      [src(t, "manual", HOJE + dt.timedelta(days=2),
                           EarningsStatus.CONFIRMED, session=Session.AFTER_CLOSE)],
                      agora=AGORA)

        r = risco_svc.avaliar(t, repo.proximo_evento(t, HOJE), HOJE)
        assert r.reliable is True
        assert r.confirmed is True
        assert r.risk.value == "HIGH"
        assert r.crosses_event(HOJE + dt.timedelta(days=30)) is True

    def test_so_estimativa_secundaria_nao_alcanca_a_confianca_minima(self, repo):
        """yfinance sozinho fica em 45 — abaixo do mínimo de 60."""
        svc = EarningsEventService(repository=repo)
        risco_svc = EarningsRiskService()
        t = PREFIXO_TESTE + "FRA"
        svc.registrar(t, "2026Q3",
                      [src(t, "yfinance", HOJE + dt.timedelta(days=5),
                           EarningsStatus.ESTIMATED)],
                      agora=AGORA)

        r = risco_svc.avaliar(t, repo.proximo_evento(t, HOJE), HOJE)
        assert r.reliable is False
        assert r.crosses_event(HOJE + dt.timedelta(days=30)) is None
