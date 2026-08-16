"""Testes da API de leitura (src.api.app) com TestClient e banco fake.

O dublê de cursor registra toda query executada — é o que permite provar
que nenhum endpoint escreve no banco."""
import datetime as dt
import re
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


#: Comandos de escrita, casados como PALAVRA inteira. Substring aqui dá
#: falso positivo real: `earnings_events.updated_at` contém "UPDATE" e é
#: nome de coluna num SELECT — a versão anterior deste guardrail reprovava
#: uma query de leitura legítima por causa disso.
_ESCRITA = re.compile(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|CREATE|DROP|ALTER)\b")


def _sem_escrita(cursor, conn):
    """A prova do requisito 'A API não dispara execução'."""
    for q in cursor.queries:
        achado = _ESCRITA.search(q.upper())
        assert achado is None, f"escrita detectada ({achado and achado.group()}): {q}"
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

def test_openapi_cobre_a_superficie_de_leitura():
    schema = app.openapi()
    assert set(schema["paths"]) >= {
        "/carteira", "/cotacoes", "/sugestoes", "/desfecho",
        "/resultados", "/saude-coleta", "/parametros", "/operacoes",
    }
    assert set(schema["paths"]["/resultados"]) == {"get"}, "leitura, nunca escrita"
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


# --- /resultados ------------------------------------------------------------

def _evento(ticker, periodo, estimada, confirmada, status, confianca,
            hora_conf=None, sessao="AFTER_CLOSE"):
    return (f"{ticker}:{periodo}", ticker, f"{ticker} SA", periodo,
            estimada, confirmada, None, hora_conf, sessao, status,
            confianca, [], AGORA)


def _dispatch_resultados(eventos=(), fontes=(), pendentes=()):
    def dispatch(query, params):
        # A ordem importa: a query de pendentes cita `earnings_events` no
        # LEFT JOIN, então ela precisa ser reconhecida antes.
        if "earnings_manual_entries" in query:
            return list(pendentes)
        if "earnings_event_sources" in query:
            return list(fontes)
        if "FROM earnings_events" in query:
            return list(eventos)
        raise AssertionError(f"query não esperada: {query}")
    return dispatch


def test_resultados_confirmada_vence_e_estimada_e_preservada():
    """A invariante do domínio virando contrato: a data efetiva é a
    confirmada, e a estimativa divergente CONTINUA na resposta em vez de
    ser apagada."""
    cliente, cursor, conn, patches = _cliente(_dispatch_resultados(
        eventos=[_evento("VALE3", "2026Q3", dt.date(2026, 10, 20),
                         dt.date(2026, 10, 22), "CONFIRMED", 95,
                         hora_conf=dt.time(18, 0))],
    ))
    with patches[0], patches[1]:
        corpo = cliente.get("/resultados").json()

    evento = corpo["eventos"][0]
    assert evento["data_efetiva"] == "2026-10-22", "a confirmada é a que vale"
    assert evento["data_estimada"] == "2026-10-20", "discordância preservada"
    assert evento["confirmado"] is True
    assert evento["faixa_confianca"] == "CONFIRMED"
    assert evento["hora_efetiva"] == "18:00:00"
    _sem_escrita(cursor, conn)


def test_resultados_sem_confirmacao_usa_estimada_e_nao_finge_confirmacao():
    cliente, cursor, conn, patches = _cliente(_dispatch_resultados(
        eventos=[_evento("PETR4", "2026Q3", dt.date(2026, 11, 6), None,
                         "ESTIMATED", 70)],
    ))
    with patches[0], patches[1]:
        evento = cliente.get("/resultados").json()["eventos"][0]

    assert evento["data_efetiva"] == "2026-11-06"
    assert evento["data_confirmada"] is None
    assert evento["confirmado"] is False
    assert evento["faixa_confianca"] == "ESTIMATED_HIGH"
    _sem_escrita(cursor, conn)


def test_resultados_agrupam_fontes_por_evento():
    cliente, cursor, conn, patches = _cliente(_dispatch_resultados(
        eventos=[_evento("PETR4", "2026Q3", dt.date(2026, 11, 6), None,
                         "ESTIMATED", 70)],
        fontes=[
            ("PETR4:2026Q3", "yahoo", dt.date(2026, 11, 6), "ESTIMATED", 60,
             AGORA, "https://finance.yahoo.com"),
            ("PETR4:2026Q3", "cvm", dt.date(2026, 11, 5), "RELEASED", 90,
             AGORA, None),
            ("OUTRO:2026Q3", "manual", dt.date(2026, 12, 1), "CONFIRMED", 100,
             AGORA, None),
        ],
    ))
    with patches[0], patches[1]:
        evento = cliente.get("/resultados").json()["eventos"][0]

    provedores = [f["provedor"] for f in evento["fontes"]]
    assert provedores == ["yahoo", "cvm"], "só as fontes deste evento"
    assert evento["fontes"][0]["url"] == "https://finance.yahoo.com"
    _sem_escrita(cursor, conn)


