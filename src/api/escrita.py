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

from src.assets.manage import (
    AtivoInvalido,
    add_ativo,
    list_ativos,
    parar_de_vigiar,
    tickers_vigiados,
    universo_de_analise,
    vigiar,
)
from src.caixa.manage import LancamentoInvalido, extrato, registrar, saldo
from src.config import get_settings
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
                    "venda coberta é registrada. Está em OPÇÕES (cada uma "
                    "sobre 1 ação), não em contratos"
    )
    preco_medio: float = Field(description="Base de custo — nunca valor de mercado")

    # Só em OPCAO. Sem eles a posição entra na carteira mas fica fora do
    # acompanhamento: não há como comparar strike com cotação nem contar
    # dias para o vencimento.
    ticker_objeto: str | None = Field(
        default=None,
        description="A ação que a opção cobre. Informado, não inferido: "
                    "derivar do código exigiria interpretar código B3",
    )
    strike: float | None = None
    vencimento: dt.date | None = None


class PosicaoAbertaResposta(BaseModel):
    id: int
    ticker: str
    tipo_ativo: str
    quantidade: int
    preco_medio: float
    aberta_em: dt.datetime
    origem: str


class EncerramentoEntrada(BaseModel):
    """Como a posição fechou — obrigatório porque o resultado depende disso.

    `fechada_em` sozinho diz QUANDO fechou e nunca COMO: expirada rende o
    prêmio inteiro, recomprada rende o prêmio menos a recompra, exercida
    atravessa duas categorias fiscais.
    """

    motivo: str = Field(
        default="encerrada",
        description="expirada | recomprada | exercida | encerrada",
    )
    preco_fechamento: float | None = Field(
        default=None,
        description="Obrigatório em `recomprada`: é o que se pagou para sair. "
                    "Sem ele o resultado sairia superestimado",
    )


class VigiarEntrada(BaseModel):
    ticker: str
    motivo: str | None = Field(
        default=None,
        description="Por que este ticker entrou na watchlist — a pergunta "
                    "que aparece meses depois, quando ninguém lembra",
    )


class WatchlistResposta(BaseModel):
    """A watchlist e o custo que ela impõe.

    O orçamento vem junto de propósito: vigiar não é de graça, e o número
    de vigiados é limitado por ele. Mostrar a lista sem mostrar o teto
    deixaria o usuário descobrir o limite quando a coleta da carteira
    falhasse no fim do dia.
    """

    vigiados: list[str]
    universo: list[str] = Field(
        description="CARTEIRA ∪ VIGIADOS — o que os ETLs coletam e a "
                    "varredura percorre"
    )
    requests_por_ticker_dia: int = Field(
        description="Cotação + duas janelas de vela + opções"
    )
    orcamento_diario: int
    tickers_suportados: int = Field(
        description="Teto de tickers no universo, dado o orçamento"
    )


class CaixaEntrada(BaseModel):
    valor: float = Field(description="Positivo aporta, negativo retira. Zero é recusado")
    descricao: str | None = None


class LancamentoResposta(BaseModel):
    id: int
    valor: float
    descricao: str | None
    ocorrido_em: dt.datetime


class CaixaResposta(BaseModel):
    """Saldo e extrato.

    O saldo é a SOMA dos lançamentos, nunca um número sobrescrito: é o
    "como se chegou até aqui" que explica, meses depois, por que uma
    avaliação aceitou ou recusou uma put.
    """

    saldo: float
    garante_put: bool = Field(
        description="False quando o saldo é zero — e é isso que faz "
                    "`avaliar()` recusar a put como não coberta"
    )
    lancamentos: list[LancamentoResposta]


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
            ticker_objeto=entrada.ticker_objeto,
            strike=entrada.strike,
            vencimento=entrada.vencimento,
        )
    except PosicaoInvalida as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return PosicaoCriada(id=posicao_id)


@router.post("/posicoes/{posicao_id}/encerrar", status_code=204)
def encerrar_posicao(posicao_id: int, entrada: EncerramentoEntrada) -> None:
    """Marca `fechada_em` com o desfecho. A linha NUNCA é removida: o
    histórico é o que permite explicar uma decisão passada meses depois.

    Exige corpo com o motivo — o que também serve de confirmação: encerrar
    é irreversível pela interface (não existe reabrir), e um POST vazio
    tornava perda de dado a um clique de distância.
    """
    try:
        close_posicao(posicao_id, entrada.motivo, entrada.preco_fechamento)
    except PosicaoInvalida as e:
        # Motivo inválido é erro de entrada (422); posição inexistente é 404.
        codigo = 422 if "motivo" in str(e) or "superestimado" in str(e) else 404
        raise HTTPException(status_code=codigo, detail=str(e)) from e


# --- Watchlist --------------------------------------------------------------

#: Requests por ticker por dia: cotação (1) + velas 1h e 1d (2) + opções (1).
_REQUESTS_POR_TICKER_DIA = 4


@router.get("/watchlist", response_model=WatchlistResposta)
def listar_watchlist() -> WatchlistResposta:
    """Ativos vigiados e o custo que isso impõe ao orçamento diário."""
    orcamento = get_settings().brapi_requests_dia_maximo
    return WatchlistResposta(
        vigiados=tickers_vigiados(),
        universo=universo_de_analise(),
        requests_por_ticker_dia=_REQUESTS_POR_TICKER_DIA,
        orcamento_diario=orcamento,
        tickers_suportados=orcamento // _REQUESTS_POR_TICKER_DIA,
    )


@router.post("/watchlist", status_code=201)
def adicionar_a_watchlist(entrada: VigiarEntrada) -> dict:
    """Passa a vigiar um ativo JÁ CADASTRADO.

    Vigiar não cadastra: `ativos` é alvo de FK de cotação, opção e notícia,
    e criar o registro aqui exigiria inventar o nome do ativo — o que a
    regra 1 do projeto proíbe.
    """
    try:
        vigiar(entrada.ticker, entrada.motivo)
    except AtivoInvalido as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"ticker": entrada.ticker.strip().upper(), "vigiado": True}


@router.post("/watchlist/{ticker}/remover", status_code=204)
def remover_da_watchlist(ticker: str) -> None:
    """Sai da varredura e para de consumir orçamento. O cadastro e o
    histórico permanecem — isto não descadastra o ativo."""
    parar_de_vigiar(ticker)


# --- Caixa ------------------------------------------------------------------

@router.get("/caixa", response_model=CaixaResposta)
def ler_caixa() -> CaixaResposta:
    atual = saldo()
    return CaixaResposta(
        saldo=atual,
        garante_put=atual > 0,
        lancamentos=[LancamentoResposta(**l) for l in extrato()],
    )


@router.post("/caixa", status_code=201)
def lancar_caixa(entrada: CaixaEntrada) -> dict:
    """Registra um lançamento. É o que torna uma PUT coberta, coberta:
    sem garantia para honrar o exercício ao strike, `avaliar()` recusa a
    operação em vez de tratá-la como coberta."""
    try:
        lancamento_id = registrar(entrada.valor, entrada.descricao)
    except LancamentoInvalido as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"id": lancamento_id, "saldo": saldo()}
