"""Testes de src.market.valuation — valorização a mercado e exposição
descoberta, com cursor fake (sem Postgres)."""
import datetime as dt

import pytest

from src.market.valuation import (
    acoes_em_carteira,
    cobertura_disponivel_em_contratos,
    cobertura_em_contratos_por_caixa,
    cotacao_vigente,
    notional_descoberto,
    notional_descoberto_em_carteira,
    patrimonio_a_mercado,
)

PARAMS = {"cotacao_frescor_maximo_horas": 72}
AGORA = dt.datetime(2026, 8, 15, 12, 0, tzinfo=dt.timezone.utc)


class _FakeCursor:
    """Cursor que responde por formato de query, no estilo do fake já usado
    em `tests/test_report_daily.py`."""

    def __init__(self, cotacoes=None, posicoes_acao=None, opcoes_vendidas=None):
        #: ticker -> (preco, coletado_em)
        self.cotacoes = cotacoes or {}
        #: lista de (ticker, quantidade)
        self.posicoes_acao = posicoes_acao or []
        #: lista de (quantidade, strike, tipo, ticker_objeto)
        self.opcoes_vendidas = opcoes_vendidas or []
        self._resultado = None

    def execute(self, query, params=()):
        if "FROM cotacoes" in query:
            self._resultado = self.cotacoes.get(params[0])
        elif "SELECT ticker, quantidade FROM posicoes" in query:
            self._resultado = list(self.posicoes_acao)
        elif "COALESCE(SUM(quantidade), 0)" in query:
            total = sum(q for t, q in self.posicoes_acao if t == params[0])
            self._resultado = (total,)
        elif "o.tipo = 'CALL'" in query:
            self._resultado = [
                (q, s) for q, s, tipo, obj in self.opcoes_vendidas
                if tipo == "CALL" and obj == params[0]
            ]
        elif "o.tipo = 'PUT'" in query:
            self._resultado = [
                (q, s) for q, s, tipo, obj in self.opcoes_vendidas
                if tipo == "PUT" and obj == params[0]
            ]
        else:
            raise AssertionError(f"query não esperada em teste: {query}")

    def fetchone(self):
        return self._resultado

    def fetchall(self):
        return self._resultado


# A validação da janela de frescor mora em `tests/test_params.py`, junto das
# demais validações de `params.yaml`.

# --- Cotação vigente -------------------------------------------------------

def test_cotacao_fresca_e_utilizavel():
    cur = _FakeCursor(cotacoes={
        "PETR4": (42.0, AGORA - dt.timedelta(hours=2)),
    })
    cotacao = cotacao_vigente(cur, "PETR4", PARAMS, AGORA)
    assert cotacao.utilizavel is True
    assert cotacao.preco == 42.0
    assert cotacao.idade_horas == pytest.approx(2.0)


def test_cotacao_fora_da_janela_nao_e_utilizavel_e_informa_a_idade():
    cur = _FakeCursor(cotacoes={
        "PETR4": (42.0, AGORA - dt.timedelta(hours=100)),
    })
    cotacao = cotacao_vigente(cur, "PETR4", PARAMS, AGORA)
    assert cotacao.utilizavel is False
    assert cotacao.preco is None, "preço velho não pode vazar como valor"
    assert "100.0h" in cotacao.motivo
    assert "PETR4" in cotacao.motivo


def test_cotacao_de_pregao_anterior_dentro_da_janela_serve():
    """Sexta-fechamento → segunda-abertura não é dado velho, é ausência de
    pregão. A janela de 72h cobre isso de propósito."""
    cur = _FakeCursor(cotacoes={
        "PETR4": (42.0, AGORA - dt.timedelta(hours=66)),
    })
    assert cotacao_vigente(cur, "PETR4", PARAMS, AGORA).utilizavel is True


def test_ticker_sem_nenhuma_cotacao():
    cotacao = cotacao_vigente(_FakeCursor(), "VALE3", PARAMS, AGORA)
    assert cotacao.utilizavel is False
    assert cotacao.coletado_em is None
    assert "nenhuma cotação registrada" in cotacao.motivo


# --- Patrimônio a mercado --------------------------------------------------

