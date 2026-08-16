"""Testes de src.strategy.outcome_repository contra o Postgres real.

Pulados sem banco, no padrão de tests/test_earnings_integration.py. Usam
ticker sintético com prefixo ZZ e limpam o que criaram."""
import datetime as dt
import os

import pytest

from src.strategy.outcome import LinhaDesfecho, Motivo
from src.strategy.outcome_repository import gravar, ultima_execucao_do_dia

psycopg = pytest.importorskip("psycopg")

TICKER = "ZZDESF3"


def _banco_disponivel() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.desfecho_avaliacao')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _banco_disponivel(),
    reason="Postgres indisponível ou migração 003 não aplicada "
           "(docker compose up -d db && python -m src.db.bootstrap)",
)


@pytest.fixture
def ativo():
    """`desfecho_avaliacao.ticker_objeto` tem FK para `ativos`."""
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ativos (ticker, nome, tipo) VALUES (%s,%s,%s) "
            "ON CONFLICT (ticker) DO NOTHING",
            (TICKER, "Ativo sintético de teste", "acao"),
        )
        conn.commit()
    yield TICKER
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM desfecho_avaliacao WHERE ticker_objeto = %s", (TICKER,))
        cur.execute("DELETE FROM ativos WHERE ticker = %s", (TICKER,))
        conn.commit()


def _gravar(linhas, executado_em):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        n = gravar(cur, executado_em, linhas)
        conn.commit()
    return n


def test_desfecho_sobrevive_a_execucao(ativo):
    """O ponto da change: o motivo deixa de morrer com o processo."""
    agora = dt.datetime.now(dt.timezone.utc)
    _gravar([
        LinhaDesfecho(ativo, Motivo.CRITERIO_REPROVADO, 8,
                      {"iv_rank": 8}, {"codigo_opcao": "ZZI450"}),
    ], agora)

    linhas = ultima_execucao_do_dia(agora.date())
    minhas = [l for l in linhas if l.ticker_objeto == ativo]
    assert len(minhas) == 1
    assert minhas[0].motivo == Motivo.CRITERIO_REPROVADO
    assert minhas[0].quantidade == 8
    assert minhas[0].criterios_contagem == {"iv_rank": 8}
    assert minhas[0].amostra["codigo_opcao"] == "ZZI450"


def test_duas_execucoes_no_mesmo_dia_sao_distinguiveis(ativo):
    """Rodar de novo não pode somar com a rodada anterior — o relatório
    mostraria 18 onde foram 9, duas vezes."""
    agora = dt.datetime.now(dt.timezone.utc)
    antes = agora - dt.timedelta(hours=2)

    _gravar([LinhaDesfecho(ativo, Motivo.CRITERIO_REPROVADO, 9)], antes)
    _gravar([LinhaDesfecho(ativo, Motivo.SUGERIDA, 1)], agora)

    minhas = [l for l in ultima_execucao_do_dia(agora.date()) if l.ticker_objeto == ativo]
    assert len(minhas) == 1, "só a execução mais recente"
    assert minhas[0].motivo == Motivo.SUGERIDA
    assert minhas[0].quantidade == 1


def test_execucao_anterior_permanece_gravada(ativo):
    """A leitura devolve só a mais recente, mas o histórico continua lá —
    é o que permite comparar dias."""
    agora = dt.datetime.now(dt.timezone.utc)
    antes = agora - dt.timedelta(hours=2)
    _gravar([LinhaDesfecho(ativo, Motivo.CRITERIO_REPROVADO, 9)], antes)
    _gravar([LinhaDesfecho(ativo, Motivo.SUGERIDA, 1)], agora)

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM desfecho_avaliacao WHERE ticker_objeto = %s",
            (ativo,),
        )
        assert cur.fetchone()[0] == 2


def test_dia_sem_execucao_devolve_vazio(ativo):
    assert ultima_execucao_do_dia(dt.date(2020, 1, 1)) == []


def test_gravar_lista_vazia_nao_faz_nada(ativo):
    assert _gravar([], dt.datetime.now(dt.timezone.utc)) == 0


def test_varias_linhas_da_mesma_execucao_saem_juntas(ativo):
    agora = dt.datetime.now(dt.timezone.utc)
    _gravar([
        LinhaDesfecho(ativo, Motivo.SUGERIDA, 1),
        LinhaDesfecho(ativo, Motivo.CRITERIO_REPROVADO, 8, {"delta": 8}),
    ], agora)

    minhas = [l for l in ultima_execucao_do_dia(agora.date()) if l.ticker_objeto == ativo]
    assert {l.motivo for l in minhas} == {Motivo.SUGERIDA, Motivo.CRITERIO_REPROVADO}
