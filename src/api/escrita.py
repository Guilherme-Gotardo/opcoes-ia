"""Superfície de ESCRITA da carteira, para a interface web cadastrar o que
hoje só entra por CLI.

POR QUE ISTO EXISTE, SE A API "NÃO ESCREVE"
-------------------------------------------
O invariante original de `src/api/app.py` era "somente leitura". Ele foi
revisado, não abandonado, e a distinção é a que já governa o projeto
inteiro:

- **Registrar posição não é executar ordem.** O que entra aqui é o mesmo que
  `portfolio.manage` grava desde sempre: o espelho do que o usuário JÁ tem
  na corretora. Nenhum endpoint manda ordem para lugar nenhum, e o sistema
  continua sendo de sugestão para revisão humana.
- **A regra de decisão continua fora.** Nada aqui avalia, pondera ou emite
  sugestão. Escrever posição não é decidir estratégia.

O que segue valendo, sem exceção: **nenhum endpoint dispara execução.** Este
módulo não roda ETL, avaliação, consolidação nem relatório.

POR QUE UM MÓDULO SEPARADO
--------------------------
A leitura mantém a garantia que os testes dela provam — o guardrail
`_sem_escrita` varre as queries dos endpoints de leitura e reprova qualquer
comando de escrita. Misturar as duas superfícies no mesmo módulo tornaria
esse teste impossível de escrever. Aqui a escrita é explícita, isolada e
fácil de auditar.

NENHUMA VALIDAÇÃO É REESCRITA AQUI
----------------------------------
`add_ativo`, `add_posicao` e `close_posicao` são as MESMAS funções que a CLI
usa. Este módulo só traduz HTTP para chamada de domínio e erro de domínio
para status HTTP. Duplicar a regra criaria duas verdades — e a da CLI é a
que o ETL e a avaliação já respeitam.
"""
import datetime as dt

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.assets.manage import AtivoInvalido, add_ativo, list_ativos
from src.portfolio.manage import (
    PosicaoInvalida,
    add_posicao,
    close_posicao,
    list_posicoes_abertas,
)

router = APIRouter(tags=["carteira"])


# --- Modelos ----------------------------------------------------------------

class AtivoEntrada(BaseModel):
    ticker: str
    nome: str = Field(
        description="Obrigatório: o sistema NUNCA deriva nome a partir do ticker"
    )
    tipo: str = Field(default="acao", description="acao | fii | bdr")
    cnpj_raiz: str | None = Field(
        default=None,
        description="8 dígitos, a RAIZ do CNPJ — é o que liga o ativo ao dump "
                    "da CVM para datas de resultado",
    )


class AtivoResposta(BaseModel):
    ticker: str
    nome: str
    tipo: str
    cnpj_raiz: str | None
    criado_em: dt.datetime


class PosicaoEntrada(BaseModel):
    ticker: str = Field(
        description="Em ACAO é o ticker do ativo (precisa estar cadastrado); "
                    "em OPCAO é o CÓDIGO da opção, que não é linha em `ativos`"
    )
    tipo_ativo: str = Field(description="ACAO | OPCAO")
    quantidade: int = Field(
        description="Negativo = posição LANÇADA (vendida). É assim que uma "
                    "venda coberta é registrada"
    )
    preco_medio: float = Field(description="Base de custo — nunca valor de mercado")


class PosicaoAbertaResposta(BaseModel):
    id: int
    ticker: str
    tipo_ativo: str
    quantidade: int
    preco_medio: float
    aberta_em: dt.datetime
    origem: str


class PosicaoCriada(BaseModel):
    id: int
    executou_ordem: bool = Field(
        default=False,
        description="Sempre False. Registrar posição é espelhar o que já "
                    "existe na corretora; nada foi enviado a lugar nenhum",
    )


# --- Ativos -----------------------------------------------------------------

@router.get("/ativos", response_model=list[AtivoResposta])
def listar_ativos() -> list[AtivoResposta]:
    """Ativos cadastrados — o pré-requisito de todo o resto.

    `cotacoes`, `opcoes` e `noticias` têm FK para `ativos`: sem cadastro, o
    ETL recusa o ticker e registrar posição em ação falha.
    """
    return [AtivoResposta(**a) for a in list_ativos()]


@router.post("/ativos", response_model=AtivoResposta, status_code=201)
def cadastrar_ativo(entrada: AtivoEntrada) -> AtivoResposta:
    """Cadastra ou CORRIGE um ativo.

    Regravar o mesmo ticker atualiza a linha em vez de duplicar ou falhar —
    as cotações já coletadas continuam associadas, porque a chave primária
    não muda.
    """
    try:
        ticker = add_ativo(
            entrada.ticker, entrada.nome, entrada.tipo, entrada.cnpj_raiz
        )
    except AtivoInvalido as e:
        # A mensagem do domínio é escrita para o usuário e cita o que
        # corrigir; repassá-la é melhor do que traduzi-la para algo genérico.
        raise HTTPException(status_code=422, detail=str(e)) from e

    criado = next((a for a in list_ativos() if a["ticker"] == ticker), None)
    if criado is None:  # pragma: no cover - inalcançável após INSERT bem-sucedido
        raise HTTPException(status_code=500, detail="ativo não encontrado após gravar")
    return AtivoResposta(**criado)


# --- Posições ---------------------------------------------------------------

@router.get("/posicoes", response_model=list[PosicaoAbertaResposta])
def listar_posicoes() -> list[PosicaoAbertaResposta]:
    """Posições em aberto (`fechada_em IS NULL`)."""
    return [
        PosicaoAbertaResposta(**{**p, "preco_medio": float(p["preco_medio"])})
        for p in list_posicoes_abertas()
    ]


@router.post("/posicoes", response_model=PosicaoCriada, status_code=201)
def registrar_posicao(entrada: PosicaoEntrada) -> PosicaoCriada:
    """Registra uma posição que o usuário JÁ tem.

    Isto é escrituração, não ordem: o sistema não fala com corretora em
    lugar nenhum. Quantidade negativa registra posição lançada — o caso da
    venda coberta.
    """
    try:
        posicao_id = add_posicao(
            entrada.ticker,
            entrada.tipo_ativo,
            entrada.quantidade,
            entrada.preco_medio,
        )
    except PosicaoInvalida as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return PosicaoCriada(id=posicao_id)


@router.post("/posicoes/{posicao_id}/encerrar", status_code=204)
def encerrar_posicao(posicao_id: int) -> None:
    """Marca `fechada_em`. A linha NUNCA é removida: o histórico é o que
    permite explicar uma decisão passada meses depois."""
    try:
        close_posicao(posicao_id)
    except PosicaoInvalida as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