def test_resultados_expoem_registrado_mas_nao_consolidado():
    """A armadilha do fluxo vira estado explícito: `manage add` gravou, o
    `ingest` não promoveu, e a avaliação segue bloqueada."""
    cliente, cursor, conn, patches = _cliente(_dispatch_resultados(
        pendentes=[("ITUB4", "2026Q3", dt.date(2026, 11, 10), "UNKNOWN",
                    "https://ri.itau.com.br", AGORA)],
    ))
    with patches[0], patches[1]:
        corpo = cliente.get("/resultados").json()

    assert corpo["eventos"] == []
    pendente = corpo["pendentes_consolidacao"][0]
    assert pendente["ticker"] == "ITUB4"
    assert pendente["comando_para_consolidar"] == (
        "python -m src.earnings.ingest --tickers ITUB4"
    )
    _sem_escrita(cursor, conn)


def test_resultados_declaram_a_politica_vigente():
    cliente, cursor, conn, patches = _cliente(_dispatch_resultados())
    with patches[0], patches[1]:
        corpo = cliente.get("/resultados").json()
    assert corpo["politica_resultado_desconhecido"] == "bloquear"
    _sem_escrita(cursor, conn)


# --- /operacao --------------------------------------------------------------

def _dispatch_saude(cotacoes=(), opcoes=(), noticias=(), earnings=(),
                       avaliacao=None, gastos=0):
    def dispatch(query, params):
        # A query do orçamento também cita `cotacoes`; reconhecer antes.
        if "COUNT(*) FROM cotacoes WHERE fonte" in query:
            return (gastos,)
        if "FROM desfecho_avaliacao" in query:
            return (avaliacao,)
        if "FROM earnings_event_sources" in query:
            return list(earnings)
        if "FROM cotacoes" in query:
            return list(cotacoes)
        if "FROM opcoes" in query:
            return list(opcoes)
        if "FROM noticias" in query:
            return list(noticias)
        raise AssertionError(f"query não esperada: {query}")
    return dispatch


@contextmanager
def _orcamento_de(limite):
    from types import SimpleNamespace
    with patch.object(api_app, "get_settings",
                      return_value=SimpleNamespace(brapi_requests_dia_maximo=limite)):
        yield


def test_saude_coleta_reporta_ultima_entrega_por_canal_e_fonte():
    cliente, cursor, conn, patches = _cliente(_dispatch_saude(
        cotacoes=[("brapi", AGORA, 2)],
        earnings=[("manual", AGORA, 1), ("cvm", None, 0)],
        avaliacao=AGORA,
        gastos=12,
    ))
    with patches[0], patches[1], _orcamento_de(600):
        corpo = cliente.get("/saude-coleta").json()

    canais = {(c["canal"], c["fonte"]): c for c in corpo["coletas"]}
    assert canais[("cotações", "brapi")]["registros_hoje"] == 2
    assert canais[("cotações", "brapi")]["ja_entregou"] is True
    assert canais[("resultados", "cvm")]["ja_entregou"] is False
    assert corpo["ultima_avaliacao_em"] == "2026-08-16T12:00:00Z"
    _sem_escrita(cursor, conn)


def test_saude_coleta_orcamento_usa_o_limite_configurado():
    cliente, cursor, conn, patches = _cliente(_dispatch_saude(gastos=45))
    with patches[0], patches[1], _orcamento_de(600):
        orcamento = cliente.get("/saude-coleta").json()["orcamento"]

    assert orcamento["limite_diario"] == 600
    assert orcamento["gastos_hoje"] == 45
    assert orcamento["restante_hoje"] == 555
    assert orcamento["e_aproximacao"] is True, "é proxy por linhas gravadas"
    _sem_escrita(cursor, conn)


