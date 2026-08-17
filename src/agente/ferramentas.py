"""Ferramentas que o agente de relatório pode usar na Messages API.

Este módulo só MONTA a configuração. Não chama a API, não compõe prompt e
não decide nada — é a peça que a Fase 4 consome.

TRÊS CORREÇÕES AO PLANO, TODAS VERIFICADAS CONTRA O SDK
-------------------------------------------------------
1. **`mcp_servers` sozinho é erro de validação.** O plano dizia que os MCPs
   são "passados via parâmetro `mcp_servers`". Não bastam: cada servidor
   declarado precisa de uma entrada correspondente em `tools`
   (`{"type": "mcp_toolset", "mcp_server_name": ...}`), e a chamada exige o
   beta `mcp-client-2025-11-20`. Um servidor sem toolset é rejeitado.

   Aqui isso é estruturalmente impossível de errar: as duas listas saem da
   MESMA fonte, e `validar()` prova a correspondência.

2. **Busca web não precisa de MCP nenhum.** O plano listava "busca
   web/notícia" como o primeiro MCP a conectar. A Messages API tem
   `web_search` como ferramenta NATIVA de servidor: sem servidor para
   hospedar, sem credencial para guardar, e com citação de fonte embutida —
   que é justamente o critério de pronto da fase ("citar corretamente a
   fonte"). Um MCP de busca seria trabalho a mais para um resultado pior.

3. **Notificação não é ferramenta do agente.** O plano queria um MCP de
   Slack/e-mail/Telegram para o agente entregar o relatório. Dar a ele uma
   ferramenta de ENVIO transfere ao modelo a decisão de mandar, para quem,
   e quantas vezes. O envio é determinístico e fica com o script, DEPOIS de
   o agente compor o texto — a mesma fronteira que mantém "nada aqui é
   ordem executada" verdadeira em todo o resto do projeto.

SEGREDO NUNCA MORA NO YAML
--------------------------
`ferramentas.yaml` declara o NOME da variável de ambiente que guarda o token
de cada servidor, não o token. O arquivo é versionado; a variável não.
"""
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import yaml

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

ARQUIVO_PADRAO = Path(__file__).resolve().parent / "ferramentas.yaml"

#: Versão da ferramenta de busca web com filtragem dinâmica (roda em Opus 5
#: e Sonnet 5). Fixada aqui e não em `ferramentas.yaml` porque não é escolha
#: de operação: é o contrato da API para o modelo que usamos.
TIPO_BUSCA_WEB = "web_search_20260209"
TIPO_BUSCA_WEB_BASICA = "web_search_20250305"

#: Exigido por QUALQUER chamada que declare `mcp_servers`.
BETA_MCP = "mcp-client-2025-11-20"


class ConfiguracaoInvalida(RuntimeError):
    """A configuração de ferramentas não fecha. Falha na montagem, não na
    chamada: um 400 vindo da API diria "invalid request" sem dizer qual
    servidor ficou sem toolset."""


@dataclass(frozen=True)
class ServidorMCP:
    """Um servidor MCP a conectar. O token é resolvido do ambiente na
    montagem — nunca fica no arquivo de configuração."""

    nome: str
    url: str
    #: Nome da variável de ambiente com o token, se o servidor exigir.
    variavel_token: str | None = None

    def token(self) -> str | None:
        if not self.variavel_token:
            return None
        valor = os.getenv(self.variavel_token)
        if not valor:
            log.warning(
                "Servidor MCP %r declara %s, que não está no ambiente — a "
                "conexão vai ser tentada SEM autenticação.",
                self.nome, self.variavel_token,
            )
        return valor or None


@dataclass(frozen=True)
class Ferramentas:
    """Configuração pronta para a chamada. `como_kwargs()` entrega o dicionário
    que vai direto em `client.beta.messages.create(**kwargs)`."""

    tools: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    betas: list[str] = field(default_factory=list)

    def como_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.tools:
            kwargs["tools"] = self.tools
        if self.mcp_servers:
            kwargs["mcp_servers"] = self.mcp_servers
        if self.betas:
            kwargs["betas"] = self.betas
        return kwargs

    def resumo(self) -> str:
        nativas = [t["name"] for t in self.tools if t.get("type", "").startswith("web_")]
        mcps = [s["name"] for s in self.mcp_servers]
        return (
            f"nativas: {', '.join(nativas) or 'nenhuma'} · "
            f"MCP: {', '.join(mcps) or 'nenhum'}"
        )


def carregar_config(caminho: Path | None = None) -> dict:
    caminho = caminho or ARQUIVO_PADRAO
    if not caminho.exists():
        return {}
    return yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}


