"""Testes de src.report.daily — geração do relatório diário a partir de um
banco fake (mock de cursor), sem depender de Postgres real."""
import datetime as dt
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from src import report as report_pkg  # noqa: F401 (garante pacote importável)
from src.report import daily


class _FakeCursor:
    def __init__(self, dispatcher):
        self._dispatcher = dispatcher
        self.queries = []
        self._kind = None
        self._value = None

    def execute(self, query, params=()):
        self.queries.append((query, params))
        self._kind, self._value = self._dispatcher(query, params)

    def fetchone(self):
        return self._value

    def fetchall(self):
        return self._value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        pass


def _patched_get_connection(fake_conn):
    @contextmanager
    def _fake():
        yield fake_conn

    return _fake


def _dispatcher(
    posicoes_rows, cotacoes_ultima, opcoes_ultima, sugestoes_rows,
    ticker_objeto_map=None, cotacoes=None, precos_opcao=None,
):
    """`cotacoes`: ticker -> (preco, coletado_em) usado na valorização a
    mercado. `cotacoes_ultima` continua servindo só ao alerta de frescor da
    coleta, que é outra pergunta."""
    ticker_objeto_map = ticker_objeto_map or {}
    cotacoes = cotacoes or {}
    precos_opcao = precos_opcao or {}

    def dispatch(query, params):
        if "FROM posicoes" in query and "SELECT ticker, tipo_ativo" in query:
            return "all", posicoes_rows
        if "SELECT preco, coletado_em FROM cotacoes" in query:
            return "one", cotacoes.get(params[0])
        if "SELECT preco, coletado_em FROM opcoes" in query:
            return "one", precos_opcao.get(params[0])
        if "ticker_objeto FROM opcoes WHERE codigo" in query:
            codigo = params[0]
            valor = ticker_objeto_map.get(codigo)
            return "one", ((valor,) if valor else None)
        if "MAX(coletado_em) FROM cotacoes" in query:
            ticker = params[0]
            return "one", (cotacoes_ultima.get(ticker),)
        if "MAX(coletado_em) FROM opcoes" in query:
            ticker = params[0]
            return "one", (opcoes_ultima.get(ticker),)
        if "FROM sugestoes" in query:
            return "all", sugestoes_rows
        raise AssertionError(f"query não esperada em teste: {query}")

    return dispatch


def _settings_configurado():
    return MagicMock(news_api_key="uma-chave")


def test_relatorio_sem_posicoes_nem_sugestoes(tmp_path):
    fake_conn = _FakeConnection(_FakeCursor(_dispatcher([], {}, {}, [])))
    with patch("src.report.daily.get_connection", _patched_get_connection(fake_conn)), \
         patch("src.report.daily.get_settings", _settings_configurado), \
         patch.object(daily, "REPORTS_DIR", tmp_path):
        caminho = daily.gerar_relatorio(dt.date(2026, 8, 14))

    conteudo = caminho.read_text(encoding="utf-8")
    assert "Nenhuma posição aberta." in conteudo
    assert "Nenhuma sugestão hoje." in conteudo
    assert "Nenhum alerta hoje." in conteudo


def test_alerta_quando_cotacao_desatualizada(tmp_path):
    hoje = dt.date(2026, 8, 14)
    ontem = dt.datetime(2026, 8, 13, 18, 0, tzinfo=dt.timezone.utc)
    posicoes = [("PETR4", "ACAO", 100, 32.5)]
    fake_conn = _FakeConnection(
        _FakeCursor(_dispatcher(
            posicoes, {"PETR4": ontem}, {"PETR4": None}, [],
            cotacoes={"PETR4": (42.0, ontem)},
        ))
    )
    with patch("src.report.daily.get_connection", _patched_get_connection(fake_conn)), \
         patch("src.report.daily.get_settings", _settings_configurado), \
         patch.object(daily, "REPORTS_DIR", tmp_path):
        caminho = daily.gerar_relatorio(hoje)

    conteudo = caminho.read_text(encoding="utf-8")
    assert "PETR4: cotação desatualizada" in conteudo
    assert "PETR4: nenhum dado de opções coletado ainda." in conteudo


