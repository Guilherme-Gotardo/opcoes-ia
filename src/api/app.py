"""API de leitura da carteira, para a interface web consumir.

TRÊS LIMITES, POR CONSTRUÇÃO
----------------------------
1. **Não decide.** Todo critério de estratégia é determinístico e mora em
   `src/strategy/`; aqui só se serializa o que o domínio já concluiu.
   Nenhum cálculo de valorização, exposição ou risco acontece neste módulo.
2. **Não dispara.** Nenhum endpoint roda ETL, avaliação, consolidação ou
   relatório. A API lê o que a execução anterior gravou — inclusive o
   desfecho da avaliação, que desde a change `persist-evaluation-outcomes`
   sobrevive ao processo.
3. **Não escreve.** Somente leitura; nenhuma tabela é alterada.

SEM AUTENTICAÇÃO, POR DECISÃO REGISTRADA
----------------------------------------
Ferramenta de um usuário, na máquina do usuário. O servidor sobe ligado a
`127.0.0.1` (nunca `0.0.0.0` — a diferença entre "minha máquina" e "minha
rede local"), e o CORS libera só a origem do dev server do Vite. Publicar
isto em endereço acessível pela internet exige rever a decisão numa change
própria.

Os modelos Pydantic existem para o OpenAPI sair descritivo o bastante para
gerar os tipos TypeScript do frontend (`openapi-typescript`) — não para
revalidar regra de domínio.
"""
import datetime as dt
import json
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.db.connection import get_connection
from src.market.valuation import carregar_params, visao_carteira
from src.strategy.outcome_repository import ultima_execucao_do_dia

#: Origem do dev server do Vite. Configurável, mas nunca "*": inofensivo em
#: localhost hoje, perigoso no dia em que alguém publicar sem revisar.
ORIGEM_INTERFACE = os.getenv("OPCOES_IA_WEB_ORIGIN", "http://localhost:5173")

app = FastAPI(
    title="opcoes-ia — leitura da carteira",
    description=(
        "Superfície de LEITURA para a interface própria. Não decide, não "
        "dispara execução, não escreve. Toda sugestão exposta está pendente "
        "de revisão humana — nada aqui representa ordem executada."
    ),
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ORIGEM_INTERFACE],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# --- Modelos de resposta ----------------------------------------------------

class PosicaoResposta(BaseModel):
    ticker: str
    tipo_ativo: str
    quantidade: int
    preco_medio: float = Field(description="Base de custo — nunca usada como valor")
    preco_mercado: float | None
    cotacao_em: dt.datetime | None
    motivo_sem_cotacao: str | None
    valor: float | None


class CarteiraResposta(BaseModel):
    posicoes: list[PosicaoResposta]
    total_patrimonio: float
    patrimonio_parcial: bool = Field(
        description="True quando alguma posição ficou sem cotação utilizável "
                    "— o total NÃO cobre a carteira inteira"
    )
    tickers_sem_cotacao: list[str]
    motivos_sem_cotacao: list[str]
    exposicao_pct_por_ativo: dict[str, float]


class CotacaoResposta(BaseModel):
    ticker: str
    preco: float | None
    coletado_em: dt.datetime | None
    tem_cotacao: bool


class SugestaoResposta(BaseModel):
    ticker_objeto: str
    tipo_operacao: str
    codigo_opcao: str | None
    strike: float | None
    vencimento: dt.date | None
    premio_estimado: float | None
    status: str
    criterios: dict = Field(description="Snapshot completo, com a base de valorização")
    pendente_revisao_humana: bool = Field(
        description="Sempre True: nenhuma sugestão é ordem executada"
    )


class MotivoDesfechoResposta(BaseModel):
    ticker_objeto: str
    motivo: str
    quantidade: int
    criterios_contagem: dict[str, int] = Field(
        description="A soma PODE exceder `quantidade`: opção reprovada em "
                    "dois critérios conta nos dois"
    )
    amostra: dict | None


