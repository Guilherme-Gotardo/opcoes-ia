"""Testes da função pura `avaliar` de src.strategy.covered — cobre os
critérios da skill covered-options-strategy sem precisar de banco."""
import pytest

from src.strategy import covered
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

#: `preco_medio` (custo) e `preco_mercado` são deliberadamente diferentes em
#: todas as fixtures: se algum critério voltar a usar custo, algum teste
#: quebra em vez de passar por coincidência.
POSICAO_COM_LOTE = {
    "ticker": "PETR4", "quantidade": 100, "preco_medio": 38.0,
    "preco_mercado": 42.0, "cotacao_em": "2026-08-15T12:00:00+00:00",
}

#: `idade_horas` é obrigatório desde 2026-08-16: o dado da opção passa pela
#: mesma janela de frescor que a cotação da ação. Idade desconhecida é
#: tratada como dado insuficiente, e não como "pode usar".
OPCAO_CALL_BOA = {
    "codigo": "PETRJ380", "tipo": "CALL", "strike": 38.5, "vencimento": "2026-09-21",
    "preco": 0.85, "delta": 0.28, "iv_rank": 61.0, "dias_vencimento": 32,
    "exposicao_pct_apos_operacao": 12.0, "dias_para_resultado": 30,
    "idade_horas": 2.0,
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
    posicao_sem_lote = dict(POSICAO_COM_LOTE, quantidade=50)
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
    posicao = dict(POSICAO_COM_LOTE, quantidade=0, caixa_disponivel=4000.0)
    opcao_put = dict(OPCAO_CALL_BOA, tipo="PUT", codigo="PETRN360", strike=36.0)
    resultado = avaliar(posicao, opcao_put, PARAMS)
    assert resultado.tipo_operacao == "covered_put"
    assert resultado.elegivel is True


def test_avaliar_covered_put_com_caixa_insuficiente():
    posicao = dict(POSICAO_COM_LOTE, quantidade=0, caixa_disponivel=100.0)
    opcao_put = dict(OPCAO_CALL_BOA, tipo="PUT", codigo="PETRN360", strike=36.0)
    resultado = avaliar(posicao, opcao_put, PARAMS)
    assert resultado.elegivel is False
    assert "caixa insuficiente" in resultado.motivo_nao_elegivel


def test_avaliar_covered_put_sem_info_de_caixa_marca_dado_insuficiente():
    posicao = dict(POSICAO_COM_LOTE, quantidade=0)
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


# --- Valorização a preço de mercado ----------------------------------------

def test_posicao_sem_cotacao_e_dado_insuficiente_antes_dos_criterios():
    """Sem preço de mercado não há como calcular prêmio nem exposição — a
    avaliação para antes dos critérios, e não cai para `preco_medio`."""
    posicao = dict(
        POSICAO_COM_LOTE, preco_mercado=None, cotacao_em=None,
        motivo_sem_cotacao="PETR4: cotação de 100.0h atrás, fora da janela de 72h",
    )
    resultado = avaliar(posicao, OPCAO_CALL_BOA, PARAMS)

    assert resultado.elegivel is False
    assert "dado insuficiente" in resultado.motivo_nao_elegivel
    assert "PETR4" in resultado.motivo_nao_elegivel
    assert "100.0h" in resultado.motivo_nao_elegivel, "a idade precisa chegar ao usuário"
    assert resultado.criterios == [], "nem chegou a avaliar critérios de mercado"
    assert resultado.bloqueado_por_resultado is False, (
        "faltou cotação, não data de resultado"
    )


def test_premio_minimo_e_calculado_sobre_mercado_nao_sobre_custo():
    """Prêmio de 0.20 sobre custo 38.0 dá 0.53% (passaria); sobre mercado
    42.0 dá 0.48% (reprova). O critério tem de seguir o mercado."""
    opcao = dict(OPCAO_CALL_BOA, preco=0.20)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, PARAMS)

    criterio = next(c for c in resultado.criterios if c.nome == "premio_pct")
    assert criterio.valor == pytest.approx(0.4762, abs=1e-4)
    assert criterio.aprovado is False
    assert "42.0" in criterio.detalhe, "o detalhe precisa dizer sobre o que calculou"


def test_covered_call_coberta_passa_mesmo_com_strike_alto_para_o_patrimonio():
    """O caso que motivou a change: com o notional cheio (strike 45 × 100 =
    R$ 4.500) contra patrimônio de R$ 14.250, a exposição dava 31,6% e
    reprovava toda covered call de PETR4. Coberta pelas ações, é zero."""
    opcao = dict(OPCAO_CALL_BOA, strike=45.0, exposicao_pct_apos_operacao=0.0)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, PARAMS)

    assert resultado.elegivel is True
    criterio = next(
        c for c in resultado.criterios if c.nome == "exposicao_pct_apos_operacao"
    )
    assert criterio.aprovado is True