def test_alerta_news_nao_configurado(tmp_path):
    fake_conn = _FakeConnection(_FakeCursor(_dispatcher([], {}, {}, [])))
    settings_sem_chave = MagicMock(news_api_key="")
    with patch("src.report.daily.get_connection", _patched_get_connection(fake_conn)), \
         patch("src.report.daily.get_settings", return_value=settings_sem_chave), \
         patch.object(daily, "REPORTS_DIR", tmp_path):
        caminho = daily.gerar_relatorio(dt.date(2026, 8, 14))

    assert "Notícias: coleta não configurada" in caminho.read_text(encoding="utf-8")


def test_sugestao_inclui_texto_de_revisao_humana(tmp_path):
    sugestoes_rows = [
        (
            "PETR4", "covered_call", "PETRJ380", 38.5, dt.date(2026, 9, 21), 0.85,
            '{"criterios": [{"nome": "iv_rank", "detalhe": "61 (mínimo 50)", "aprovado": true}]}',
            "pendente",
        )
    ]
    fake_conn = _FakeConnection(_FakeCursor(_dispatcher([], {}, {}, sugestoes_rows)))
    with patch("src.report.daily.get_connection", _patched_get_connection(fake_conn)), \
         patch("src.report.daily.get_settings", _settings_configurado), \
         patch.object(daily, "REPORTS_DIR", tmp_path):
        caminho = daily.gerar_relatorio(dt.date(2026, 8, 14))

    conteudo = caminho.read_text(encoding="utf-8")
    assert "PETRJ380" in conteudo
    assert "pendente de revisão humana" in conteudo.lower()
    assert "iv_rank" in conteudo


def test_dois_dias_geram_dois_arquivos_distintos(tmp_path):
    fake_conn = _FakeConnection(_FakeCursor(_dispatcher([], {}, {}, [])))
    with patch("src.report.daily.get_connection", _patched_get_connection(fake_conn)), \
         patch("src.report.daily.get_settings", _settings_configurado), \
         patch.object(daily, "REPORTS_DIR", tmp_path):
        caminho1 = daily.gerar_relatorio(dt.date(2026, 8, 13))
        caminho2 = daily.gerar_relatorio(dt.date(2026, 8, 14))

    assert caminho1 != caminho2
    assert caminho1.exists() and caminho2.exists()


# --- Valorização a preço de mercado ----------------------------------------

def _relatorio_com(tmp_path, data, posicoes, cotacoes, **kwargs):
    fake_conn = _FakeConnection(_FakeCursor(_dispatcher(
        posicoes, {}, {}, [], cotacoes=cotacoes, **kwargs
    )))
    with patch("src.report.daily.get_connection", _patched_get_connection(fake_conn)), \
         patch("src.report.daily.get_settings", _settings_configurado), \
         patch.object(daily, "REPORTS_DIR", tmp_path):
        return daily.gerar_relatorio(data).read_text(encoding="utf-8")


def test_patrimonio_usa_mercado_e_nao_preco_medio(tmp_path):
    """O caso que motivou a change: 100 PETR4 a custo 32.50 valem R$ 4.200 a
    mercado (42.00), não R$ 3.250."""
    data = dt.date(2026, 8, 14)
    coletado = dt.datetime(2026, 8, 14, 20, 0, tzinfo=dt.timezone.utc)
    conteudo = _relatorio_com(
        tmp_path, data,
        posicoes=[("PETR4", "ACAO", 100, 32.5)],
        cotacoes={"PETR4": (42.0, coletado)},
    )

    assert "Patrimônio total (a preço de mercado): R$ 4200.00" in conteudo
    assert "3250.00" not in conteudo, "custo não pode aparecer como patrimônio"
    assert "Patrimônio parcial" not in conteudo


