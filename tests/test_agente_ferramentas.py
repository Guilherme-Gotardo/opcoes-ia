"""Testes da camada de ferramentas do agente. Sem rede e sem chave.

O teste que carrega o peso é `test_servidor_sem_toolset_e_recusado`: é a
invariante que o plano teria violado. Declarar um servidor em `mcp_servers`
sem a entrada correspondente em `tools` faz a API rejeitar a requisição
INTEIRA com um 400 genérico, que não diz qual servidor ficou faltando.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agente.ferramentas import (
    BETA_MCP,
    TIPO_BUSCA_WEB,
    TIPO_BUSCA_WEB_BASICA,
    ConfiguracaoInvalida,
    Ferramentas,
    ServidorMCP,
    carregar_config,
    do_arquivo,
    montar,
    servidores_de,
    validar,
)

BRAPI = ServidorMCP("brapi", "https://brapi.dev/api/mcp/mcp", "BRAPI_TOKEN")


def _tipos(f: Ferramentas) -> list[str]:
    return [t.get("type") for t in f.tools]


# --- busca web: nativa, sem MCP ---------------------------------------------

def test_busca_web_e_ferramenta_nativa_sem_servidor_nem_beta():
    """O plano listava busca web como o primeiro MCP a conectar. Não precisa:
    é ferramenta de servidor da própria API — sem servidor para hospedar,
    sem credencial, e com citação de fonte embutida."""
    f = montar()
    assert _tipos(f) == [TIPO_BUSCA_WEB]
    assert f.mcp_servers == []
    assert f.betas == [], "sem MCP não há beta a declarar"


def test_teto_de_buscas_viaja_na_ferramenta():
    """Busca web é cobrada por uso; sem teto o custo cresce sem decisão."""
    assert montar(max_buscas=2).tools[0]["max_uses"] == 2


def test_variante_basica_para_modelo_antigo():
    assert _tipos(montar(busca_web_basica=True)) == [TIPO_BUSCA_WEB_BASICA]


def test_busca_web_desligada_nao_deixa_ferramenta():
    assert montar(busca_web=False).tools == []


# --- MCP: as duas metades, sempre ---------------------------------------------

def test_mcp_gera_servidor_e_toolset_e_beta():
    with patch.dict("os.environ", {"BRAPI_TOKEN": "tok"}):
        f = montar(servidores=[BRAPI])

    assert {"type": "mcp_toolset", "mcp_server_name": "brapi"} in f.tools
    assert f.mcp_servers == [{
        "type": "url", "name": "brapi",
        "url": "https://brapi.dev/api/mcp/mcp",
        "authorization_token": "tok",
    }]
    assert f.betas == [BETA_MCP]


def test_token_ausente_conecta_sem_autenticacao_e_avisa():
    """Silenciar aqui produziria um MCP que "não devolve nada" sem motivo
    aparente."""
    with patch.dict("os.environ", {}, clear=True):
        f = montar(servidores=[BRAPI])
    assert "authorization_token" not in f.mcp_servers[0]


def test_servidor_sem_variavel_de_token_nao_manda_campo():
    f = montar(servidores=[ServidorMCP("aberto", "https://exemplo/mcp")])
    assert "authorization_token" not in f.mcp_servers[0]


def test_kwargs_saem_prontos_para_a_chamada():
    with patch.dict("os.environ", {"BRAPI_TOKEN": "tok"}):
        kwargs = montar(servidores=[BRAPI]).como_kwargs()
    assert set(kwargs) == {"tools", "mcp_servers", "betas"}


def test_kwargs_omitem_chave_vazia():
    """Mandar `mcp_servers: []` não é o mesmo que não mandar, e um beta
    declarado sem uso é ruído no contrato."""
    kwargs = montar().como_kwargs()
    assert "mcp_servers" not in kwargs
    assert "betas" not in kwargs


# --- validação: o 400 que o plano teria produzido ----------------------------

def test_servidor_sem_toolset_e_recusado():
    with pytest.raises(ConfiguracaoInvalida) as e:
        validar(Ferramentas(
            tools=[], betas=[BETA_MCP],
            mcp_servers=[{"type": "url", "name": "brapi", "url": "x"}],
        ))
    assert "brapi" in str(e.value)
    assert "não basta" in str(e.value)


def test_toolset_apontando_para_servidor_inexistente_e_recusado():
    with pytest.raises(ConfiguracaoInvalida) as e:
        validar(Ferramentas(
            tools=[{"type": "mcp_toolset", "mcp_server_name": "fantasma"}],
            mcp_servers=[], betas=[],
        ))
    assert "fantasma" in str(e.value)


def test_nome_de_servidor_repetido_e_recusado():
    """O toolset referencia por NOME; dois servidores com o mesmo nome
    tornam a referência ambígua."""
    with pytest.raises(ConfiguracaoInvalida) as e:
        validar(Ferramentas(
            tools=[{"type": "mcp_toolset", "mcp_server_name": "x"}],
            mcp_servers=[{"type": "url", "name": "x", "url": "a"},
                         {"type": "url", "name": "x", "url": "b"}],
            betas=[BETA_MCP],
        ))
    assert "repetido" in str(e.value)


def test_mcp_sem_o_beta_e_recusado():
    with pytest.raises(ConfiguracaoInvalida) as e:
        validar(Ferramentas(
            tools=[{"type": "mcp_toolset", "mcp_server_name": "brapi"}],
            mcp_servers=[{"type": "url", "name": "brapi", "url": "x"}],
            betas=[],
        ))
    assert BETA_MCP in str(e.value)


def test_montar_nunca_produz_configuracao_invalida():
    """As duas listas saem do mesmo laço — é o que torna o erro acima
    inalcançável por este caminho."""
    with patch.dict("os.environ", {"BRAPI_TOKEN": "tok"}):
        f = montar(servidores=[BRAPI, ServidorMCP("outro", "https://outro/mcp")])
    validar(f)  # não levanta
    assert len([t for t in f.tools if t.get("type") == "mcp_toolset"]) == 2


# --- leitura do arquivo -------------------------------------------------------

def _config(tmp_path: Path, conteudo: str) -> Path:
    p = tmp_path / "ferramentas.yaml"
    p.write_text(conteudo, encoding="utf-8")
    return p


def test_servidor_desligado_nao_entra(tmp_path):
    """`ativo: false` registra a intenção sem pagar uma tentativa de conexão
    por execução."""
    p = _config(tmp_path, """
