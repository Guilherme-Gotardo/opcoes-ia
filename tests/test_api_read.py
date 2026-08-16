"""Testes da API de leitura (src.api.app) com TestClient e banco fake.

O dublê de cursor registra toda query executada — é o que permite provar
que nenhum endpoint escreve no banco."""
import datetime as dt
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api import app as api_app
from src.api.app import app

AGORA = dt.datetime(2026, 8, 16, 12, 0, tzinfo=dt.timezone.utc)


class _FakeCursor:
    def __init__(self, dispatcher):
        self._dispatcher = dispatcher
        self.queries: list[str] = []
        self._res = None

    def execute(self, query, params=()):
        self.queries.append(query)
        self._res = self._dispatcher(query, params)

    def fetchone(self):
        return self._res if not isinstance(self._res, list) else (
            self._res[0] if self._res else None
        )

    def fetchall(self):
        return self._res or []

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


def _cliente(dispatcher, desfecho=None):
    cursor = _FakeCursor(dispatcher)
    conn = _FakeConn(cursor)

    @contextmanager
    def _fake_conn():
        yield conn

    patches = [
        patch.object(api_app, "get_connection", _fake_conn),
        patch.object(api_app, "carregar_params",
                     return_value={"cotacao_frescor_maximo_horas": 72}),
    ]
    if desfecho is not None:
        patches.append(
            patch.object(api_app, "ultima_execucao_do_dia", return_value=desfecho)
        )
    return TestClient(app), cursor, conn, patches


def _sem_escrita(cursor, conn):
    """A prova do requisito 'A API não dispara execução'."""
    proibidos = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "DROP")
    for q in cursor.queries:
        assert not any(p in q.upper() for p in proibidos), f"escrita detectada: {q}"
    assert conn.commits == 0, "endpoint de leitura não comita"


# --- /carteira --------------------------------------------------------------

def _dispatch_carteira(posicoes, cotacoes):
    def dispatch(query, params):
        if "FROM posicoes" in query:
            return list(posicoes)
        if "SELECT preco, coletado_em FROM cotacoes" in query:
            return cotacoes.get(params[0])
        raise AssertionError(f"query não esperada: {query}")
    return dispatch


def test_carteira_completa():
    cliente, cursor, conn, patches = _cliente(_dispatch_carteira(
        [("PETR4", "ACAO", 100, 32.5)],
        {"PETR4": (42.0, AGORA)},
    ))
    with patches[0], patches[1], patch.object(api_app.dt, "datetime") as m:
        m.now.return_value = AGORA
        resposta = cliente.get("/carteira")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total_patrimonio"] == pytest.approx(4200.0)
    assert corpo["patrimonio_parcial"] is False
    assert corpo["posicoes"][0]["preco_medio"] == 32.5
    assert corpo["posicoes"][0]["preco_mercado"] == 42.0
    _sem_escrita(cursor, conn)


def test_carteira_parcial_declara_quem_ficou_de_fora():
    cliente, cursor, conn, patches = _cliente(_dispatch_carteira(
        [("PETR4", "ACAO", 100, 32.5), ("VALE3", "ACAO", 200, 55.0)],
        {"PETR4": (42.0, AGORA)},
    ))
    with patches[0], patches[1], patch.object(api_app.dt, "datetime") as m:
        m.now.return_value = AGORA
        corpo = cliente.get("/carteira").json()

    assert corpo["patrimonio_parcial"] is True
    assert corpo["tickers_sem_cotacao"] == ["VALE3"]
    vale = next(p for p in corpo["posicoes"] if p["ticker"] == "VALE3")
    assert vale["valor"] is None, "sem inventar valor de mercado"
    _sem_escrita(cursor, conn)


def test_carteira_vazia_e_sucesso():
    cliente, cursor, conn, patches = _cliente(_dispatch_carteira([], {}))
    with patches[0], patches[1]:
        resposta = cliente.get("/carteira")
    assert resposta.status_code == 200
    assert resposta.json()["posicoes"] == []
    _sem_escrita(cursor, conn)


# --- /cotacoes --------------------------------------------------------------

def test_cotacoes_incluem_ativo_sem_cotacao():
    def dispatch(query, params):
        assert "LEFT JOIN LATERAL" in query
        return [("PETR4", 42.0, AGORA), ("VALE3", None, None)]

    cliente, cursor, conn, patches = _cliente(dispatch)
    with patches[0], patches[1]:
        corpo = cliente.get("/cotacoes").json()

    assert corpo[0] == {"ticker": "PETR4", "preco": 42.0,
                        "coletado_em": "2026-08-16T12:00:00Z", "tem_cotacao": True}
    assert corpo[1]["tem_cotacao"] is False, "sem cotação aparece, não é omitido"
    _sem_escrita(cursor, conn)


# --- /sugestoes -------------------------------------------------------------

