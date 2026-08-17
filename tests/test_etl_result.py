import json

import pytest

from src.etl.result import DetalheAlvo, EstadoAlvo, EstadoColeta, ResultadoColeta


def _alvo(estado, ticker="PETR4", registros=0, tentado=True):
    return DetalheAlvo(ticker, estado, registros, tentado=tentado)


def test_universo_vazio_vira_pulado():
    resultado = ResultadoColeta.pulado("cotacoes", "brapi", "universo_vazio")
    assert resultado.estado == EstadoColeta.PULADO
    assert resultado.alvos_total == 0


def test_todos_os_alvos_com_sucesso():
    resultado = ResultadoColeta.de_detalhes("cotacoes", "brapi", [
        _alvo(EstadoAlvo.SUCESSO, registros=1),
        _alvo(EstadoAlvo.SUCESSO, "VALE3", registros=1),
    ])
    assert resultado.estado == EstadoColeta.SUCESSO
    assert resultado.registros_persistidos == 2


def test_sucesso_e_falha_viram_parcial():
    resultado = ResultadoColeta.de_detalhes("cotacoes", "brapi", [
        _alvo(EstadoAlvo.SUCESSO, registros=1),
        _alvo(EstadoAlvo.FALHA, "VALE3"),
    ])
    assert resultado.estado == EstadoColeta.PARCIAL
    assert resultado.alvos_falhos == 1


def test_todos_os_alvos_falham():
    resultado = ResultadoColeta.de_detalhes("cotacoes", "brapi", [
        _alvo(EstadoAlvo.FALHA),
    ])
    assert resultado.estado == EstadoColeta.FALHA


def test_todos_os_alvos_bloqueados():
    resultado = ResultadoColeta.de_detalhes("opcoes", "oplab", [
        _alvo(EstadoAlvo.BLOQUEADO, tentado=False),
    ])
    assert resultado.estado == EstadoColeta.BLOQUEADO
    assert resultado.alvos_tentados == 0


def test_resultado_rejeita_contagens_inconsistentes():
    with pytest.raises(ValueError, match="sem sucesso"):
        _alvo(EstadoAlvo.FALHA, registros=1)
    with pytest.raises(ValueError, match="não executado"):
        _alvo(EstadoAlvo.NAO_EXECUTADO)


def test_resultado_e_serializavel():
    resultado = ResultadoColeta.de_detalhes("candles_1h", "brapi", [
        _alvo(EstadoAlvo.SUCESSO, registros=28),
    ], contexto={"intervalo": "1h", "janela": "5d"})
    serializado = json.dumps(resultado.como_dict())
    assert '"estado": "sucesso"' in serializado
    assert '"registros_persistidos": 28' in serializado
