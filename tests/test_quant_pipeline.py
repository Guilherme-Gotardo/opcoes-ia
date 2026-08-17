"""Testes da camada com I/O do enriquecimento, contra o Postgres real.

Pulados sem banco, no padrão de tests/test_outcome_repository.py. Usam
ticker sintético com prefixo ZZ e limpam o que criaram.

A propriedade mais importante coberta aqui: **enriquecimento nunca derruba a
avaliação**. Tabela ausente, BCB fora do ar, opção inexistente — tudo vira
linha declarada ou zero linhas, nunca exceção subindo.
"""
import datetime as dt
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.quant import pipeline as mod
from src.quant.enrichment import Enriquecimento
from src.quant.taxa import TaxaLivreRisco

psycopg = pytest.importorskip("psycopg")

TICKER = "ZZQUANT3"
TAXA = TaxaLivreRisco(0.139, dt.date(2026, 8, 14), "teste")
EXECUCAO = dt.datetime(2026, 8, 17, 12, 0, tzinfo=dt.timezone.utc)


def _banco_disponivel() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.enriquecimento_quant')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _banco_disponivel(),
    reason="Postgres indisponível ou migração 008 não aplicada "
           "(docker compose up -d db && python -m src.db.bootstrap)",
)


@pytest.fixture
def ativo():
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ativos (ticker, nome, tipo) VALUES (%s,%s,'acao') "
            "ON CONFLICT (ticker) DO NOTHING",
            (TICKER, "Ativo sintético de teste"),
        )
        conn.commit()
    yield TICKER
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM enriquecimento_quant WHERE ticker_objeto = %s", (TICKER,))
        cur.execute("DELETE FROM opcoes WHERE ticker_objeto = %s", (TICKER,))
        cur.execute("DELETE FROM ativos WHERE ticker = %s", (TICKER,))
        conn.commit()


def _conn():
    return psycopg.connect(os.environ["DATABASE_URL"])


def _opcao(cur, codigo, *, strike=42.0, iv=0.32, dias=35, tipo="CALL", coletado=None):
    cur.execute(
        "INSERT INTO opcoes (codigo,ticker_objeto,tipo,strike,vencimento,preco,"
        "volatilidade_implicita,coletado_em,fonte) "
        "VALUES (%s,%s,%s,%s,%s,1.5,%s,%s,'sintetico')",
        (codigo, TICKER, tipo, strike, EXECUCAO.date() + dt.timedelta(days=dias),
         iv, coletado or EXECUCAO),
    )


def _resultado(codigo, **extra):
    return SimpleNamespace(
        ticker_objeto=TICKER, codigo_opcao=codigo, strike=42.0,
        preco_mercado=40.0, **extra,
    )


# --- persistência ------------------------------------------------------------

def test_gravar_guarda_a_auditoria_junto_do_numero(ativo):
    enr = Enriquecimento(
        delta_modelo=0.45, gamma=0.07, theta_dia=-0.02, vega_pp=0.06,
        rho_pp=0.03, preco_teorico=1.61, prob_exercicio_vencimento=0.39,
        modelo="CRR-binomial-1024", estilo_exercicio="americana",
        taxa_livre_risco=0.139, taxa_observada_em=dt.date(2026, 8, 14),
        volatilidade_usada=0.32, calculado_em=EXECUCAO, ressalvas=("uma ressalva",),
    )
    with _conn() as conn, conn.cursor() as cur:
        mod.gravar(cur, EXECUCAO, TICKER, "ZZQ42", enr)
        conn.commit()
        cur.execute(
            "SELECT preco_teorico, modelo, estilo_exercicio, taxa_livre_risco, "
            "taxa_observada_em, volatilidade_usada, ressalvas "
            "FROM enriquecimento_quant WHERE codigo_opcao = 'ZZQ42'"
        )
        preco, modelo, estilo, taxa, observada, vol, ressalvas = cur.fetchone()

    assert float(preco) == pytest.approx(1.61)
    # Sem estes cinco campos, o preço acima é um número irreconstruível.
    assert modelo == "CRR-binomial-1024"
    assert estilo == "americana"
    assert float(taxa) == pytest.approx(0.139)
    assert observada == dt.date(2026, 8, 14)
    assert float(vol) == pytest.approx(0.32)
    assert ressalvas == ["uma ressalva"]