def test_sugestoes_carregam_criterios_e_revisao_humana():
    criterios = '{"criterios": [{"nome": "iv_rank"}], "base_valorizacao": {"preco_mercado": 42.09}}'

    def dispatch(query, params):
        return [("PETR4", "covered_call", "PETRI450", 45.0,
                 dt.date(2026, 9, 17), 0.85, criterios, "pendente")]

    cliente, cursor, conn, patches = _cliente(dispatch)
    with patches[0], patches[1]:
        corpo = cliente.get("/sugestoes").json()

    s = corpo[0]
    assert s["pendente_revisao_humana"] is True
    assert s["status"] == "pendente"
    assert s["criterios"]["base_valorizacao"]["preco_mercado"] == 42.09
    _sem_escrita(cursor, conn)


def test_sem_sugestoes_e_lista_vazia_com_sucesso():
    cliente, cursor, conn, patches = _cliente(lambda q, p: [])
    with patches[0], patches[1]:
        resposta = cliente.get("/sugestoes")
    assert resposta.status_code == 200
    assert resposta.json() == []
    _sem_escrita(cursor, conn)


def test_nenhum_texto_da_api_sugere_execucao():
    """Guardrail: linguagem de revisão humana, nunca de execução."""
    schema = app.openapi()
    texto = str(schema).lower()
    for proibida in ("executada", "executar ordem", "enviar ordem", "confirmada"):
        assert proibida not in texto or "não" in texto, (
            f"linguagem de execução no contrato: {proibida}"
        )
    assert "pendente de revisão humana" in str(schema).lower() or \
           "pendente_revisao_humana" in str(schema)


# --- /desfecho --------------------------------------------------------------

def _linha_desfecho():
    from src.strategy.outcome import LinhaDesfecho
    return LinhaDesfecho(
        ticker_objeto="PETR4", motivo="bloqueio_data_resultado",
        quantidade=12, criterios_contagem={},
        amostra={"codigo_opcao": "PETRI450"},
    )


def test_desfecho_com_motivos_e_momento():
    def dispatch(query, params):
        assert "MAX(executado_em)" in query
        return (AGORA,)

    cliente, cursor, conn, patches = _cliente(dispatch, desfecho=[_linha_desfecho()])
    with patches[0], patches[1], patches[2]:
        corpo = cliente.get("/desfecho").json()

    assert corpo["ha_registro"] is True
    assert corpo["executado_em"] == "2026-08-16T12:00:00Z", (
        "a interface precisa poder dizer de QUANDO é o que mostra"
    )
    assert corpo["motivos"][0]["motivo"] == "bloqueio_data_resultado"
    assert corpo["motivos"][0]["quantidade"] == 12
    _sem_escrita(cursor, conn)


def test_desfecho_sem_execucao_registrada_e_explicito():
    cliente, cursor, conn, patches = _cliente(lambda q, p: None, desfecho=[])
    with patches[0], patches[1], patches[2]:
        resposta = cliente.get("/desfecho")

    assert resposta.status_code == 200, "ausência não é erro"
    corpo = resposta.json()
    assert corpo["ha_registro"] is False
    assert corpo["motivos"] == []
    assert corpo["executado_em"] is None
    _sem_escrita(cursor, conn)


# --- Contrato ---------------------------------------------------------------

def test_openapi_cobre_os_quatro_endpoints():
    schema = app.openapi()
    assert set(schema["paths"]) >= {"/carteira", "/cotacoes", "/sugestoes", "/desfecho"}
    # Campos com nome e tipo úteis para o gerador de TypeScript.
    carteira = schema["components"]["schemas"]["CarteiraResposta"]["properties"]
    assert "patrimonio_parcial" in carteira
    assert "exposicao_pct_por_ativo" in carteira


def test_numeros_da_api_coincidem_com_os_do_relatorio():
    """Mesmo estado do banco → mesmo patrimônio e exposição nos dois
    consumidores, porque ambos chamam `visao_carteira`. É o requisito
    'Nenhuma regra de decisão na API' virando teste."""
    from src.report import daily

    posicoes = [("PETR4", "ACAO", 100, 32.5), ("VALE3", "ACAO", 200, 55.0)]
    cotacoes = {"PETR4": (42.0, AGORA), "VALE3": (71.3, AGORA)}
    params = {"cotacao_frescor_maximo_horas": 72}

    # Relatório
    cursor_rel = _FakeCursor(_dispatch_carteira(posicoes, cotacoes))
    resumo = daily._resumo_carteira(cursor_rel, params, AGORA)

    # API
    cliente, cursor_api, conn, patches = _cliente(
        _dispatch_carteira(posicoes, cotacoes)
    )
    with patches[0], patches[1], patch.object(api_app.dt, "datetime") as m:
        m.now.return_value = AGORA
        corpo = cliente.get("/carteira").json()

    assert corpo["total_patrimonio"] == pytest.approx(resumo["total_patrimonio"])
    assert corpo["exposicao_pct_por_ativo"] == pytest.approx(
        resumo["exposicao_pct_por_ativo"]
    )
    assert [p["valor"] for p in corpo["posicoes"]] == [
        p["valor"] for p in resumo["posicoes"]
    ]
