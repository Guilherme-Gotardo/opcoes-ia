"""Testes da função pura `avaliar` de src.strategy.covered — cobre os
critérios da skill covered-options-strategy sem precisar de banco."""
import pytest

from src.strategy.covered import (
    EstadoCriterio,
    PoliticaInvalida,
    avaliar,
)

PARAMS = {
    "iv_rank_minimo": 50,
    "delta_min": 0.20,
    "delta_max": 0.35,
    "dias_vencimento_min": 20,
    "dias_vencimento_max": 45,
    "premio_minimo_pct": 0.5,
    "exposicao_maxima_pct_ativo": 20,
    "dias_bloqueio_antes_resultado": 7,
}

POSICAO_COM_LOTE = {"ticker": "PETR4", "quantidade": 100, "preco_medio": 38.0}

OPCAO_CALL_BOA = {
    "codigo": "PETRJ380", "tipo": "CALL", "strike": 38.5, "vencimento": "2026-09-21",
    "preco": 0.85, "delta": 0.28, "iv_rank": 61.0, "dias_vencimento": 32,
    "exposicao_pct_apos_operacao": 12.0, "dias_para_resultado": 30,
}


def test_avaliar_gera_sugestao_quando_todos_criterios_passam():
    resultado = avaliar(POSICAO_COM_LOTE, OPCAO_CALL_BOA, PARAMS)
    assert resultado.elegivel is True
    assert resultado.motivo_nao_elegivel is None
    assert all(c.aprovado for c in resultado.criterios)
    assert len(resultado.criterios) == 6


def test_avaliar_nao_gera_sugestao_quando_iv_rank_abaixo_do_minimo():
    opcao = dict(OPCAO_CALL_BOA, iv_rank=42.0)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, PARAMS)
    assert resultado.elegivel is False
    assert "iv_rank" in resultado.motivo_nao_elegivel
    criterio_iv = next(c for c in resultado.criterios if c.nome == "iv_rank")
    assert criterio_iv.aprovado is False


def test_avaliar_descarta_por_lote_insuficiente_sem_checar_criterios_mercado():
    posicao_sem_lote = {"ticker": "PETR4", "quantidade": 50, "preco_medio": 38.0}
    resultado = avaliar(posicao_sem_lote, OPCAO_CALL_BOA, PARAMS)
    assert resultado.elegivel is False
    assert "lote insuficiente" in resultado.motivo_nao_elegivel
    assert resultado.criterios == []  # nem chegou a avaliar critérios de mercado


def test_avaliar_marca_dado_insuficiente_quando_delta_ausente():
    opcao_sem_delta = dict(OPCAO_CALL_BOA)
    opcao_sem_delta["delta"] = None
    resultado = avaliar(POSICAO_COM_LOTE, opcao_sem_delta, PARAMS)
    assert resultado.elegivel is False
    assert "dado insuficiente" in resultado.motivo_nao_elegivel
    assert "delta" in resultado.motivo_nao_elegivel


def test_data_de_resultado_ausente_nao_aborta_a_avaliacao():
    """Antes, um `dias_para_resultado` nulo reprovava por "dado
    insuficiente" ANTES de olhar IV rank ou delta — nenhuma sugestão podia
    ser emitida, nunca. Agora os demais critérios são avaliados e ficam
    visíveis; só o critério de resultado fica indisponível."""
    opcao_sem_calendario = dict(OPCAO_CALL_BOA)
    opcao_sem_calendario["dias_para_resultado"] = None
    resultado = avaliar(POSICAO_COM_LOTE, opcao_sem_calendario, PARAMS)

    assert resultado.elegivel is False, "política padrão é bloquear"
    assert resultado.bloqueado_por_resultado is True
    assert "não verificável" in resultado.motivo_nao_elegivel
    assert "dado insuficiente" not in resultado.motivo_nao_elegivel

    # Os cinco critérios de mercado foram efetivamente avaliados.
    de_mercado = [c for c in resultado.criterios if c.nome != "dias_para_resultado"]
    assert len(de_mercado) == 5
    assert all(c.aprovado for c in de_mercado)

    criterio_resultado = next(
        c for c in resultado.criterios if c.nome == "dias_para_resultado"
    )
    assert criterio_resultado.indisponivel is True
    assert criterio_resultado.aprovado is False, "indisponível nunca conta como aprovado"