mcp_servers:
  - nome: ligado
    url: https://a/mcp
    ativo: true
  - nome: desligado
    url: https://b/mcp
    ativo: false
""")
    assert [s.nome for s in servidores_de(carregar_config(p))] == ["ligado"]


def test_servidor_sem_ativo_e_tratado_como_desligado(tmp_path):
    """Padrão conservador: esquecer o campo não conecta em nada por acidente."""
    p = _config(tmp_path, "mcp_servers:\n  - nome: x\n    url: https://x/mcp\n")
    assert servidores_de(carregar_config(p)) == []


@pytest.mark.parametrize("faltando", ["nome", "url"])
def test_servidor_incompleto_falha_na_leitura(tmp_path, faltando):
    campos = {"nome": "x", "url": "https://x/mcp", "ativo": True}
    del campos[faltando]
    linhas = "\n".join(f"    {k}: {v}" for k, v in campos.items())
    p = _config(tmp_path, f"mcp_servers:\n  -\n{linhas}\n")
    with pytest.raises(ConfiguracaoInvalida) as e:
        servidores_de(carregar_config(p))
    assert faltando in str(e.value)


def test_arquivo_ausente_vira_config_vazia(tmp_path):
    assert carregar_config(tmp_path / "nao-existe.yaml") == {}


def test_arquivo_do_repositorio_monta_e_valida():
    """O arquivo real: uma configuração quebrada só apareceria na primeira
    chamada à API, já tendo gasto a viagem."""
    f = do_arquivo()
    validar(f)
    assert TIPO_BUSCA_WEB in _tipos(f), "busca web vem ligada por padrão"


# --- leitura da resposta da API ----------------------------------------------

class _Bloco:
    def __init__(self, **campos):
        self.__dict__.update(campos)


def test_erro_de_busca_nao_e_confundido_com_busca_vazia():
    """Ferramenta de servidor que falha volta HTTP 200 com um OBJETO de erro
    onde o sucesso traria uma LISTA de resultados. Sem distinguir os dois,
    uma busca que quebrou pareceria uma busca que não achou nada."""
    from src.agente.verificar import _buscas_feitas

    resposta = _Bloco(content=[
        _Bloco(type="web_search_tool_result",
               content=_Bloco(error_code="max_uses_exceeded")),
    ])
    n, erros = _buscas_feitas(resposta)
    assert n == 1
    assert erros == ["max_uses_exceeded"]


def test_busca_bem_sucedida_nao_reporta_erro():
    from src.agente.verificar import _buscas_feitas

    resposta = _Bloco(content=[
        _Bloco(type="web_search_tool_result", content=[_Bloco(url="https://a")]),
    ])
    assert _buscas_feitas(resposta) == (1, [])


def test_citacoes_saem_dos_blocos_de_texto():
    from src.agente.verificar import _texto_e_citacoes

    resposta = _Bloco(content=[
        _Bloco(type="text", text="A Selic está em 14%.",
               citations=[_Bloco(url="https://bcb.gov.br/copom")]),
        _Bloco(type="web_search_tool_result", content=[]),
        _Bloco(type="text", text=" Fonte oficial.", citations=[]),
    ])
    texto, fontes = _texto_e_citacoes(resposta)
    assert texto == "A Selic está em 14%. Fonte oficial."
    assert fontes == ["https://bcb.gov.br/copom"]


def test_bloco_de_texto_sem_citacao_nao_quebra():
    from src.agente.verificar import _texto_e_citacoes

    resposta = _Bloco(content=[_Bloco(type="text", text="oi")])
    assert _texto_e_citacoes(resposta) == ("oi", [])


def test_verificar_sem_chave_orienta_em_vez_de_estourar(capsys):
    from src.agente.verificar import verificar

    with patch.dict("os.environ", {}, clear=True):
        codigo = verificar()

    assert codigo == 2
    saida = capsys.readouterr().out
    assert "ANTHROPIC_API_KEY" in saida
    assert "chmod 600" in saida, "a mensagem tem que dizer ONDE guardar"


def test_diagnostico_nao_vaza_token(capsys):
    """`python -m src.agente.ferramentas` é o comando que se cola num
    relato de problema — não pode carregar segredo junto."""
    from src.agente import ferramentas as mod

    with patch.dict("os.environ", {"BRAPI_TOKEN": "segredo-de-verdade"}), \
            patch.object(mod, "do_arquivo",
                         return_value=montar(servidores=[BRAPI])):
        mod.main()

    saida = capsys.readouterr().out
    assert "segredo-de-verdade" not in saida
    assert "***" in saida
