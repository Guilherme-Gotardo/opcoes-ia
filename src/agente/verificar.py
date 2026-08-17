"""Teste de fumaça da camada de ferramentas: uma chamada real à Messages API.

Rodar:
    ANTHROPIC_API_KEY=... python -m src.agente.verificar

O QUE ISTO PROVA
----------------
O critério de pronto da Fase 3, literalmente: "o agente consegue, numa
chamada de teste, buscar uma notícia real e citar corretamente a fonte".
Não é o agente de relatório (isso é a Fase 4) — é a fiação: ferramentas
montadas certo, beta correto, busca executada, citação voltando.

Fica separado do agente de propósito. Quando o relatório sair estranho, a
primeira pergunta é "as ferramentas estão funcionando?", e responder isso
não deveria exigir rodar o pipeline inteiro.

CUSTO
-----
Uma chamada com até `max_usos` buscas. Centavos. Não roda sozinho e não
entra no timer — é comando de diagnóstico.
"""
import argparse
import logging
import os
import sys

# Importar `config` carrega o `.env` (ele chama `load_dotenv` no import), que
# é a convenção do projeto — sem isto, uma chave presente no arquivo
# apareceria como "não está no ambiente" e a mensagem mandaria configurar o
# que já estava configurado. Não usamos loaders de outro runtime de propósito:
# esta chamada não depende de DATABASE_URL nem de BRAPI_TOKEN.
import src.config  # noqa: F401
from src.agente.ferramentas import ConfiguracaoInvalida, do_arquivo

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

#: O mesmo modelo que o agente de relatório vai usar. Testar noutro modelo
#: provaria uma fiação que não é a que roda em produção.
MODELO_PADRAO = "claude-sonnet-5"

PERGUNTA = (
    "Busque na web qual é a taxa Selic meta atual definida pelo Copom e "
    "responda em uma frase, citando a fonte. Se não encontrar, diga que não "
    "encontrou — não estime."
)


#: Prefixo das chaves da Anthropic. Chave de outro provedor no lugar certo
#: é um erro plausível — DeepSeek, OpenAI e vários outros usam `sk-` puro, e
#: o nome da variável não impede ninguém de colar a chave errada nela.
_PREFIXO_ANTHROPIC = "sk-ant-"


def diagnosticar_chave(chave: str | None) -> str | None:
    """Mensagem de problema com a chave, ou `None` se ela parece válida.

    Existe porque o modo de falha sem isto é ruim: a chave de outro provedor
    vai para `api.anthropic.com`, volta 401, e a mensagem da API fala de
    autenticação — não de provedor trocado. Quem colou a chave acha que ela
    expirou, não que está no lugar errado.

    NÃO valida a chave de verdade: só distingue "não parece ser deste
    provedor" de "parece, mas pode estar inválida". A segunda só a API sabe.
    """
    if not chave:
        return None  # a ausência tem mensagem própria, mais útil que esta
    if chave.startswith(_PREFIXO_ANTHROPIC):
        return None
    return (
        f"A chave em ANTHROPIC_API_KEY não parece ser da Anthropic: chaves\n"
        f"deste provedor começam com {_PREFIXO_ANTHROPIC!r}.\n\n"
        "Chaves de DeepSeek, OpenAI e compatíveis começam só com 'sk-'. Elas\n"
        "NÃO funcionam aqui, e não é questão de qualidade do modelo: esta\n"
        "camada usa busca web nativa e conector MCP, que só existem na\n"
        "Messages API da Anthropic. Mandada para api.anthropic.com, a chave\n"
        "voltaria 401 falando de autenticação — o que esconderia a causa.\n\n"
        "Se a intenção era testar noutro provedor, guarde a chave noutra\n"
        "variável (ex.: DEEPSEEK_API_KEY) para ela não ser usada aqui por\n"
        "engano."
    )


def _texto_e_citacoes(resposta) -> tuple[str, list[str]]:
    partes, fontes = [], []
    for bloco in resposta.content:
        if bloco.type != "text":
            continue
        partes.append(bloco.text)
        for c in (getattr(bloco, "citations", None) or []):
            url = getattr(c, "url", None) or getattr(c, "document_title", None)
            if url:
                fontes.append(url)
    return "".join(partes), fontes