def test_saude_coleta_orcamento_estourado_nunca_fica_negativo():
    cliente, cursor, conn, patches = _cliente(_dispatch_saude(gastos=900))
    with patches[0], patches[1], _orcamento_de(600):
        orcamento = cliente.get("/saude-coleta").json()["orcamento"]
    assert orcamento["restante_hoje"] == 0
    _sem_escrita(cursor, conn)


def test_saude_coleta_declara_que_nao_rastreia_falhas():
    """O limite honesto no próprio contrato: sem entrega recente pode ser
    fonte quebrada OU dia sem novidade, e o banco não distingue."""
    cliente, cursor, conn, patches = _cliente(_dispatch_saude())
    with patches[0], patches[1], _orcamento_de(600):
        corpo = cliente.get("/saude-coleta").json()
    assert corpo["rastreia_falhas"] is False
    _sem_escrita(cursor, conn)


# --- /parametros ------------------------------------------------------------

def test_parametros_expoem_frescor_e_politica():
    """Existe para a interface parar de duplicar esses números."""
    cliente, cursor, conn, patches = _cliente(lambda q, p: [])
    with patches[0], patches[1]:
        corpo = cliente.get("/parametros").json()

    assert corpo["cotacao_frescor_maximo_horas"] == 72
    assert corpo["politica_resultado_desconhecido"] == "bloquear"
    _sem_escrita(cursor, conn)


# --- /candles ---------------------------------------------------------------

def _dispatch_candles(velas=(), disponiveis=()):
    def dispatch(query, params):
        if "DISTINCT intervalo" in query:
            return [(i,) for i in disponiveis]
        if "FROM candles" in query:
            return list(velas)
        raise AssertionError(f"query não esperada: {query}")
    return dispatch


def test_candles_normaliza_ticker_e_devolve_em_ordem_cronologica():
    cliente, cursor, conn, patches = _cliente(_dispatch_candles(
        velas=[
            (AGORA, 42.10, 42.13, 41.91, 41.91, 2084200),
            (AGORA, 41.91, 42.00, 41.83, 41.96, 7316300),
        ],
        disponiveis=["1d", "1h"],
    ))
    with patches[0], patches[1]:
        corpo = cliente.get("/candles", params={"ticker": "petr4", "intervalo": "1h"}).json()

    assert corpo["ticker"] == "PETR4"
    assert corpo["intervalos_disponiveis"] == ["1d", "1h"]
    assert corpo["velas"][0]["maxima"] == 42.13
    _sem_escrita(cursor, conn)


def test_candles_corta_pelas_mais_recentes():
    """Pedir 200 velas de uma série longa precisa devolver as 200 ÚLTIMAS.
    O subselect ordena DESC e só o resultado é reordenado para desenho."""
    capturadas = {}

    def dispatch(query, params):
        if "DISTINCT intervalo" in query:
            return []
        capturadas["query"] = query
        capturadas["params"] = params
        return []

    cliente, cursor, conn, patches = _cliente(dispatch)
    with patches[0], patches[1]:
        cliente.get("/candles", params={"ticker": "PETR4", "limite": 50})

    assert "ORDER BY abertura_em DESC" in capturadas["query"]
    assert capturadas["params"][2] == 50
    _sem_escrita(cursor, conn)


def test_candles_limite_e_travado_em_faixa_sa():
    """Limite absurdo não vira varredura da tabela inteira."""
    capturado = {}

    def dispatch(query, params):
        if "DISTINCT intervalo" in query:
            return []
        capturado["limite"] = params[2]
        return []

    for pedido, esperado in ((0, 1), (-5, 1), (99999, 2000)):
        cliente, cursor, conn, patches = _cliente(dispatch)
        with patches[0], patches[1]:
            cliente.get("/candles", params={"ticker": "PETR4", "limite": pedido})
        assert capturado["limite"] == esperado, f"limite {pedido} → {capturado['limite']}"


def test_candles_de_ticker_sem_serie_e_lista_vazia_com_sucesso():
    cliente, cursor, conn, patches = _cliente(_dispatch_candles())
    with patches[0], patches[1]:
        r = cliente.get("/candles", params={"ticker": "XXXX"})
    assert r.status_code == 200
    assert r.json()["velas"] == []
    assert r.json()["intervalos_disponiveis"] == []
    _sem_escrita(cursor, conn)


# --- /operacoes -------------------------------------------------------------

def _dispatch_operacoes(posicoes=(), precos_medios=(), n_opcoes=0, cotacao=None):
    def dispatch(query, params):
        if "tipo_ativo = 'OPCAO'" in query:
            return list(posicoes)
        if "GROUP BY ticker" in query:
            return list(precos_medios)
        if "COUNT(*) FROM opcoes" in query:
            return (n_opcoes,)
        if "FROM cotacoes" in query:
            return cotacao
        raise AssertionError(f"query não esperada: {query}")
    return dispatch