def test_reprocessar_a_mesma_execucao_atualiza_em_vez_de_duplicar(ativo):
    """Reprocessar com um modelo melhor não pode empilhar duas verdades para
    a mesma opção na mesma execução."""
    with _conn() as conn, conn.cursor() as cur:
        mod.gravar(cur, EXECUCAO, TICKER, "ZZQ42",
                   Enriquecimento(preco_teorico=1.0, modelo="v1", calculado_em=EXECUCAO))
        mod.gravar(cur, EXECUCAO, TICKER, "ZZQ42",
                   Enriquecimento(preco_teorico=2.0, modelo="v2", calculado_em=EXECUCAO))
        conn.commit()
        cur.execute(
            "SELECT count(*), max(modelo), max(preco_teorico) "
            "FROM enriquecimento_quant WHERE codigo_opcao = 'ZZQ42'"
        )
        n, modelo, preco = cur.fetchone()

    assert n == 1
    assert modelo == "v2"
    assert float(preco) == pytest.approx(2.0)


# --- a taxa e seu fallback ---------------------------------------------------

def test_taxa_reaproveitada_quando_o_bcb_cai(ativo):
    with _conn() as conn, conn.cursor() as cur:
        mod.gravar(cur, EXECUCAO, TICKER, "ZZQ42", Enriquecimento(
            taxa_livre_risco=0.1275, taxa_observada_em=dt.date(2026, 8, 15),
            calculado_em=EXECUCAO,
        ))
        conn.commit()
        with patch.object(mod, "buscar_taxa", return_value=None):
            taxa, ressalvas = mod.taxa_vigente(cur, dt.date(2026, 8, 17))

    assert taxa is not None
    assert taxa.valor_aa == pytest.approx(0.1275)
    assert any("BCB indisponível" in m for m in ressalvas)
    assert "reaproveitada" in taxa.fonte


def test_sem_bcb_e_sem_historico_a_taxa_e_declarada_ausente(ativo):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM enriquecimento_quant")
        conn.commit()
        with patch.object(mod, "buscar_taxa", return_value=None):
            taxa, ressalvas = mod.taxa_vigente(cur, dt.date(2026, 8, 17))

    assert taxa is None
    assert any("indisponível" in m for m in ressalvas)


def test_taxa_velha_ganha_ressalva(ativo):
    """A Selic só muda em reunião do Copom; uma taxa de semanas atrás pode
    ter atravessado uma decisão, e isso precisa aparecer."""
    antiga = TaxaLivreRisco(0.139, dt.date(2026, 7, 1), "teste")
    with _conn() as conn, conn.cursor() as cur, \
            patch.object(mod, "buscar_taxa", return_value=antiga):
        _, ressalvas = mod.taxa_vigente(cur, dt.date(2026, 8, 17))
    assert any("Copom" in m for m in ressalvas)


def test_taxa_recente_nao_ganha_ressalva(ativo):
    recente = TaxaLivreRisco(0.139, dt.date(2026, 8, 16), "teste")
    with _conn() as conn, conn.cursor() as cur, \
            patch.object(mod, "buscar_taxa", return_value=recente):
        _, ressalvas = mod.taxa_vigente(cur, dt.date(2026, 8, 17))
    assert ressalvas == []


# --- insumos vindos do banco --------------------------------------------------

def test_cadeia_exclui_a_propria_opcao(ativo):
    """Incluir a própria opção puxaria a média na direção dela e
    subestimaria o skew."""
    with _conn() as conn, conn.cursor() as cur:
        for codigo, iv in (("ZZQ40", 0.30), ("ZZQ42", 0.50), ("ZZQ44", 0.30)):
            _opcao(cur, codigo, iv=iv)
        conn.commit()
        vencimento = EXECUCAO.date() + dt.timedelta(days=35)
        ivs = mod._ivs_da_cadeia(cur, TICKER, vencimento, "ZZQ42")

    assert sorted(ivs) == [0.30, 0.30]


def test_cadeia_usa_a_coleta_mais_recente_de_cada_opcao(ativo):
    with _conn() as conn, conn.cursor() as cur:
        _opcao(cur, "ZZQ40", iv=0.20, coletado=EXECUCAO - dt.timedelta(days=2))
        _opcao(cur, "ZZQ40", iv=0.45, coletado=EXECUCAO)
        conn.commit()
        vencimento = EXECUCAO.date() + dt.timedelta(days=35)
        assert mod._ivs_da_cadeia(cur, TICKER, vencimento, "OUTRA") == [0.45]


