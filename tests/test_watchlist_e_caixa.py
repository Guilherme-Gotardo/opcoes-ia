"""Watchlist e caixa — as duas peças que abrem a varredura de mercado.

O banco é dublado: o que se prova é a regra (universo é união, saldo é
soma, zero é recusado), não o SQL.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.assets import manage as ativos
from src.assets.manage import AtivoInvalido
from src.caixa import manage as caixa
from src.caixa.manage import LancamentoInvalido


def _cursor(resultado=None, um=None):
    cur = MagicMock()
    cur.fetchall.return_value = resultado or []
    cur.fetchone.return_value = um
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    return ctx, conn, cur


# --- watchlist --------------------------------------------------------------

def test_vigiar_exige_ativo_cadastrado():
    """`ativos` é alvo de FK de cotação, opção e notícia — vigiar um ticker
    desconhecido criaria coleta que o banco recusaria depois."""
    with patch.object(ativos, "ativo_existe", return_value=False):
        with pytest.raises(AtivoInvalido, match="não cadastrado"):
            ativos.vigiar("XPTO3")


def test_vigiar_preserva_a_data_de_entrada():
    """Revigiar não reinicia `vigiado_desde`: perder desde quando o ativo é
    observado apagaria o histórico da decisão."""
    ctx, conn, cur = _cursor()
    with patch.object(ativos, "ativo_existe", return_value=True), \
         patch.object(ativos, "get_connection", return_value=ctx):
        ativos.vigiar("PETR4", "IV alta e liquidez")

    sql = cur.execute.call_args[0][0]
    assert "COALESCE(vigiado_desde, now())" in sql
    assert conn.commit.called


def test_parar_de_vigiar_preserva_o_cadastro():
    ctx, conn, cur = _cursor()
    with patch.object(ativos, "get_connection", return_value=ctx):
        ativos.parar_de_vigiar("PETR4")

    sql = cur.execute.call_args[0][0]
    assert "vigiado = FALSE" in sql
    assert "DELETE" not in sql.upper(), "sair da watchlist não descadastra"


def test_universo_e_uniao_de_carteira_e_vigiados():
    """A união importa nos dois sentidos: ativo em carteira entra mesmo sem
    ser vigiado, senão parar de vigiar deixaria a posição sem preço."""
    ctx, _, cur = _cursor(resultado=[("PETR4",), ("VALE3",), ("ITUB4",)])
    with patch.object(ativos, "get_connection", return_value=ctx):
        universo = ativos.universo_de_analise()

    sql = cur.execute.call_args[0][0]
    assert "UNION" in sql
    assert "WHERE vigiado" in sql
    assert "tipo_ativo = 'ACAO'" in sql
    assert universo == ["PETR4", "VALE3", "ITUB4"]


def test_etls_coletam_o_universo_e_nao_so_a_carteira():
    """A mudança que abre a varredura: os três ETLs partem do universo."""
    from src.etl import fetch_candles, fetch_options, fetch_quotes

    for modulo, funcao in (
        (fetch_quotes, "_tickers_da_carteira"),
        (fetch_candles, "_tickers_da_carteira"),
        (fetch_options, "_tickers_objeto_da_carteira"),
    ):
        with patch.object(modulo, "universo_de_analise",
                          return_value=["PETR4", "ITUB4"]) as universo:
            assert getattr(modulo, funcao)() == ["PETR4", "ITUB4"]
            assert universo.called, f"{modulo.__name__} ignorou o universo"


# --- caixa ------------------------------------------------------------------

def test_saldo_e_soma_dos_lancamentos():
    ctx, _, cur = _cursor(um=(1500.0,))
    with patch.object(caixa, "get_connection", return_value=ctx):
        assert caixa.saldo() == 1500.0
    assert "SUM(valor)" in cur.execute.call_args[0][0]


def test_lancamento_zero_e_recusado():
    """Não é movimento: aceitar produziria linha que polui o extrato sem
    mudar o saldo."""
    with pytest.raises(LancamentoInvalido, match="não pode ser zero"):
        caixa.registrar(0)


def test_retirada_entra_como_negativo():
    """O sinal preserva o que aconteceu, em vez de só onde chegou."""
    ctx, conn, cur = _cursor(um=(7,))
    with patch.object(caixa, "get_connection", return_value=ctx):
        caixa.registrar(-500.0, "compra de ações")

    params = cur.execute.call_args[0][1]
    assert params[0] == -500.0
    assert conn.commit.called


def test_sem_lancamento_o_saldo_e_zero_e_isso_barra_a_put():
    """Zero aqui significa 'sem garantia registrada' — e é o que faz
    `avaliar()` recusar a put coberta em vez de tratá-la como coberta."""
    ctx, _, _ = _cursor(um=(0,))
    with patch.object(caixa, "get_connection", return_value=ctx):
        assert caixa.saldo() == 0.0