def test_exposicao_descoberta_acima_do_limite_continua_reprovando():
    opcao = dict(OPCAO_CALL_BOA, exposicao_pct_apos_operacao=31.6)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, PARAMS)

    assert resultado.elegivel is False
    criterio = next(
        c for c in resultado.criterios if c.nome == "exposicao_pct_apos_operacao"
    )
    assert criterio.aprovado is False


def test_exposicao_pct_soma_o_descoberto_novo_ao_ja_existente(monkeypatch):
    """A conta do percentual: descoberto da operação nova + descoberto já em
    carteira, sobre o patrimônio a mercado."""
    monkeypatch.setattr(
        covered, "notional_descoberto_em_carteira", lambda cur, ticker: 1000.0
    )
    pct = covered._exposicao_pct_apos_operacao(
        cur=None, ticker_objeto="PETR4",
        nova_operacao_notional=500.0, patrimonio_total=15000.0,
    )
    assert pct == pytest.approx(10.0)


def test_exposicao_pct_sem_patrimonio_devolve_none(monkeypatch):
    monkeypatch.setattr(
        covered, "notional_descoberto_em_carteira", lambda cur, ticker: 0.0
    )
    assert covered._exposicao_pct_apos_operacao(None, "PETR4", 500.0, 0.0) is None


def test_criterios_json_registra_a_base_de_valorizacao():
    dados = avaliar(POSICAO_COM_LOTE, OPCAO_CALL_BOA, PARAMS).criterios_json()
    assert dados["base_valorizacao"] == {
        "preco_mercado": 42.0,
        "cotacao_em": "2026-08-15T12:00:00+00:00",
    }


# --- Achados da revisão de 2026-08-16 ---------------------------------------
#
# Cada teste abaixo fixa um defeito que quebrava a mesma garantia central:
# campo ausente vira "dado insuficiente", nunca valor assumido nem exceção.

OPCAO_PUT_BOA = dict(
    OPCAO_CALL_BOA, codigo="PETRV380", tipo="PUT", delta=-0.28,
)
POSICAO_COM_CAIXA = dict(POSICAO_COM_LOTE, caixa_disponivel=10_000.0)


def test_covered_put_com_strike_ausente_nao_estoura():
    """Era TypeError: `strike * 100` rodava antes de qualquer checagem.

    O ETL grava NULL em `strike` quando o provedor não devolve — o próprio
    `_opcoes_call_candidatas` já previa isso —, então o caminho existia de
    verdade e derrubava a avaliação inteira.
    """
    opcao = dict(OPCAO_PUT_BOA, strike=None)
    resultado = avaliar(POSICAO_COM_CAIXA, opcao, PARAMS)
    assert resultado.elegivel is False
    assert "dado insuficiente" in resultado.motivo_nao_elegivel
    assert "strike" in resultado.motivo_nao_elegivel


def test_covered_put_sem_caixa_nao_calcula_garantia_antes_de_reclamar():
    """A ordem importa: com strike válido e caixa ausente, o motivo tem que
    ser o caixa — não um erro no cálculo que nem deveria ter acontecido."""
    opcao = dict(OPCAO_PUT_BOA, strike=38.5)
    posicao = dict(POSICAO_COM_LOTE)  # sem caixa_disponivel
    resultado = avaliar(posicao, opcao, PARAMS)
    assert resultado.elegivel is False
    assert "caixa/garantia disponível não informado" in resultado.motivo_nao_elegivel


def test_garantia_do_covered_put_usa_acoes_por_contrato():
    """O 100 solto virou a constante. Caixa 1 centavo abaixo da garantia
    reprova, e a mensagem cita o valor calculado com a constante."""
    from src.market.valuation import ACOES_POR_CONTRATO

    strike = 38.5
    garantia = strike * ACOES_POR_CONTRATO
    opcao = dict(OPCAO_PUT_BOA, strike=strike)
    posicao = dict(POSICAO_COM_LOTE, caixa_disponivel=garantia - 0.01)

    resultado = avaliar(posicao, opcao, PARAMS)
    assert resultado.elegivel is False
    assert "caixa insuficiente" in resultado.motivo_nao_elegivel
    assert str(garantia) in resultado.motivo_nao_elegivel


