"""Testes de src.strategy.outcome — classificação e agregação do desfecho,
sem banco."""
import pytest

from src.strategy.covered import (
    CriterioAvaliado,
    EstadoCriterio,
    ResultadoAvaliacao,
)
from src.strategy.outcome import (
    LinhaDesfecho,
    Motivo,
    agregar,
    classificar,
    criterios_reprovados,
    resumo_por_motivo,
)


def _criterio(nome, estado):
    return CriterioAvaliado(nome, 1.0, f"{nome} detalhe", estado)


def _resultado(ticker="PETR4", codigo="PETRI450", elegivel=False,
               criterios=None, bloqueado=False, motivo=None):
    return ResultadoAvaliacao(
        ticker_objeto=ticker, codigo_opcao=codigo,
        tipo_operacao="covered_call", elegivel=elegivel,
        motivo_nao_elegivel=motivo, criterios=criterios or [],
        bloqueado_por_resultado=bloqueado,
        strike=45.0, vencimento="2026-09-17", premio_estimado=0.85,
        preco_mercado=42.09, cotacao_em="2026-08-16T02:23:55+00:00",
    )


# --- Classificação ---------------------------------------------------------

def test_elegivel_e_sugerida():
    assert classificar(_resultado(elegivel=True)) == Motivo.SUGERIDA


def test_bloqueio_por_data_de_resultado():
    r = _resultado(
        bloqueado=True,
        criterios=[
            _criterio("iv_rank", EstadoCriterio.APROVADO),
            _criterio("dias_para_resultado", EstadoCriterio.INDISPONIVEL),
        ],
    )
    assert classificar(r) == Motivo.BLOQUEIO_DATA_RESULTADO


def test_criterio_reprovado():
    r = _resultado(criterios=[_criterio("iv_rank", EstadoCriterio.REPROVADO)])
    assert classificar(r) == Motivo.CRITERIO_REPROVADO


def test_reprovacao_vence_bloqueio():
    """Mesma precedência de `avaliar()`: um delta fora da faixa continua fora
    da faixa, haja ou não data de resultado."""
    r = _resultado(
        bloqueado=True,
        criterios=[
            _criterio("delta", EstadoCriterio.REPROVADO),
            _criterio("dias_para_resultado", EstadoCriterio.INDISPONIVEL),
        ],
    )
    assert classificar(r) == Motivo.CRITERIO_REPROVADO


def test_dado_insuficiente():
    r = _resultado(motivo="dado insuficiente: PETR4: nenhuma cotação registrada")
    assert classificar(r) == Motivo.DADO_INSUFICIENTE


def test_pre_requisito():
    r = _resultado(motivo="lote insuficiente para covered call: 50 ações em carteira")
    assert classificar(r) == Motivo.PRE_REQUISITO


def test_caixa_insuficiente_tambem_e_pre_requisito():
    r = _resultado(motivo="caixa insuficiente para covered put: 100 disponível")
    assert classificar(r) == Motivo.PRE_REQUISITO


def test_todo_resultado_cai_em_exatamente_um_motivo():
    casos = [
        _resultado(elegivel=True),
        _resultado(bloqueado=True, criterios=[_criterio("x", EstadoCriterio.INDISPONIVEL)]),
        _resultado(criterios=[_criterio("x", EstadoCriterio.REPROVADO)]),
        _resultado(motivo="dado insuficiente: x"),
        _resultado(motivo="lote insuficiente: x"),
    ]
    motivos = {classificar(r) for r in casos}
    assert len(motivos) == 5, "cada caso precisa cair num código distinto"


# --- Critérios reprovados --------------------------------------------------

def test_criterios_reprovados_lista_so_os_reprovados():
    r = _resultado(criterios=[
        _criterio("iv_rank", EstadoCriterio.REPROVADO),
        _criterio("delta", EstadoCriterio.APROVADO),
        _criterio("premio_pct", EstadoCriterio.REPROVADO),
        _criterio("dias_para_resultado", EstadoCriterio.INDISPONIVEL),
    ])
    assert criterios_reprovados(r) == ["iv_rank", "premio_pct"]


# --- Agregação -------------------------------------------------------------

def test_muitas_opcoes_no_mesmo_motivo_viram_uma_linha():
    """O caso que motivou a forma agregada: falta a data da PETR4 e todas as
    opções dela caem no mesmo motivo."""
    bloqueadas = [
        _resultado(codigo=f"PETRI{i}", bloqueado=True,
                   criterios=[_criterio("dias_para_resultado", EstadoCriterio.INDISPONIVEL)])
        for i in range(100)
    ]
    linhas = agregar(bloqueadas)

    assert len(linhas) == 1, "100 opções, um fato: falta a data"
    assert linhas[0].motivo == Motivo.BLOQUEIO_DATA_RESULTADO
    assert linhas[0].quantidade == 100