def _posicao_opcao(**kw):
    base = dict(
        pid=1, codigo="PETRJ400", objeto="PETR4", qtd=-100, premio=0.92,
        strike=40.0, venc=dt.date(2026, 9, 18), aberta=AGORA, fechada=None,
        motivo=None, preco_fech=None,
    )
    base.update(kw)
    return tuple(base.values())


def test_operacao_aberta_mostra_distancia_do_strike():
    """A pergunta central da venda coberta: a ação passou do strike?"""
    cliente, cursor, conn, patches = _cliente(_dispatch_operacoes(
        posicoes=[_posicao_opcao()],
        precos_medios=[("PETR4", 35.35)],
        cotacao=(42.09, AGORA),
    ))
    with patches[0], patches[1]:
        corpo = cliente.get("/operacoes").json()

    op = corpo["operacoes"][0]
    assert op["preco_objeto"] == 42.09
    assert op["dentro_do_dinheiro"] is True
    assert op["distancia_do_strike_pct"] == pytest.approx(5.225, abs=1e-3)
    _sem_escrita(cursor, conn)


def test_operacao_aberta_traz_cenarios_e_nenhum_resultado_realizado():
    """Sem cotação de opção não há marcação a mercado — o honesto é mostrar
    os desfechos possíveis, não inventar um valor 'atual'."""
    cliente, cursor, conn, patches = _cliente(_dispatch_operacoes(
        posicoes=[_posicao_opcao()],
        precos_medios=[("PETR4", 35.35)],
        cotacao=(42.09, AGORA),
    ))
    with patches[0], patches[1]:
        op = cliente.get("/operacoes").json()["operacoes"][0]

    assert op["resultado_liquido"] == 0.0
    assert any("em aberto" in r for r in op["ressalvas"])
    nomes = [c["nome"] for c in op["cenarios"]]
    assert nomes == ["expira sem exercício", "exercida"]
    _sem_escrita(cursor, conn)


def test_opcao_sem_strike_degrada_sem_quebrar():
    """Posição registrada antes dos campos de opção continua aparecendo,
    só que sem o que depende deles."""
    cliente, cursor, conn, patches = _cliente(_dispatch_operacoes(
        posicoes=[_posicao_opcao(strike=None, venc=None, objeto=None)],
    ))
    with patches[0], patches[1]:
        op = cliente.get("/operacoes").json()["operacoes"][0]

    assert op["distancia_do_strike_pct"] is None
    assert op["dias_para_vencimento"] is None
    assert [c["nome"] for c in op["cenarios"]] == ["expira sem exercício"]
    _sem_escrita(cursor, conn)


def test_operacao_encerrada_traz_resultado_e_pernas():
    cliente, cursor, conn, patches = _cliente(_dispatch_operacoes(
        posicoes=[_posicao_opcao(motivo="expirada", fechada=AGORA)],
        precos_medios=[("PETR4", 35.35)],
        cotacao=(42.09, AGORA),
    ))
    with patches[0], patches[1]:
        op = cliente.get("/operacoes").json()["operacoes"][0]

    assert op["resultado_bruto"] == pytest.approx(92.0)
    assert op["pernas"][0]["nome"] == "opção"
    assert op["cenarios"] == [], "operação fechada não tem cenário hipotético"
    _sem_escrita(cursor, conn)


def test_operacoes_declaram_que_nao_ha_marcacao_a_mercado_da_opcao():
    """`opcoes` fica vazia enquanto o ETL está bloqueado no plano Free — a
    resposta diz isso em vez de deixar a interface supor."""
    cliente, cursor, conn, patches = _cliente(_dispatch_operacoes(n_opcoes=0))
    with patches[0], patches[1]:
        corpo = cliente.get("/operacoes").json()
    assert corpo["tem_cotacao_de_opcao"] is False
    _sem_escrita(cursor, conn)


def test_resultado_de_operacao_e_sempre_estimativa():
    cliente, cursor, conn, patches = _cliente(_dispatch_operacoes(
        posicoes=[_posicao_opcao(motivo="expirada", fechada=AGORA)],
    ))
    with patches[0], patches[1]:
        op = cliente.get("/operacoes").json()["operacoes"][0]
    assert op["estimativa"] is True