def servidores_de(config: dict) -> list[ServidorMCP]:
    """Lê os servidores MCP declarados. Só entram os marcados `ativo: true` —
    deixar um servidor no arquivo desligado é a forma de registrar a intenção
    sem tentar conectar nele a cada execução."""
    servidores = []
    for item in config.get("mcp_servers") or []:
        if not item.get("ativo", False):
            continue
        faltando = [c for c in ("nome", "url") if not item.get(c)]
        if faltando:
            raise ConfiguracaoInvalida(
                f"servidor MCP sem {', '.join(faltando)}: {item!r}"
            )
        servidores.append(ServidorMCP(
            nome=str(item["nome"]), url=str(item["url"]),
            variavel_token=item.get("variavel_token"),
        ))
    return servidores


def montar(
    *,
    busca_web: bool = True,
    max_buscas: int = 5,
    servidores: Sequence[ServidorMCP] = (),
    busca_web_basica: bool = False,
) -> Ferramentas:
    """Monta a configuração de ferramentas.

    `max_buscas` existe porque busca web é cobrada por uso: sem teto, um
    relatório que "quer conferir mais uma coisa" multiplica o custo sem
    ninguém decidir isso.

    `busca_web_basica` troca para a versão sem filtragem dinâmica, necessária
    em modelos mais antigos. O padrão é a atual.
    """
    tools: list[dict[str, Any]] = []
    mcp_servers: list[dict[str, Any]] = []
    betas: list[str] = []

    if busca_web:
        tools.append({
            "type": TIPO_BUSCA_WEB_BASICA if busca_web_basica else TIPO_BUSCA_WEB,
            "name": "web_search",
            "max_uses": max_buscas,
        })

    # As duas listas saem do mesmo laço de propósito: é o que torna
    # impossível declarar um servidor sem o toolset correspondente — o erro
    # exato que o plano teria produzido.
    for s in servidores:
        servidor: dict[str, Any] = {"type": "url", "name": s.nome, "url": s.url}
        if (token := s.token()):
            servidor["authorization_token"] = token
        mcp_servers.append(servidor)
        tools.append({"type": "mcp_toolset", "mcp_server_name": s.nome})

    if mcp_servers:
        betas.append(BETA_MCP)

    ferramentas = Ferramentas(tools=tools, mcp_servers=mcp_servers, betas=betas)
    validar(ferramentas)
    return ferramentas


def validar(f: Ferramentas) -> None:
    """Prova as invariantes que a API cobraria como 400 genérico."""
    nomes_declarados = [s["name"] for s in f.mcp_servers]
    nomes_com_toolset = [
        t["mcp_server_name"] for t in f.tools if t.get("type") == "mcp_toolset"
    ]

    sem_toolset = set(nomes_declarados) - set(nomes_com_toolset)
    if sem_toolset:
        raise ConfiguracaoInvalida(
            f"servidor(es) MCP sem `mcp_toolset` correspondente em `tools`: "
            f"{sorted(sem_toolset)}. A API rejeita a requisição inteira — "
            "declarar em `mcp_servers` não basta."
        )

    orfaos = set(nomes_com_toolset) - set(nomes_declarados)
    if orfaos:
        raise ConfiguracaoInvalida(
            f"`mcp_toolset` apontando para servidor não declarado: "
            f"{sorted(orfaos)}."
        )

    duplicados = [n for n in set(nomes_declarados) if nomes_declarados.count(n) > 1]
    if duplicados:
        raise ConfiguracaoInvalida(
            f"nome de servidor MCP repetido: {sorted(duplicados)}. Os nomes "
            "precisam ser únicos — é por eles que o toolset referencia."
        )

    if f.mcp_servers and BETA_MCP not in f.betas:
        raise ConfiguracaoInvalida(
            f"há `mcp_servers` mas o beta {BETA_MCP!r} não foi declarado; a "
            "chamada seria rejeitada."
        )


def do_arquivo(caminho: Path | None = None, **extra) -> Ferramentas:
    """Atalho: lê `ferramentas.yaml` e monta."""
    config = carregar_config(caminho)
    return montar(
        busca_web=config.get("busca_web", {}).get("ativo", True),
        max_buscas=int(config.get("busca_web", {}).get("max_usos", 5)),
        servidores=servidores_de(config),
        **extra,
    )


def main() -> int:
    """`python -m src.agente.ferramentas` — mostra o que seria enviado, sem
    chamar a API nem revelar token."""
    import json

    try:
        f = do_arquivo()
    except ConfiguracaoInvalida as e:
        print(f"Configuração inválida: {e}")
        return 1

    seguro = {
        **f.como_kwargs(),
        "mcp_servers": [
            {**s, "authorization_token": "***"} if "authorization_token" in s else s
            for s in f.mcp_servers
        ],
    }
    if not f.mcp_servers:
        seguro.pop("mcp_servers", None)
    print(f.resumo())
    print(json.dumps(seguro, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