def test_contagem_por_criterio_pode_exceder_o_total():
    """Uma opção reprovada em dois critérios conta nos dois — a pergunta é
    'quantas foram barradas por este critério', não como elas se dividem."""
    r = _resultado(criterios=[
        _criterio("iv_rank", EstadoCriterio.REPROVADO),
        _criterio("delta", EstadoCriterio.REPROVADO),
    ])
    linha = agregar([r])[0]

    assert linha.quantidade == 1
    assert linha.criterios_contagem == {"iv_rank": 1, "delta": 1}
    assert sum(linha.criterios_contagem.values()) > linha.quantidade


def test_motivos_diferentes_viram_linhas_diferentes():
    linhas = agregar([
        _resultado(codigo="A", elegivel=True),
        _resultado(codigo="B", criterios=[_criterio("iv_rank", EstadoCriterio.REPROVADO)]),
        _resultado(codigo="C", bloqueado=True,
                   criterios=[_criterio("dias_para_resultado", EstadoCriterio.INDISPONIVEL)]),
    ])
    assert {l.motivo for l in linhas} == {
        Motivo.SUGERIDA, Motivo.CRITERIO_REPROVADO, Motivo.BLOQUEIO_DATA_RESULTADO
    }
    assert all(l.quantidade == 1 for l in linhas)


def test_ativos_diferentes_nao_se_misturam():
    linhas = agregar([
        _resultado(ticker="PETR4", criterios=[_criterio("iv_rank", EstadoCriterio.REPROVADO)]),
        _resultado(ticker="VALE3", criterios=[_criterio("iv_rank", EstadoCriterio.REPROVADO)]),
    ])
    assert len(linhas) == 2
    assert {l.ticker_objeto for l in linhas} == {"PETR4", "VALE3"}


def test_amostra_e_o_primeiro_do_grupo_e_deterministica():
    resultados = [
        _resultado(codigo="PRIMEIRA", criterios=[_criterio("iv_rank", EstadoCriterio.REPROVADO)]),
        _resultado(codigo="SEGUNDA", criterios=[_criterio("iv_rank", EstadoCriterio.REPROVADO)]),
    ]
    linha = agregar(resultados)[0]
    assert linha.amostra["codigo_opcao"] == "PRIMEIRA"
    assert agregar(resultados)[0].amostra == linha.amostra, "mesma entrada, mesma amostra"


def test_amostra_carrega_criterios_e_base_de_valorizacao():
    r = _resultado(criterios=[_criterio("iv_rank", EstadoCriterio.REPROVADO)])
    amostra = agregar([r])[0].amostra
    assert amostra["strike"] == 45.0
    assert amostra["base_valorizacao"]["preco_mercado"] == 42.09
    assert amostra["criterios"][0]["nome"] == "iv_rank"


def test_ativo_sem_opcoes_aparece_no_desfecho():
    """Sem isto, 'nada a avaliar' sumiria do registro e viraria
    indistinguível de 'ativo fora da carteira'."""
    linhas = agregar([], tickers_sem_opcoes=["VALE3"])
    assert len(linhas) == 1
    assert linhas[0].motivo == Motivo.SEM_OPCOES
    assert linhas[0].quantidade == 0


def test_ativo_com_opcoes_nao_ganha_linha_de_sem_opcoes():
    linhas = agregar(
        [_resultado(ticker="PETR4", elegivel=True)], tickers_sem_opcoes=["PETR4"]
    )
    assert [l.motivo for l in linhas] == [Motivo.SUGERIDA]


def test_execucao_vazia_nao_gera_linha():
    assert agregar([]) == []


def test_ordem_das_linhas_e_estavel():
    resultados = [
        _resultado(ticker="VALE3", elegivel=True),
        _resultado(ticker="PETR4", criterios=[_criterio("delta", EstadoCriterio.REPROVADO)]),
    ]
    assert [(l.ticker_objeto, l.motivo) for l in agregar(resultados)] == [
        ("PETR4", Motivo.CRITERIO_REPROVADO),
        ("VALE3", Motivo.SUGERIDA),
    ]


def test_resumo_por_motivo_soma_os_ativos():
    linhas = [
        LinhaDesfecho("PETR4", Motivo.CRITERIO_REPROVADO, 8),
        LinhaDesfecho("VALE3", Motivo.CRITERIO_REPROVADO, 5),
        LinhaDesfecho("PETR4", Motivo.SUGERIDA, 1),
    ]
    assert resumo_por_motivo(linhas) == {
        Motivo.CRITERIO_REPROVADO: 13, Motivo.SUGERIDA: 1,
    }