def test_patrimonio_soma_a_mercado_nao_a_custo():
    cur = _FakeCursor(
        cotacoes={"PETR4": (42.0, AGORA), "VALE3": (60.0, AGORA)},
        posicoes_acao=[("PETR4", 100), ("VALE3", 100)],
    )
    patrimonio = patrimonio_a_mercado(cur, PARAMS, AGORA)
    assert patrimonio.total == pytest.approx(10200.0)
    assert patrimonio.parcial is False


def test_patrimonio_parcial_lista_quem_ficou_de_fora():
    cur = _FakeCursor(
        cotacoes={"PETR4": (42.0, AGORA)},
        posicoes_acao=[("PETR4", 100), ("VALE3", 100)],
    )
    patrimonio = patrimonio_a_mercado(cur, PARAMS, AGORA)
    assert patrimonio.total == pytest.approx(4200.0)
    assert patrimonio.parcial is True
    assert patrimonio.tickers_sem_cotacao == ["VALE3"]


# --- Cobertura e notional descoberto ---------------------------------------

def test_cem_acoes_cobrem_um_contrato():
    cur = _FakeCursor(posicoes_acao=[("PETR4", 100)])
    assert cobertura_disponivel_em_contratos(cur, "PETR4") == 1
    assert acoes_em_carteira(cur, "PETR4") == 100


def test_lote_ja_comprometido_por_call_vendida_nao_cobre_de_novo():
    """Duas calls sucessivas sobre o mesmo lote de 100 ações: a segunda é
    descoberta."""
    cur = _FakeCursor(
        posicoes_acao=[("PETR4", 100)],
        opcoes_vendidas=[(-1, 45.0, "CALL", "PETR4")],
    )
    assert cobertura_disponivel_em_contratos(cur, "PETR4") == 0


def test_covered_call_totalmente_coberta_tem_notional_descoberto_zero():
    assert notional_descoberto(contratos=1, strike=45.0, cobertura_em_contratos=1) == 0.0


def test_parte_descoberta_conta_integralmente():
    # 3 contratos, cobertura para 1 → 2 descobertos.
    assert notional_descoberto(3, 45.0, 1) == pytest.approx(9000.0)


def test_cobertura_maior_que_a_operacao_nao_gera_credito():
    assert notional_descoberto(1, 45.0, 5) == 0.0


def test_cobertura_por_caixa_para_covered_put():
    assert cobertura_em_contratos_por_caixa(9000.0, 36.0) == 2
    assert cobertura_em_contratos_por_caixa(100.0, 36.0) == 0
    assert cobertura_em_contratos_por_caixa(None, 36.0) == 0


def test_carteira_sem_opcao_vendida_nao_tem_exposicao_descoberta():
    cur = _FakeCursor(posicoes_acao=[("PETR4", 100)])
    assert notional_descoberto_em_carteira(cur, "PETR4") == 0.0


def test_call_vendida_coberta_pelas_acoes_nao_conta():
    cur = _FakeCursor(
        posicoes_acao=[("PETR4", 100)],
        opcoes_vendidas=[(-1, 45.0, "CALL", "PETR4")],
    )
    assert notional_descoberto_em_carteira(cur, "PETR4") == 0.0


def test_call_vendida_alem_da_cobertura_conta_o_excedente():
    """Cobertura para 1 contrato e 2 vendidos: as ações cobrem o strike mais
    baixo primeiro, deixando descoberto o de maior notional."""
    cur = _FakeCursor(
        posicoes_acao=[("PETR4", 100)],
        opcoes_vendidas=[
            (-1, 40.0, "CALL", "PETR4"),
            (-1, 50.0, "CALL", "PETR4"),
        ],
    )
    assert notional_descoberto_em_carteira(cur, "PETR4") == pytest.approx(5000.0)


def test_put_vendida_conta_integralmente_sem_fonte_de_garantia():
    cur = _FakeCursor(
        posicoes_acao=[("PETR4", 100)],
        opcoes_vendidas=[(-1, 36.0, "PUT", "PETR4")],
    )
    assert notional_descoberto_em_carteira(cur, "PETR4") == pytest.approx(3600.0)


# --- Visão de carteira (extraída de report/daily.py) ------------------------

