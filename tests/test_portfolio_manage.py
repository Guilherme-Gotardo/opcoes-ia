"""Testes de src.portfolio.manage — usam um banco fake (mock de cursor/conexão)
para não depender de um Postgres real rodando."""
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from src.portfolio import manage
from src.portfolio.manage import (
    PosicaoInvalida,
    add_posicao,
    close_posicao,
    list_posicoes_abertas,
)


class _FakeCursor:
    def __init__(self, fetchone_return=None, rowcount=1, rows=None, columns=None):
        self.fetchone_return = fetchone_return
        self.rowcount = rowcount
        self.rows = rows or []
        self.description = [_Col(c) for c in (columns or [])]
        self.queries: list[tuple[str, tuple]] = []

    def execute(self, query, params=()):
        self.queries.append((query, params))

    def fetchone(self):
        return self.fetchone_return

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Col:
    def __init__(self, name):
        self.name = name


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def _patched_get_connection(fake_conn: _FakeConnection):
    @contextmanager
    def _fake():
        yield fake_conn

    return _fake


def _ativo_cadastrado(existe=True):
    """`add_posicao` consulta `ativos` por outra conexão (a de
    `assets.manage`), então o dublê é da função, não do cursor."""
    return patch("src.portfolio.manage.ativo_existe", return_value=existe)


def test_add_posicao_acao_valida():
    cursor = _FakeCursor(fetchone_return=(1,))
    fake_conn = _FakeConnection(cursor)
    with patch(
        "src.portfolio.manage.get_connection", _patched_get_connection(fake_conn)
    ), _ativo_cadastrado():
        posicao_id = add_posicao("PETR4", "ACAO", 100, 32.50)

    assert posicao_id == 1
    assert fake_conn.committed
    query, params = cursor.queries[0]
    assert "INSERT INTO posicoes" in query
    # Os três últimos são os campos de opção da migração 005 — nulos numa
    # posição em ação, que é o que a validação exige.
    assert params == ("PETR4", "ACAO", 100, 32.50, "manual", None, None, None)


def test_add_posicao_acao_em_ativo_nao_cadastrado_e_recusada():
    """Sem o ativo, `cotacoes` não aceita a cotação desse ticker — a posição
    ficaria invisível para o ETL."""
    cursor = _FakeCursor(fetchone_return=(1,))
    fake_conn = _FakeConnection(cursor)
    with patch(
        "src.portfolio.manage.get_connection", _patched_get_connection(fake_conn)
    ), _ativo_cadastrado(existe=False), pytest.raises(PosicaoInvalida) as exc:
        add_posicao("XXXX9", "ACAO", 100, 10.0)

    mensagem = str(exc.value)
    assert "XXXX9" in mensagem, "precisa nomear o ticker"
    assert "src.assets.manage add" in mensagem, "precisa dizer como resolver"
    assert cursor.queries == [], "nada pode ser gravado"


def test_posicao_em_opcao_nao_exige_ativo_cadastrado():
    """`posicoes.ticker` guarda o CÓDIGO da opção, que não é linha em
    `ativos` — quem aponta para lá é `opcoes.ticker_objeto`."""
    cursor = _FakeCursor(fetchone_return=(7,))
    fake_conn = _FakeConnection(cursor)
    with patch(
        "src.portfolio.manage.get_connection", _patched_get_connection(fake_conn)
    ), _ativo_cadastrado(existe=False):
        assert add_posicao("PETRJ380", "OPCAO", -100, 0.85) == 7


def test_add_posicao_opcao_vendida_quantidade_negativa():
    cursor = _FakeCursor(fetchone_return=(2,))
    fake_conn = _FakeConnection(cursor)
    with patch(
        "src.portfolio.manage.get_connection", _patched_get_connection(fake_conn)
    ):
        posicao_id = add_posicao("PETRJ380", "OPCAO", -100, 0.85)

    assert posicao_id == 2
    _, params = cursor.queries[0]
    assert params[2] == -100


def test_add_posicao_quantidade_zero_rejeitada():
    with pytest.raises(PosicaoInvalida):
        add_posicao("PETR4", "ACAO", 0, 32.50)


def test_add_posicao_preco_invalido_rejeitado():
    with pytest.raises(PosicaoInvalida):
        add_posicao("PETR4", "ACAO", 100, 0)


def test_add_posicao_tipo_ativo_invalido_rejeitado():
    with pytest.raises(PosicaoInvalida):
        add_posicao("PETR4", "FII", 100, 32.50)


def test_close_posicao_existente():
    cursor = _FakeCursor(rowcount=1)
    fake_conn = _FakeConnection(cursor)
    with patch(
        "src.portfolio.manage.get_connection", _patched_get_connection(fake_conn)
    ):
        close_posicao(1)

    assert fake_conn.committed
    query, params = cursor.queries[0]
    assert "UPDATE posicoes" in query
    # `motivo_fechamento` é obrigatório desde a migração 005: `fechada_em`
    # sozinho diz quando fechou e nunca como.
    assert params == ("encerrada", None, 1)


def test_close_posicao_inexistente_levanta_erro():
    cursor = _FakeCursor(rowcount=0)
    fake_conn = _FakeConnection(cursor)
    with patch(
        "src.portfolio.manage.get_connection", _patched_get_connection(fake_conn)
    ):
        with pytest.raises(PosicaoInvalida):
            close_posicao(999)


def test_list_posicoes_abertas():
    columns = ["id", "ticker", "tipo_ativo", "quantidade", "preco_medio", "aberta_em", "origem"]
    rows = [(1, "PETR4", "ACAO", 100, 32.50, "2026-08-01T00:00:00", "manual")]
    cursor = _FakeCursor(rows=rows, columns=columns)
    fake_conn = _FakeConnection(cursor)
    with patch(
        "src.portfolio.manage.get_connection", _patched_get_connection(fake_conn)
    ):
        posicoes = list_posicoes_abertas()

    assert len(posicoes) == 1
    assert posicoes[0]["ticker"] == "PETR4"
    query, _ = cursor.queries[0]
    assert "fechada_em IS NULL" in query


# --- campos de opção e desfecho (migração 005) ------------------------------

def test_acao_nao_aceita_campos_de_opcao():
    """Strike numa posição de ação é dado no lugar errado — recusar é mais
    honesto do que gravar e ignorar depois."""
    with pytest.raises(PosicaoInvalida, match="não aceita"):
        manage.add_posicao("PETR4", "ACAO", 100, 32.5, strike=45.0)


def test_strike_precisa_ser_positivo():
    with pytest.raises(PosicaoInvalida, match="strike"):
        manage.add_posicao("PETRI450", "OPCAO", -100, 1.15, strike=0)


def test_recompra_sem_preco_e_recusada():
    """Sem o preço pago para sair, o resultado da operação sairia
    superestimado — e um número inflado é pior do que número nenhum."""
    with pytest.raises(PosicaoInvalida, match="superestimado"):
        manage.close_posicao(1, motivo="recomprada")


def test_motivo_de_fechamento_fora_do_conjunto_e_recusado():
    with pytest.raises(PosicaoInvalida, match="motivo de fechamento"):
        manage.close_posicao(1, motivo="virou_po")