def test_preco_medio_continua_visivel_ao_lado_do_mercado(tmp_path):
    data = dt.date(2026, 8, 14)
    coletado = dt.datetime(2026, 8, 14, 20, 0, tzinfo=dt.timezone.utc)
    conteudo = _relatorio_com(
        tmp_path, data,
        posicoes=[("PETR4", "ACAO", 100, 32.5)],
        cotacoes={"PETR4": (42.0, coletado)},
    )

    assert "Preço médio (custo)" in conteudo
    assert "Preço de mercado" in conteudo
    assert "| 32.5000 | 42.0000 | 2026-08-14 | 4200.00 |" in conteudo


def test_posicao_sem_cotacao_e_sinalizada_sem_valor_estimado(tmp_path):
    data = dt.date(2026, 8, 14)
    coletado = dt.datetime(2026, 8, 14, 20, 0, tzinfo=dt.timezone.utc)
    conteudo = _relatorio_com(
        tmp_path, data,
        posicoes=[("PETR4", "ACAO", 100, 32.5), ("VALE3", "ACAO", 100, 55.0)],
        cotacoes={"PETR4": (42.0, coletado)},
    )

    assert "VALE3: nenhuma cotação registrada" in conteudo
    assert "não valorizada a mercado" in conteudo
    assert "5500.00" not in conteudo, "não pode valorizar VALE3 pelo custo"
    assert "Patrimônio total (a preço de mercado): R$ 4200.00" in conteudo


def test_patrimonio_parcial_e_declarado_com_quem_ficou_de_fora(tmp_path):
    data = dt.date(2026, 8, 14)
    coletado = dt.datetime(2026, 8, 14, 20, 0, tzinfo=dt.timezone.utc)
    conteudo = _relatorio_com(
        tmp_path, data,
        posicoes=[("PETR4", "ACAO", 100, 32.5), ("VALE3", "ACAO", 100, 55.0)],
        cotacoes={"PETR4": (42.0, coletado)},
    )

    assert "Patrimônio parcial" in conteudo
    assert "não cobre VALE3" in conteudo


def test_cotacao_fora_da_janela_informa_a_idade(tmp_path):
    data = dt.date(2026, 8, 14)
    velha = dt.datetime(2026, 8, 5, 20, 0, tzinfo=dt.timezone.utc)
    conteudo = _relatorio_com(
        tmp_path, data,
        posicoes=[("PETR4", "ACAO", 100, 32.5)],
        cotacoes={"PETR4": (42.0, velha)},
    )

    assert "fora da janela" in conteudo
    assert "h atrás" in conteudo
    assert "4200.00" not in conteudo, "cotação velha não pode virar valor"


def test_exposicao_percentual_sai_sobre_o_patrimonio_a_mercado(tmp_path):
    data = dt.date(2026, 8, 14)
    coletado = dt.datetime(2026, 8, 14, 20, 0, tzinfo=dt.timezone.utc)
    conteudo = _relatorio_com(
        tmp_path, data,
        posicoes=[("PETR4", "ACAO", 100, 32.5), ("VALE3", "ACAO", 100, 20.0)],
        cotacoes={
            "PETR4": (30.0, coletado),   # R$ 3.000
            "VALE3": (10.0, coletado),   # R$ 1.000
        },
    )

    assert "sobre o patrimônio a mercado" in conteudo
    assert "- PETR4: 75.00% do patrimônio" in conteudo
    assert "- VALE3: 25.00% do patrimônio" in conteudo


