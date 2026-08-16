"""Fábrica de providers de datas de resultado, por nome.

Existe para que o entrypoint de consolidação (`src/earnings/ingest.py`)
traduza `--fontes manual,cvm` em instâncias sem conhecer o construtor de
cada provider — e para que um nome errado morra aqui, antes de qualquer
I/O, em vez de virar "nenhum evento encontrado" lá na frente.

O padrão é só `manual`: é a única fonte com autoridade para `CONFIRMED`, é
determinística e não depende de rede. `cvm` baixa o dump IPE e `yahoo` sai
para a rede via `yfinance` — custo que só faz sentido quando pedido.

Os imports de `cvm` e `yahoo` são adiados para dentro dos construtores
porque eles arrastam `requests` e `yfinance`; quem roda só o padrão não
deve pagar por dependência que não vai usar.
"""
from src.earnings.providers.base import EarningsProvider, ProviderIndisponivel
from src.earnings.providers.manual import ManualProvider


class FonteDesconhecida(ValueError):
    """Nome de fonte que não corresponde a nenhum provider registrado.

    Falha alto em vez de rodar o subconjunto reconhecido: consolidar menos
    fontes do que o usuário pediu produziria "nenhum evento" por um motivo
    que ele não teria como ver.
    """


def _construir_cvm() -> EarningsProvider:
    from src.earnings.providers.cvm import CvmProvider  # noqa: PLC0415

    return CvmProvider()


def _construir_yahoo() -> EarningsProvider:
    from src.earnings.providers.yahoo import YahooProvider  # noqa: PLC0415

    return YahooProvider()


#: Nome canônico da fonte → construtor. A chave é SEMPRE o `provider.name`,
#: porque é por ele que `EarningsEventService.coletar()` indexa o resultado,
#: que `confidence.py` decide o tier e que fica gravado nas fontes do evento.
#: Divergir aqui faria o relatório de execução falar de uma fonte com um
#: nome que o resto do sistema não reconhece.
PROVIDERS_DISPONIVEIS: dict[str, callable] = {
    "manual": ManualProvider,
    "cvm": _construir_cvm,
    "yfinance": _construir_yahoo,
}

#: Apelidos aceitos em `--fontes`. O provider do Yahoo se chama `yfinance`
#: (nome da biblioteca) desde a Fase 2, mas quem lê a documentação digita
#: `yahoo` — aceitar os dois evita um "fonte desconhecida" gratuito sem
#: renomear a identidade que já está persistida.
APELIDOS: dict[str, str] = {
    "yahoo": "yfinance",
}

#: Conjunto padrão da consolidação — ver docstring do módulo.
FONTES_PADRAO: tuple[str, ...] = ("manual",)


def nomes_aceitos() -> list[str]:
    """Nomes canônicos e apelidos, para mensagens de erro acionáveis."""
    return sorted(set(PROVIDERS_DISPONIVEIS) | set(APELIDOS))


def construir_providers(nomes: list[str] | None = None) -> list[EarningsProvider]:
    """Instancia os providers pedidos, validando os nomes antes de tocar I/O.

    `None` cai em `FONTES_PADRAO`. Lista vazia é ERRO, não padrão: com
    `providers=[]` o `EarningsEventService` consolidaria zero eventos e
    reportaria sucesso — falha silenciosa com cara de execução limpa.
    """
    if nomes is None:
        nomes = list(FONTES_PADRAO)

    pedidos = [n.strip().lower() for n in nomes if n and n.strip()]
    if not pedidos:
        raise FonteDesconhecida(
            "nenhuma fonte informada. Use uma ou mais de: "
            f"{', '.join(nomes_aceitos())}."
        )

    normalizados = [APELIDOS.get(n, n) for n in pedidos]
    desconhecidos = [n for n in normalizados if n not in PROVIDERS_DISPONIVEIS]
    if desconhecidos:
        raise FonteDesconhecida(
            f"fonte(s) desconhecida(s): {', '.join(desconhecidos)}. "
            f"Use uma ou mais de: {', '.join(nomes_aceitos())}."
        )

    # `dict.fromkeys` preserva a ordem pedida e remove repetição — pedir
    # `manual,manual` não deve consultar a mesma fonte duas vezes.
    return [PROVIDERS_DISPONIVEIS[n]() for n in dict.fromkeys(normalizados)]


__all__ = [
    "APELIDOS",
    "EarningsProvider",
    "FONTES_PADRAO",
    "FonteDesconhecida",
    "ManualProvider",
    "PROVIDERS_DISPONIVEIS",
    "ProviderIndisponivel",
    "construir_providers",
    "nomes_aceitos",
]