class _CursorCarteira:
    """Dublê para `visao_carteira`: posições, cotações e preços de opção."""

    def __init__(self, posicoes=None, cotacoes=None, precos_opcao=None,
                 ticker_objeto=None):
        self.posicoes = posicoes or []          # (ticker, tipo, qtd, preco_medio)
        self.cotacoes = cotacoes or {}          # ticker -> (preco, coletado_em)
        self.precos_opcao = precos_opcao or {}  # codigo -> (preco, coletado_em)
        self.ticker_objeto = ticker_objeto or {}
        self._res = None

    def execute(self, query, params=()):
        if "FROM posicoes" in query:
            self._res = list(self.posicoes)
        elif "SELECT preco, coletado_em FROM cotacoes" in query:
            self._res = self.cotacoes.get(params[0])
        elif "SELECT preco, coletado_em FROM opcoes" in query:
            self._res = self.precos_opcao.get(params[0])
        elif "ticker_objeto FROM opcoes" in query:
            v = self.ticker_objeto.get(params[0])
            self._res = (v,) if v else None
        else:
            raise AssertionError(f"query não esperada: {query}")

    def fetchone(self):
        return self._res

    def fetchall(self):
        return self._res


def test_visao_carteira_completa():
    from src.market.valuation import visao_carteira
    cur = _CursorCarteira(
        posicoes=[("PETR4", "ACAO", 100, 32.5), ("VALE3", "ACAO", 200, 55.0)],
        cotacoes={"PETR4": (42.0, AGORA), "VALE3": (71.3, AGORA)},
    )
    visao = visao_carteira(cur, PARAMS, AGORA)

    assert visao.total_patrimonio == pytest.approx(100 * 42.0 + 200 * 71.3)
    assert visao.patrimonio_parcial is False
    assert visao.posicoes[0].preco_medio == 32.5, "custo continua visível"
    assert visao.posicoes[0].preco_mercado == 42.0
    assert visao.exposicao_pct_por_ativo["VALE3"] == pytest.approx(
        200 * 71.3 / (100 * 42.0 + 200 * 71.3) * 100
    )


def test_visao_carteira_posicao_sem_cotacao_vira_parcial():
    from src.market.valuation import visao_carteira
    cur = _CursorCarteira(
        posicoes=[("PETR4", "ACAO", 100, 32.5), ("VALE3", "ACAO", 200, 55.0)],
        cotacoes={"PETR4": (42.0, AGORA)},  # VALE3 sem cotação
    )
    visao = visao_carteira(cur, PARAMS, AGORA)

    assert visao.patrimonio_parcial is True
    assert visao.tickers_sem_cotacao == ["VALE3"]
    assert visao.total_patrimonio == pytest.approx(4200.0), "sem inventar valor"
    vale = next(p for p in visao.posicoes if p.ticker == "VALE3")
    assert vale.valor is None
    assert "nenhuma cotação registrada" in vale.motivo_sem_cotacao


def test_visao_carteira_opcao_fora_do_patrimonio():
    from src.market.valuation import visao_carteira
    cur = _CursorCarteira(
        posicoes=[("PETR4", "ACAO", 100, 32.5), ("PETRI450", "OPCAO", -1, 0.85)],
        cotacoes={"PETR4": (42.0, AGORA)},
        precos_opcao={"PETRI450": (1.10, AGORA)},
        ticker_objeto={"PETRI450": "PETR4"},
    )
    visao = visao_carteira(cur, PARAMS, AGORA)

    assert visao.total_patrimonio == pytest.approx(4200.0), "opção não soma"
    opcao = next(p for p in visao.posicoes if p.tipo_ativo == "OPCAO")
    assert opcao.valor == pytest.approx(1.10), "mas é valorizada"
    # ...e a exposição dela é atribuída ao ativo-objeto.
    assert visao.exposicao_pct_por_ativo["PETR4"] == pytest.approx(
        (4200.0 + 1.10) / 4200.0 * 100
    )


def test_visao_carteira_vazia():
    from src.market.valuation import visao_carteira
    visao = visao_carteira(_CursorCarteira(), PARAMS, AGORA)
    assert visao.posicoes == []
    assert visao.total_patrimonio == 0.0
    assert visao.patrimonio_parcial is False
