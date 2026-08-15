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


def _dispatcher(posicoes_rows, cotacoes_ultima, opcoes_ultima, sugestoes_rows, ticker_objeto_map=None):
    ticker_objeto_map = ticker_objeto_map or {}

    def dispatch(query, params):
        if "FROM posicoes" in query and "SELECT ticker, tipo_ativo" in query:
            return "all", posicoes_rows
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
    ontem = dt.datetime(2026, 8, 13, 18, 0)
    posicoes = [("PETR4", "ACAO", 100, 32.5)]
    fake_conn = _FakeConnection(
        _FakeCursor(_dispatcher(posicoes, {"PETR4": ontem}, {"PETR4": None}, []))
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