def test_lote_do_covered_call_usa_acoes_por_contrato():
    from src.market.valuation import ACOES_POR_CONTRATO

    posicao = dict(POSICAO_COM_LOTE, quantidade=ACOES_POR_CONTRATO - 1)
    resultado = avaliar(posicao, OPCAO_CALL_BOA, PARAMS)
    assert resultado.elegivel is False
    assert str(ACOES_POR_CONTRATO) in resultado.motivo_nao_elegivel


def test_strike_ausente_no_covered_call_e_dado_insuficiente():
    """Antes o orquestrador fazia `strike or 0.0`: notional zero, exposição
    zero, critério de exposição APROVADO. Um dado faltando aprovava o
    critério que deveria barrar."""
    opcao = dict(OPCAO_CALL_BOA, strike=None)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, PARAMS)
    assert resultado.elegivel is False
    assert "strike" in resultado.motivo_nao_elegivel


def test_dado_de_opcao_fora_da_janela_de_frescor_e_recusado():
    """A janela valia só para a cotação da ação; delta e IV rank de dias
    atrás entravam como se fossem de agora."""
    opcao = dict(OPCAO_CALL_BOA, idade_horas=100.0)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, dict(PARAMS))
    assert resultado.elegivel is False
    assert "fora da janela" in resultado.motivo_nao_elegivel
    assert "100.0h" in resultado.motivo_nao_elegivel


def test_opcao_sem_data_de_coleta_e_dado_insuficiente():
    opcao = dict(OPCAO_CALL_BOA, idade_horas=None)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, PARAMS)
    assert resultado.elegivel is False
    assert "sem data de coleta" in resultado.motivo_nao_elegivel


def test_janela_da_opcao_pode_ser_mais_curta_que_a_da_cotacao():
    """O parâmetro próprio existe para apertar a opção sem apertar a ação."""
    params = dict(PARAMS, cotacao_frescor_maximo_horas=72,
                  opcao_frescor_maximo_horas=4)
    opcao = dict(OPCAO_CALL_BOA, idade_horas=10.0)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, params)
    assert resultado.elegivel is False
    assert "janela de 4h" in resultado.motivo_nao_elegivel


def test_premio_ao_mes_aparece_no_detalhe_sem_mudar_o_criterio():
    """O viés de prazo fica visível; o limiar segue sobre o valor bruto."""
    resultado = avaliar(POSICAO_COM_LOTE, OPCAO_CALL_BOA, PARAMS)
    premio = next(c for c in resultado.criterios if c.nome == "premio_pct")
    assert "%/mês" in premio.detalhe
    assert premio.aprovado is True
    assert not any(c.nome == "premio_pct_ao_mes" for c in resultado.criterios)


def test_criterio_de_premio_ao_mes_so_existe_se_configurado():
    """Opção de 45 dias com prêmio que passa no bruto e falha no mensal."""
    params = dict(PARAMS, premio_minimo_pct=0.5, premio_minimo_pct_ao_mes=2.0)
    opcao = dict(OPCAO_CALL_BOA, dias_vencimento=45)
    resultado = avaliar(POSICAO_COM_LOTE, opcao, params)

    bruto = next(c for c in resultado.criterios if c.nome == "premio_pct")
    mensal = next(c for c in resultado.criterios if c.nome == "premio_pct_ao_mes")
    assert bruto.aprovado is True, "o critério bruto continua passando"
    assert mensal.aprovado is False, "o normalizado por prazo reprova"
    assert resultado.elegivel is False


def test_denominador_parcial_e_declarado_no_criterio_de_exposicao():
    """Era só log.warning: quem lê o desfecho não via que a exposição estava
    inflada por um patrimônio incompleto."""
    posicao = dict(POSICAO_COM_LOTE,
                   patrimonio_tickers_sem_cotacao=("ABEV3", "BBAS3"))
    resultado = avaliar(posicao, OPCAO_CALL_BOA, PARAMS)
    exposicao = next(
        c for c in resultado.criterios if c.nome == "exposicao_pct_apos_operacao"
    )
    assert "denominador parcial" in exposicao.detalhe
    assert "ABEV3" in exposicao.detalhe and "BBAS3" in exposicao.detalhe


def test_sem_patrimonio_parcial_o_detalhe_fica_limpo():
    resultado = avaliar(POSICAO_COM_LOTE, OPCAO_CALL_BOA, PARAMS)
    exposicao = next(
        c for c in resultado.criterios if c.nome == "exposicao_pct_apos_operacao"
    )
    assert "denominador parcial" not in exposicao.detalhe