def test_historico_respeita_a_janela_do_percentil(ativo):
    with _conn() as conn, conn.cursor() as cur:
        _opcao(cur, "ZZQDENTRO", iv=0.31, coletado=EXECUCAO - dt.timedelta(days=100))
        _opcao(cur, "ZZQFORA", iv=0.99, coletado=EXECUCAO - dt.timedelta(days=400))
        conn.commit()
        ivs = mod._ivs_historicas(cur, TICKER, EXECUCAO.date())

    assert 0.31 in ivs
    assert 0.99 not in ivs, "coleta anterior à janela de 252 dias não entra"


# --- o fluxo completo, e o que ele nunca faz ---------------------------------

def test_enriquece_toda_opcao_avaliada_inclusive_a_reprovada(ativo):
    with _conn() as conn, conn.cursor() as cur:
        for codigo in ("ZZQ40", "ZZQ42", "ZZQ44"):
            _opcao(cur, codigo)
        conn.commit()
        with patch.object(mod, "buscar_taxa", return_value=TAXA):
            n = mod.enriquecer_avaliacoes(
                cur, EXECUCAO, [_resultado(c) for c in ("ZZQ40", "ZZQ42", "ZZQ44")]
            )
        conn.commit()
        cur.execute(
            "SELECT count(*) FROM enriquecimento_quant WHERE ticker_objeto = %s", (TICKER,)
        )
        assert cur.fetchone()[0] == 3
    assert n == 3


def test_opcao_ausente_de_opcoes_vira_linha_declarada(ativo):
    """"Não deu para enriquecer, e por quê" é informação. Pular em silêncio
    faria a ausência da linha significar duas coisas diferentes."""
    with _conn() as conn, conn.cursor() as cur:
        with patch.object(mod, "buscar_taxa", return_value=TAXA):
            mod.enriquecer_avaliacoes(cur, EXECUCAO, [_resultado("ZZQINEXISTENTE")])
        conn.commit()
        cur.execute(
            "SELECT modelo, ressalvas FROM enriquecimento_quant "
            "WHERE codigo_opcao = 'ZZQINEXISTENTE'"
        )
        modelo, ressalvas = cur.fetchone()

    assert modelo == "indisponivel"
    assert any("não encontrada" in m for m in ressalvas)


def test_ressalva_da_taxa_viaja_para_cada_opcao(ativo):
    antiga = TaxaLivreRisco(0.139, dt.date(2026, 6, 1), "teste")
    with _conn() as conn, conn.cursor() as cur:
        _opcao(cur, "ZZQ42")
        conn.commit()
        with patch.object(mod, "buscar_taxa", return_value=antiga):
            mod.enriquecer_avaliacoes(cur, EXECUCAO, [_resultado("ZZQ42")])
        conn.commit()
        cur.execute("SELECT ressalvas FROM enriquecimento_quant WHERE codigo_opcao='ZZQ42'")
        ressalvas = cur.fetchone()[0]

    assert any("Copom" in m for m in ressalvas)


def test_resultado_sem_codigo_de_opcao_e_ignorado(ativo):
    with _conn() as conn, conn.cursor() as cur, \
            patch.object(mod, "buscar_taxa", return_value=TAXA):
        assert mod.enriquecer_avaliacoes(cur, EXECUCAO, [_resultado(None)]) == 0


def test_lista_vazia_nao_toca_o_banco(ativo):
    with _conn() as conn, conn.cursor() as cur:
        assert mod.enriquecer_avaliacoes(cur, EXECUCAO, []) == 0


def test_execucao_sem_a_tabela_nao_levanta(ativo):
    """A garantia central: sem a migração 008, a avaliação segue igual."""
    class _CursorSemTabela:
        def execute(self, *a, **k): pass
        def fetchone(self): return (None,)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _ConnSemTabela:
        def cursor(self): return _CursorSemTabela()
        def commit(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    from contextlib import contextmanager

    @contextmanager
    def _fake():
        yield _ConnSemTabela()

    with patch("src.db.connection.get_connection", _fake):
        assert mod.enriquecer_execucao(EXECUCAO, [_resultado("ZZQ42")]) == 0


def test_erro_de_banco_no_enriquecimento_nao_propaga(ativo):
    """Nenhuma falha aqui pode invalidar a decisão, que já foi gravada."""
    from contextlib import contextmanager

    @contextmanager
    def _explode():
        raise RuntimeError("banco caiu")
        yield  # pragma: no cover

    with patch("src.db.connection.get_connection", _explode):
        assert mod.enriquecer_execucao(EXECUCAO, [_resultado("ZZQ42")]) == 0
