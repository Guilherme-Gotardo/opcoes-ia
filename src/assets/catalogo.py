"""Catálogo de ativos da B3, para o cadastro não depender de digitação.

POR QUE ISTO EXISTE
-------------------
`add_ativo` exige `nome` e nunca o deriva do ticker — regra 1 do projeto:
o sistema não inventa dado. A consequência era o usuário digitar nome e
CNPJ à mão, com a margem de erro que digitação sempre tem: um dígito
trocado no CNPJ raiz quebra o vínculo com o dump da CVM, e o calendário de
resultados fica silenciosamente vazio para aquele ativo.

Buscar num catálogo REAL resolve os dois: o nome vem da fonte, e o CNPJ
também. Continua sem inventar nada — só troca a origem do dado, de "o que
o usuário lembrou" para "o que o provedor publica".

TRÊS ARMADILHAS QUE A FONTE TEM, E QUE ESTE MÓDULO TRATA
--------------------------------------------------------
1. **Nome igual ao ticker.** BDRs e fundos voltam com `name` sendo o
   próprio código ("OXYP34", "FNOR11"). Aceitar isso seria derivar o nome
   do ticker pela porta dos fundos — exatamente o que a regra 1 proíbe.
   Esses candidatos vêm com `nome=None` e o motivo declarado, para a tela
   pedir o nome ao usuário em vez de preencher lixo.

2. **Mercado fracionário.** `PETR4F` e `RECV3F` não são ativos distintos,
   são o fracionário do mesmo papel. Cadastrar seria criar uma segunda
   entidade para a mesma empresa, e as posições ficariam divididas entre
   duas linhas que deveriam ser uma.

3. **Tipos que não cabem.** `ativos.tipo` aceita `acao`, `fii` e `bdr`. A
   fonte tem ETF, FI-Infra, FI-Agro, FIP e FIDC — todos `type=fund`.
   Mapear ETF para "fii" seria classificar errado; eles vêm marcados como
   não suportados, com o subtipo à mostra.

CUSTO
-----
Cada busca é 1 request do orçamento diário, e buscar o CNPJ é mais 1.
Cadastrar um ativo custa ~2 — irrelevante no eventual, caro se a interface
buscar a cada tecla digitada. Quem chama decide quando disparar.
"""
import logging
from dataclasses import dataclass

import requests

from src.config import get_settings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BRAPI_LISTA = "https://brapi.dev/api/quote/list"
BRAPI_COTACAO = "https://brapi.dev/api/quote"

#: Como o tipo da fonte vira o tipo de `ativos`. Chave é (type, subType).
#: O que não está aqui não é suportado — e é melhor dizer isso do que
#: escolher a caixa mais parecida.
_TIPOS = {
    ("stock", "stock"): "acao",
    ("stock", "unit"): "acao",
    ("bdr", "bdr"): "bdr",
    ("fund", "fii"): "fii",
}


class CatalogoIndisponivel(RuntimeError):
    """A fonte não respondeu como esperado. Nunca vira lista vazia: quem
    chama precisa distinguir 'nada encontrado' de 'não consegui procurar'."""


@dataclass(frozen=True)
class Candidato:
    """Um ativo do catálogo, já avaliado quanto a poder ser cadastrado."""

    ticker: str
    #: `None` quando a fonte devolveu o próprio ticker como nome — não há
    #: nome de verdade, e assumir um seria inventar.
    nome: str | None
    tipo: str | None
    setor: str | None
    #: Vazio quando o candidato pode ser cadastrado como está.
    impedimentos: tuple[str, ...] = ()

    @property
    def cadastravel(self) -> bool:
        return not self.impedimentos


def _classificar(item: dict) -> Candidato:
    ticker = (item.get("stock") or "").upper()
    nome_bruto = (item.get("name") or "").strip()
    tipo_fonte = (item.get("type") or "", item.get("subType") or "")
    impedimentos: list[str] = []

    # 1. Nome que é só o ticker de volta.
    nome = None if nome_bruto.upper() == ticker or not nome_bruto else nome_bruto
    if nome is None:
        impedimentos.append(
            "a fonte não publica o nome deste ativo — informe manualmente"
        )

    # 2. Fracionário: mesmo papel, código diferente.
    if ticker.endswith("F") and len(ticker) > 5:
        impedimentos.append(
            f"{ticker} é o mercado fracionário; cadastre o papel inteiro "
            f"({ticker[:-1]})"
        )

    # 3. Tipo fora do que o cadastro comporta.
    tipo = _TIPOS.get(tipo_fonte)
    if tipo is None:
        impedimentos.append(
            f"tipo não suportado pelo cadastro: {tipo_fonte[0]}/{tipo_fonte[1]} "
            "(aceitos: ação, FII e BDR)"
        )

    return Candidato(
        ticker=ticker,
        nome=nome,
        tipo=tipo,
        setor=item.get("sector"),
        impedimentos=tuple(impedimentos),
    )


def buscar(termo: str, limite: int = 15) -> list[Candidato]:
    """Procura ativos por código ou nome no catálogo do provedor."""
    termo = (termo or "").strip()
    if not termo:
        return []

    settings = get_settings()
    try:
        resp = requests.get(
            BRAPI_LISTA,
            params={"search": termo, "limit": limite},
            headers={"Authorization": f"Bearer {settings.brapi_token}"},
            timeout=20,
        )
        resp.raise_for_status()
        itens = resp.json().get("stocks")
    except requests.RequestException as e:
        raise CatalogoIndisponivel(
            f"não foi possível consultar o catálogo de ativos: {e}"
        ) from e

    if itens is None:
        raise CatalogoIndisponivel(
            "resposta do catálogo sem a lista de ativos — o formato da API "
            "pode ter mudado."
        )

    candidatos = [_classificar(i) for i in itens]
    # Cadastráveis primeiro: o que tem impedimento continua visível, com o
    # motivo, em vez de sumir sem explicação.
    return sorted(candidatos, key=lambda c: (not c.cadastravel, c.ticker))


def cnpj_raiz_de(ticker: str) -> str | None:
    """Raiz do CNPJ (8 dígitos) do ativo, ou `None` se a fonte não tiver.

    É o que liga o ativo ao dump da CVM para datas de resultado. Digitado à
    mão, um dígito trocado quebra o vínculo em silêncio — o calendário fica
    vazio para aquele ativo e nada aponta a causa.
    """
    settings = get_settings()
    try:
        resp = requests.get(
            f"{BRAPI_COTACAO}/{ticker.strip().upper()}",
            params={"modules": "summaryProfile"},
            headers={"Authorization": f"Bearer {settings.brapi_token}"},
            timeout=20,
        )
        resp.raise_for_status()
        resultados = resp.json().get("results") or []
    except requests.RequestException as e:
        raise CatalogoIndisponivel(
            f"não foi possível consultar o perfil de {ticker}: {e}"
        ) from e

    if not resultados:
        return None
    cnpj = (resultados[0].get("summaryProfile") or {}).get("cnpj")
    if not cnpj:
        return None

    digitos = "".join(c for c in str(cnpj) if c.isdigit())
    # A raiz são os 8 primeiros; o resto é filial e dígito verificador, e
    # `add_ativo` recusa qualquer coisa que não tenha exatamente 8.
    return digitos[:8] if len(digitos) >= 8 else None