class DesfechoResposta(BaseModel):
    executado_em: dt.datetime | None = Field(
        description="Momento da avaliação que produziu este desfecho — se "
                    "ela não rodou hoje, é de outro dia"
    )
    ha_registro: bool
    motivos: list[MotivoDesfechoResposta]


# --- Endpoints --------------------------------------------------------------

@app.get("/carteira", response_model=CarteiraResposta)
def carteira() -> CarteiraResposta:
    params = carregar_params()
    agora = dt.datetime.now(dt.timezone.utc)
    with get_connection() as conn, conn.cursor() as cur:
        visao = visao_carteira(cur, params, agora)
    return CarteiraResposta(
        posicoes=[PosicaoResposta(**vars(p)) for p in visao.posicoes],
        total_patrimonio=visao.total_patrimonio,
        patrimonio_parcial=visao.patrimonio_parcial,
        tickers_sem_cotacao=visao.tickers_sem_cotacao,
        motivos_sem_cotacao=visao.motivos_sem_cotacao,
        exposicao_pct_por_ativo=visao.exposicao_pct_por_ativo,
    )


@app.get("/cotacoes", response_model=list[CotacaoResposta])
def cotacoes() -> list[CotacaoResposta]:
    """Cotação mais recente de cada ativo cadastrado — inclusive os SEM
    cotação, representados explicitamente em vez de omitidos."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.ticker, c.preco, c.coletado_em
            FROM ativos a
            LEFT JOIN LATERAL (
                SELECT preco, coletado_em FROM cotacoes
                WHERE ticker = a.ticker ORDER BY coletado_em DESC LIMIT 1
            ) c ON TRUE
            ORDER BY a.ticker
            """
        )
        linhas = cur.fetchall()
    return [
        CotacaoResposta(
            ticker=t,
            preco=float(preco) if preco is not None else None,
            coletado_em=momento,
            tem_cotacao=preco is not None,
        )
        for t, preco, momento in linhas
    ]


@app.get("/sugestoes", response_model=list[SugestaoResposta])
def sugestoes() -> list[SugestaoResposta]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker_objeto, tipo_operacao, codigo_opcao, strike,
                   vencimento, premio_estimado, criterios_json, status
            FROM sugestoes ORDER BY gerado_em DESC
            """
        )
        linhas = cur.fetchall()
    respostas = []
    for tk, op, codigo, strike, venc, premio, criterios, status in linhas:
        if isinstance(criterios, str):
            criterios = json.loads(criterios)
        respostas.append(SugestaoResposta(
            ticker_objeto=tk, tipo_operacao=op, codigo_opcao=codigo,
            strike=float(strike) if strike is not None else None,
            vencimento=venc,
            premio_estimado=float(premio) if premio is not None else None,
            status=status, criterios=criterios or {},
            pendente_revisao_humana=True,
        ))
    return respostas


@app.get("/desfecho", response_model=DesfechoResposta)
def desfecho(data: dt.date | None = None) -> DesfechoResposta:
    """Desfecho da execução mais recente do dia — por que (não) saiu
    sugestão. Lê o registro que a avaliação gravou; NÃO roda a avaliação."""
    data = data or dt.datetime.now(dt.timezone.utc).date()
    linhas = ultima_execucao_do_dia(data)
    executado_em = None
    if linhas:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(executado_em) FROM desfecho_avaliacao "
                "WHERE executado_em::date = %s",
                (data,),
            )
            executado_em = cur.fetchone()[0]
    return DesfechoResposta(
        executado_em=executado_em,
        ha_registro=bool(linhas),
        motivos=[
            MotivoDesfechoResposta(
                ticker_objeto=l.ticker_objeto, motivo=l.motivo,
                quantidade=l.quantidade,
                criterios_contagem=l.criterios_contagem or {},
                amostra=l.amostra,
            )
            for l in linhas
        ],
    )