def _buscas_feitas(resposta) -> tuple[int, list[str]]:
    """Quantas buscas rodaram, e os erros que voltaram.

    Erro de ferramenta de servidor NÃO levanta exceção: volta HTTP 200 com
    um objeto de erro dentro do bloco de resultado. Sem olhar aqui, uma
    busca que falhou por completo pareceria uma busca que não achou nada.
    """
    n, erros = 0, []
    for bloco in resposta.content:
        if bloco.type != "web_search_tool_result":
            continue
        n += 1
        conteudo = bloco.content
        # Sucesso vem como LISTA de resultados; erro vem como OBJETO único.
        if not isinstance(conteudo, list):
            erros.append(getattr(conteudo, "error_code", "erro desconhecido"))
    return n, erros


def verificar(modelo: str = MODELO_PADRAO) -> int:
    if (problema := diagnosticar_chave(os.getenv("ANTHROPIC_API_KEY"))):
        print(problema)
        return 2

    if not os.getenv("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY não está no ambiente.\n\n"
            "A chave fica FORA do repositório, com permissão 600 — o mesmo\n"
            "lugar dos outros segredos do pregão:\n"
            "    echo 'ANTHROPIC_API_KEY=sk-ant-...' >> ~/.config/opcoes-ia/env\n"
            "    chmod 600 ~/.config/opcoes-ia/env\n"
            "Para rodar agora, sem gravar em disco:\n"
            "    ANTHROPIC_API_KEY=sk-ant-... python -m src.agente.verificar"
        )
        return 2

    try:
        import anthropic
    except ImportError:
        print("SDK ausente. Instale com: pip install -r requirements-optional.txt")
        return 2

    try:
        ferramentas = do_arquivo()
    except ConfiguracaoInvalida as e:
        print(f"Configuração de ferramentas inválida: {e}")
        return 1

    print(f"Modelo: {modelo}")
    print(f"Ferramentas: {ferramentas.resumo()}\n")

    cliente = anthropic.Anthropic()
    try:
        resposta = cliente.beta.messages.create(
            model=modelo,
            max_tokens=2000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": PERGUNTA}],
            **ferramentas.como_kwargs(),
        )
    except anthropic.APIStatusError as e:
        print(f"A API recusou a chamada ({e.status_code}): {e.message}")
        return 1
    except anthropic.APIConnectionError as e:
        print(f"Não foi possível alcançar a API: {e}")
        return 1

    # `refusal` chega como HTTP 200 — ler `content` direto quebraria aqui.
    if resposta.stop_reason == "refusal":
        print("O modelo recusou a requisição. Ferramentas não foram exercidas.")
        return 1

    buscas, erros_de_busca = _buscas_feitas(resposta)
    texto, fontes = _texto_e_citacoes(resposta)

    print(f"Buscas executadas: {buscas}")
    if erros_de_busca:
        print(f"Erros de busca: {', '.join(erros_de_busca)}")
    print(f"\nResposta:\n{texto.strip()}\n")
    print(f"Fontes citadas ({len(fontes)}):")
    for f in dict.fromkeys(fontes):
        print(f"  - {f}")

    # O critério de pronto da fase, cobrado explicitamente em vez de
    # deixado à leitura de quem rodou.
    if buscas == 0:
        print("\nFALHOU: nenhuma busca foi executada — a ferramenta não engatou.")
        return 1
    if erros_de_busca:
        print("\nFALHOU: a busca rodou mas devolveu erro.")
        return 1
    if not fontes:
        print(
            "\nPARCIAL: a busca rodou, mas a resposta não trouxe citação. A "
            "fiação está de pé; o prompt é que precisa cobrar a fonte."
        )
        return 1

    print("\nOK: busca executada e fonte citada — a fiação da Fase 3 está de pé.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--modelo", default=MODELO_PADRAO)
    return verificar(p.parse_args(argv).modelo)


if __name__ == "__main__":
    sys.exit(main())
