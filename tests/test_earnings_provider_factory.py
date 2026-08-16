"""Testes da fábrica de providers (`src.earnings.providers`).

Nome errado precisa morrer aqui, antes de qualquer I/O — se passar, vira
"nenhum evento encontrado" lá na frente, que é indistinguível de "não há
resultado próximo"."""
import pytest

from src.earnings.providers import (
    FONTES_PADRAO,
    PROVIDERS_DISPONIVEIS,
    FonteDesconhecida,
    ManualProvider,
    construir_providers,
)


def test_padrao_e_somente_manual():
    """`manual` é offline e a única autoridade para CONFIRMED — é o único
    padrão sensato para uma operação dentro do pipeline diário."""
    assert FONTES_PADRAO == ("manual",)
    providers = construir_providers()
    assert len(providers) == 1
    assert isinstance(providers[0], ManualProvider)
    assert providers[0].name == "manual"


def test_nome_valido_instancia_o_provider_certo():
    providers = construir_providers(["manual"])
    assert [p.name for p in providers] == ["manual"]


def test_nome_e_normalizado():
    providers = construir_providers([" Manual "])
    assert [p.name for p in providers] == ["manual"]


def test_repeticao_nao_consulta_a_mesma_fonte_duas_vezes():
    providers = construir_providers(["manual", "manual"])
    assert len(providers) == 1


def test_apelido_yahoo_resolve_para_o_provider_yfinance():
    """O provider se chama `yfinance` (nome usado no mapa de tiers de
    `confidence.py` e gravado nas fontes do evento), mas a documentação diz
    `yahoo` — os dois precisam funcionar."""
    providers = construir_providers(["yahoo"])
    assert [p.name for p in providers] == ["yfinance"]


def test_apelido_e_canonico_nao_duplicam_a_fonte():
    assert len(construir_providers(["yahoo", "yfinance"])) == 1


def test_nome_invalido_levanta_erro_citando_as_opcoes():
    with pytest.raises(FonteDesconhecida) as exc:
        construir_providers(["manual", "bloomberg"])
    mensagem = str(exc.value)
    assert "bloomberg" in mensagem, "precisa nomear o valor inválido"
    for nome in PROVIDERS_DISPONIVEIS:
        assert nome in mensagem, "precisa listar as fontes válidas"


def test_nome_invalido_falha_antes_de_construir_qualquer_provider():
    """Se o erro saísse depois de instanciar as fontes válidas, o `cvm` já
    teria baixado o dump antes de o comando abortar."""
    with pytest.raises(FonteDesconhecida):
        construir_providers(["inexistente"])


@pytest.mark.parametrize("nomes", [[], [""], ["  "], [None]])
def test_lista_vazia_e_erro_e_nao_padrao(nomes):
    """`EarningsEventService.__init__` faz `providers or []`: sem esta
    guarda, `--fontes ''` consolidaria zero eventos reportando sucesso."""
    with pytest.raises(FonteDesconhecida, match="nenhuma fonte"):
        construir_providers(nomes)


def test_none_cai_no_padrao_em_vez_de_erro():
    """`None` é "não pedi nada", diferente de "pedi lista vazia"."""
    assert len(construir_providers(None)) == 1


def test_todas_as_fontes_registradas_sao_construiveis():
    """Guarda contra um provider ganhar argumento obrigatório no construtor
    sem a fábrica acompanhar."""
    for nome in PROVIDERS_DISPONIVEIS:
        provider = construir_providers([nome])[0]
        assert provider.name == nome
