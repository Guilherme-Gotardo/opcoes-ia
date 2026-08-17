from src.etl.policy import FluxoPolicy, PoliticaColeta, agregar, carregar
from src.etl.result import DetalheAlvo, EstadoAlvo, EstadoColeta, ResultadoColeta


def _politica():
    return PoliticaColeta("teste-1", {
        "daily": FluxoPolicy(
            obrigatorias=frozenset({"cotacoes", "earnings"}),
            opcionais=frozenset({"opcoes", "noticias"}),
        )
    })


def _resultado(coletor, estado=EstadoAlvo.SUCESSO):
    return ResultadoColeta.de_detalhes(
        coletor, "fonte", [DetalheAlvo("PETR4", estado)]
    )


def test_arquivo_de_politica_tem_versao_e_fluxos():
    politica = carregar()
    assert politica.versao == "2026-08-17.1"
    assert politica.fluxos["intraday"].obrigatorias == {"cotacoes"}


def test_todas_as_fontes_saudaveis():
    resultado = agregar("daily", [
        _resultado("cotacoes"), _resultado("earnings"),
        _resultado("opcoes"), _resultado("noticias"),
    ], _politica())
    assert resultado.estado == EstadoColeta.SUCESSO


def test_fonte_obrigatoria_falha():
    resultado = agregar("daily", [
        _resultado("cotacoes", EstadoAlvo.FALHA), _resultado("earnings"),
        _resultado("opcoes"), _resultado("noticias"),
    ], _politica())
    assert resultado.estado == EstadoColeta.FALHA


def test_fonte_obrigatoria_parcial():
    parcial = ResultadoColeta.de_detalhes("cotacoes", "brapi", [
        DetalheAlvo("PETR4", EstadoAlvo.SUCESSO),
        DetalheAlvo("VALE3", EstadoAlvo.FALHA),
    ])
    resultado = agregar("daily", [
        parcial, _resultado("earnings"), _resultado("opcoes"),
        _resultado("noticias"),
    ], _politica())
    assert resultado.estado == EstadoColeta.PARCIAL


def test_fonte_opcional_bloqueada_degrada_para_parcial():
    resultado = agregar("daily", [
        _resultado("cotacoes"), _resultado("earnings"),
        _resultado("opcoes", EstadoAlvo.BLOQUEADO), _resultado("noticias"),
    ], _politica())
    assert resultado.estado == EstadoColeta.PARCIAL


def test_fonte_opcional_nao_configurada_degrada_para_parcial():
    resultado = agregar("daily", [
        _resultado("cotacoes"), _resultado("earnings"), _resultado("opcoes"),
        ResultadoColeta.pulado("noticias", "newsapi", "fonte_nao_configurada"),
    ], _politica())
    assert resultado.estado == EstadoColeta.PARCIAL


def test_fonte_opcional_ausente_degrada_para_parcial():
    resultado = agregar("daily", [
        _resultado("cotacoes"), _resultado("earnings"), _resultado("opcoes"),
    ], _politica())
    assert resultado.estado == EstadoColeta.PARCIAL
    assert resultado.fontes_ausentes == ("noticias",)


def test_universo_totalmente_vazio_e_pulado():
    resultados = [
        ResultadoColeta.pulado(nome, "fonte", "universo_vazio")
        for nome in ("cotacoes", "earnings", "opcoes", "noticias")
    ]
    assert agregar("daily", resultados, _politica()).estado == EstadoColeta.PULADO


def test_resultado_inclui_versao_da_politica():
    resultado = agregar("daily", [
        _resultado("cotacoes"), _resultado("earnings"),
        _resultado("opcoes"), _resultado("noticias"),
    ], _politica())
    assert resultado.como_dict()["policy_version"] == "teste-1"