def test_opcao_e_valorizada_mas_fica_fora_do_patrimonio(tmp_path):
    data = dt.date(2026, 8, 14)
    coletado = dt.datetime(2026, 8, 14, 20, 0, tzinfo=dt.timezone.utc)
    conteudo = _relatorio_com(
        tmp_path, data,
        posicoes=[("PETR4", "ACAO", 100, 32.5), ("PETRI280", "OPCAO", -1, 0.95)],
        cotacoes={"PETR4": (42.0, coletado)},
        precos_opcao={"PETRI280": (1.10, coletado)},
        ticker_objeto_map={"PETRI280": "PETR4"},
    )

    assert "Patrimônio total (a preço de mercado): R$ 4200.00" in conteudo, (
        "o valor da opção não pode somar ao patrimônio"
    )
    assert "Só posições em ação entram no patrimônio" in conteudo
    assert "| PETRI280 | OPCAO | -1 | 0.9500 | 1.1000 |" in conteudo


# --- Seção de avaliações bloqueadas por data de resultado -------------------

def _bloqueio(ticker="PETR4", codigo="PETRI280"):
    """Um ResultadoAvaliacao bloqueado, como `executar_avaliacao_carteira`
    devolve quando os critérios de mercado passam mas falta a data."""
    from src.strategy.covered import (
        CriterioAvaliado,
        EstadoCriterio,
        ResultadoAvaliacao,
    )
    return ResultadoAvaliacao(
        ticker_objeto=ticker, codigo_opcao=codigo, tipo_operacao="covered_call",
        elegivel=False, bloqueado_por_resultado=True,
        motivo_nao_elegivel="não verificável(is): dias_para_resultado",
        strike=28.0, vencimento="2026-09-18", premio_estimado=0.95,
        criterios=[
            CriterioAvaliado("iv_rank", 62.0, "62.0 (mínimo 50)", EstadoCriterio.APROVADO),
            CriterioAvaliado("dias_para_resultado", None,
                             "data de resultado não verificável (política: bloquear)",
                             EstadoCriterio.INDISPONIVEL),
        ],
    )


def test_bloqueio_por_resultado_aparece_com_criterios_e_acao(tmp_path):
    linhas: list[str] = []
    daily._renderizar_bloqueios(linhas, [_bloqueio()])
    texto = "\n".join(linhas)

    assert "## Avaliações bloqueadas por data de resultado" in texto
    assert "PETR4 — PETRI280" in texto
    assert "iv_rank: 62.0 (mínimo 50) ✅" in texto, "critérios já verificados ficam visíveis"
    assert "⚠️" in texto, "o critério indisponível não pode virar ❌"
    assert "src.earnings.manage add PETR4" in texto, "precisa dizer como destravar"


def test_sem_bloqueio_a_secao_nao_e_criada(tmp_path):
    linhas: list[str] = []
    daily._renderizar_bloqueios(linhas, [])
    assert linhas == [], "seção vazia não deve ser gerada"


def test_sugestao_sinalizada_exibe_aviso_de_agenda(tmp_path):
    sugestao = {
        "ticker_objeto": "PETR4", "tipo_operacao": "covered_call",
        "codigo_opcao": "PETRI280", "strike": 28.0, "vencimento": "2026-09-18",
        "premio_estimado": 0.95, "status": "pendente",
        "criterios": {
            "criterios": [
                {"nome": "iv_rank", "valor": 62.0, "detalhe": "62 (mínimo 50)",
                 "estado": "aprovado", "aprovado": True},
                {"nome": "dias_para_resultado", "valor": None,
                 "detalhe": "não verificável", "estado": "indisponivel",
                 "aprovado": False},
            ],
            "aviso_resultado": "agenda de resultados NÃO verificada — confirme a data",
        },
    }
    texto = daily._renderizar_markdown(
        dt.date(2026, 8, 15),
        {"posicoes": [], "total_patrimonio": 0, "exposicao_pct_por_ativo": {}},
        [], [sugestao],
    )
    assert "agenda de resultados NÃO verificada" in texto
    assert "Pendente de revisão humana" in texto, "o aviso soma, não substitui"
    assert "dias_para_resultado: não verificável ⚠️" in texto
