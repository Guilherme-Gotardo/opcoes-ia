"""Testes de src.assets.manage — validação sem banco (cursor fake) no
padrão de tests/test_report_daily.py."""
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from src.assets import manage
from src.assets.manage import (
    AtivoInvalido,
    add_ativo,
    ativo_existe,
    list_ativos,
    tickers_cadastrados,
)


class _FakeCursor:
    def __init__(self, retorno=None, colunas=None):
        self.retorno = retorno if retorno is not None else []
        self.description = [type("C", (), {"name": c})() for c in (colunas or [])]
        self.executados = []

    def execute(self, query, params=()):
        self.executados.append((query, params))

    def fetchone(self):
        return self.retorno[0] if self.retorno else None

    def fetchall(self):
        return self.retorno

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


def _patch_conn(cursor):
    conn = _FakeConn(cursor)

    @contextmanager
    def _fake():
        yield conn

    return patch.object(manage, "get_connection", _fake), conn


# --- Cadastro válido -------------------------------------------------------

def test_cadastro_valido_normaliza_ticker_e_grava():
    cur = _FakeCursor()
    ctx, conn = _patch_conn(cur)
    with ctx:
        assert add_ativo(" petr4 ", "Petrobras PN", "acao") == "PETR4"
    assert conn.commits == 1
    _, params = cur.executados[0]
    assert params[:3] == ("PETR4", "Petrobras PN", "acao")


def test_tipo_tem_padrao_acao():
    cur = _FakeCursor()
    ctx, _ = _patch_conn(cur)
    with ctx:
        add_ativo("VALE3", "Vale ON")
    assert cur.executados[0][1][2] == "acao"


def test_recadastro_usa_upsert_e_nao_duplica():
    cur = _FakeCursor()
    ctx, _ = _patch_conn(cur)
    with ctx:
        add_ativo("PETR4", "Petrobras PN — nome corrigido")
    query = cur.executados[0][0]
    assert "ON CONFLICT (ticker) DO UPDATE" in query


def test_recadastro_sem_cnpj_nao_apaga_o_ja_cadastrado():
    """Corrigir o nome não deveria custar o vínculo com a CVM."""
    cur = _FakeCursor()
    ctx, _ = _patch_conn(cur)
    with ctx:
        add_ativo("PETR4", "Petrobras PN")
    assert "COALESCE(EXCLUDED.cnpj_raiz, ativos.cnpj_raiz)" in cur.executados[0][0]


# --- Rejeições -------------------------------------------------------------

@pytest.mark.parametrize("ticker", ["", "   ", None])
def test_ticker_obrigatorio(ticker):
    with pytest.raises(AtivoInvalido, match="ticker é obrigatório"):
        add_ativo(ticker, "Um nome")


@pytest.mark.parametrize("nome", ["", "   ", None])
def test_nome_obrigatorio_e_nunca_derivado_do_ticker(nome):
    with pytest.raises(AtivoInvalido) as exc:
        add_ativo("PETR4", nome)
    assert "não deriva nome" in str(exc.value), (
        "a mensagem precisa dizer por que não preenchemos sozinhos"
    )


def test_tipo_invalido_lista_os_aceitos():
    with pytest.raises(AtivoInvalido) as exc:
        add_ativo("PETR4", "Petrobras PN", "criptomoeda")
    mensagem = str(exc.value)
    assert "criptomoeda" in mensagem
    for tipo in ("acao", "fii", "bdr"):
        assert tipo in mensagem


# --- cnpj_raiz -------------------------------------------------------------

def test_cnpj_aceita_formatado_e_normaliza():
    cur = _FakeCursor()
    ctx, _ = _patch_conn(cur)
    with ctx:
        add_ativo("PETR4", "Petrobras PN", "acao", cnpj_raiz="33.000.167")
    assert cur.executados[0][1][3] == "33000167"


def test_cnpj_ausente_e_aceito():
    cur = _FakeCursor()
    ctx, _ = _patch_conn(cur)
    with ctx:
        add_ativo("PETR4", "Petrobras PN")
    assert cur.executados[0][1][3] is None


@pytest.mark.parametrize("valor", ["3300016", "330001678", "33.000.1"])
def test_cnpj_com_numero_errado_de_digitos_falha(valor):
    """Gravar 7 ou 9 dígitos criaria um identificador que nunca casa com o
    dump da CVM, e o sintoma seria 'esse ativo nunca tem resultado'."""
    with pytest.raises(AtivoInvalido, match="8 dígitos"):
        add_ativo("PETR4", "Petrobras PN", "acao", cnpj_raiz=valor)


# --- Consultas -------------------------------------------------------------

def test_ativo_existe_normaliza_o_ticker():
    cur = _FakeCursor(retorno=[(1,)])
    ctx, _ = _patch_conn(cur)
    with ctx:
        assert ativo_existe(" petr4 ") is True
    assert cur.executados[0][1] == ("PETR4",)


def test_ativo_inexistente():
    cur = _FakeCursor(retorno=[])
    ctx, _ = _patch_conn(cur)
    with ctx:
        assert ativo_existe("XXXX9") is False


def test_tickers_cadastrados_faz_uma_consulta_so():
    cur = _FakeCursor(retorno=[("PETR4",), ("VALE3",)])
    ctx, _ = _patch_conn(cur)
    with ctx:
        assert tickers_cadastrados(["petr4", "VALE3", "XXXX9"]) == {"PETR4", "VALE3"}
    assert len(cur.executados) == 1, "o ETL não pode consultar ticker a ticker"


def test_tickers_cadastrados_com_lista_vazia_nao_consulta():
    cur = _FakeCursor()
    ctx, _ = _patch_conn(cur)
    with ctx:
        assert tickers_cadastrados([]) == set()
    assert cur.executados == []


def test_list_ativos_devolve_dicts():
    cur = _FakeCursor(
        retorno=[("PETR4", "Petrobras PN", "acao", "33000167", None)],
        colunas=["ticker", "nome", "tipo", "cnpj_raiz", "criado_em"],
    )
    ctx, _ = _patch_conn(cur)
    with ctx:
        ativos = list_ativos()
    assert ativos[0]["ticker"] == "PETR4"
    assert ativos[0]["cnpj_raiz"] == "33000167"


# --- CLI -------------------------------------------------------------------

def test_list_vazio_orienta_o_cadastro(capsys):
    cur = _FakeCursor(retorno=[], colunas=["ticker"])
    ctx, _ = _patch_conn(cur)
    with ctx:
        manage.main(["list"])
    saida = capsys.readouterr().out
    assert "Nenhum ativo cadastrado" in saida
    assert "src.assets.manage add" in saida, "saída vazia precisa dizer o que fazer"


def test_list_distingue_quem_tem_cnpj(capsys):
    cur = _FakeCursor(
        retorno=[
            ("PETR4", "Petrobras PN", "acao", "33000167", None),
            ("VALE3", "Vale ON", "acao", None, None),
        ],
        colunas=["ticker", "nome", "tipo", "cnpj_raiz", "criado_em"],
    )
    ctx, _ = _patch_conn(cur)
    with ctx:
        manage.main(["list"])
    saida = capsys.readouterr().out
    assert "33000167" in saida
    assert "sem CNPJ" in saida


def test_cli_entrada_invalida_sai_com_codigo_2(capsys):
    with pytest.raises(SystemExit) as exc:
        manage.main(["add", "PETR4", "", "acao"])
    assert exc.value.code == 2
    assert "erro:" in capsys.readouterr().err