def test_politica_sinalizar_emite_sugestao_com_aviso():
    params = dict(PARAMS, politica_resultado_desconhecido="sinalizar")
    opcao = dict(OPCAO_CALL_BOA, dias_para_resultado=None)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, params)

    assert resultado.elegivel is True
    assert resultado.bloqueado_por_resultado is False
    assert "NÃO verificada" in resultado.aviso_resultado


def test_reprovacao_no_merito_vence_a_politica_sinalizar():
    """Delta fora da faixa reprova mesmo sob `sinalizar`."""
    params = dict(PARAMS, politica_resultado_desconhecido="sinalizar")
    opcao = dict(OPCAO_CALL_BOA, delta=0.85, dias_para_resultado=None)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, params)

    assert resultado.elegivel is False
    assert resultado.bloqueado_por_resultado is False, (
        "foi reprovado no mérito, não bloqueado por falta de dado"
    )
    assert "delta" in resultado.motivo_nao_elegivel
    assert "não verificável" in resultado.motivo_nao_elegivel


def test_resultado_proximo_demais_reprova_normalmente():
    opcao = dict(OPCAO_CALL_BOA, dias_para_resultado=3)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, PARAMS)
    assert resultado.elegivel is False
    assert resultado.bloqueado_por_resultado is False
    criterio = next(c for c in resultado.criterios if c.nome == "dias_para_resultado")
    assert criterio.estado is EstadoCriterio.REPROVADO


def test_politica_invalida_falha_alto():
    params = dict(PARAMS, politica_resultado_desconhecido="talvez")
    with pytest.raises(PoliticaInvalida, match="talvez"):
        avaliar(POSICAO_COM_LOTE, dict(OPCAO_CALL_BOA), params)


def test_criterios_json_expoe_os_tres_estados():
    opcao = dict(OPCAO_CALL_BOA, dias_para_resultado=None)
    dados = avaliar(POSICAO_COM_LOTE, opcao, PARAMS).criterios_json()
    estados = {c["nome"]: c["estado"] for c in dados["criterios"]}
    assert estados["dias_para_resultado"] == "indisponivel"
    assert estados["iv_rank"] == "aprovado"
    assert dados["bloqueado_por_resultado"] is True


def test_avaliar_covered_put_com_caixa_suficiente():
    posicao = {"ticker": "PETR4", "quantidade": 0, "preco_medio": 38.0, "caixa_disponivel": 4000.0}
    opcao_put = dict(OPCAO_CALL_BOA, tipo="PUT", codigo="PETRN360", strike=36.0)
    resultado = avaliar(posicao, opcao_put, PARAMS)
    assert resultado.tipo_operacao == "covered_put"
    assert resultado.elegivel is True


def test_avaliar_covered_put_com_caixa_insuficiente():
    posicao = {"ticker": "PETR4", "quantidade": 0, "preco_medio": 38.0, "caixa_disponivel": 100.0}
    opcao_put = dict(OPCAO_CALL_BOA, tipo="PUT", codigo="PETRN360", strike=36.0)
    resultado = avaliar(posicao, opcao_put, PARAMS)
    assert resultado.elegivel is False
    assert "caixa insuficiente" in resultado.motivo_nao_elegivel


def test_avaliar_covered_put_sem_info_de_caixa_marca_dado_insuficiente():
    posicao = {"ticker": "PETR4", "quantidade": 0, "preco_medio": 38.0}
    opcao_put = dict(OPCAO_CALL_BOA, tipo="PUT", codigo="PETRN360", strike=36.0)
    resultado = avaliar(posicao, opcao_put, PARAMS)
    assert resultado.elegivel is False
    assert "dado insuficiente" in resultado.motivo_nao_elegivel


def test_avaliar_nunca_relaxa_criterio_com_quatro_de_cinco_passando():
    # Todos passam exceto prêmio mínimo (posição muito cara torna o prêmio
    # percentualmente pequeno demais).
    opcao = dict(OPCAO_CALL_BOA, preco=0.05)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, PARAMS)
    assert resultado.elegivel is False
    criterio_premio = next(c for c in resultado.criterios if c.nome == "premio_pct")
    assert criterio_premio.aprovado is False
