"""API da carteira, para a interface web consumir.

TRÊS LIMITES, POR CONSTRUÇÃO
----------------------------
1. **Não decide.** Todo critério de estratégia é determinístico e mora em
   `src/strategy/`; aqui só se serializa o que o domínio já concluiu.
   Nenhum cálculo de valorização, exposição ou risco acontece neste módulo.
2. **Não dispara.** Nenhum endpoint roda ETL, avaliação, consolidação ou
   relatório. A API lê o que a execução anterior gravou — inclusive o
   desfecho da avaliação, que desde a change `persist-evaluation-outcomes`
   sobrevive ao processo.
3. **Não manda ordem.** Nada aqui fala com corretora. O sistema inteiro é
   de sugestão para revisão humana e a API não é exceção.

ESTE MÓDULO NÃO ESCREVE — E ISSO É TESTADO
------------------------------------------
Todo endpoint definido AQUI é somente leitura, e o guardrail `_sem_escrita`
de `tests/test_api_read.py` varre as queries executadas para provar isso.

A escrita da carteira (cadastro de ativo, registro e encerramento de
posição) mora em `src/api/escrita.py`, montada no mesmo app por um router
separado. O invariante antigo dizia "a API não escreve"; ele foi revisado
quando a interface passou a substituir as CLIs de entrada manual, que é o
propósito declarado do repositório `opcoes-ia-web`. A separação por módulo
é o que mantém a garantia de leitura auditável — ver o cabeçalho de
`escrita.py` para o raciocínio completo.

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

from src.api.escrita import router as escrita_router
from src.config import get_settings
from src.db.connection import get_connection
from src.earnings.models import faixa_de_confianca
from src.etl.budget import requests_gastos_hoje
from src.market.valuation import (
    carregar_params,
    frescor_maximo_horas,
    visao_carteira,
)
from src.strategy.covered import politica_resultado_desconhecido
from src.strategy.outcome_repository import ultima_execucao_do_dia

#: Origem do dev server do Vite. Configurável, mas nunca "*": inofensivo em
#: localhost hoje, perigoso no dia em que alguém publicar sem revisar.
ORIGEM_INTERFACE = os.getenv("OPCOES_IA_WEB_ORIGIN", "http://localhost:5173")

app = FastAPI(
    title="opcoes-ia — carteira",
    description=(
        "Superfície para a interface própria. Não decide, não dispara "
        "execução e não manda ordem. A leitura é auditada como somente "
        "leitura; a escrita é limitada a escrituração da carteira "
        "(cadastro de ativo e registro de posição que o usuário já tem). "
        "Toda sugestão exposta está pendente de revisão humana."
    ),
    version="0.2.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ORIGEM_INTERFACE],
    # POST entrou com a escrituração da carteira. Continua sem DELETE:
    # encerrar posição é UPDATE em `fechada_em`, porque o histórico é o que
    # permite explicar uma decisão passada meses depois.
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(escrita_router)


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


class FonteResultadoResposta(BaseModel):
    """O que UMA fonte afirmou sobre a data, preservado como veio.

    Linhas perdedoras de um conflito continuam aqui: são o rastro que
    responde "por que o sistema achava isso?" meses depois.
    """

    provedor: str
    data_reportada: dt.date | None
    status: str | None
    confianca: int
    obtida_em: dt.datetime
    url: str | None


class EventoResultadoResposta(BaseModel):
    ticker: str
    empresa: str | None
    periodo_fiscal: str
    data_efetiva: dt.date | None = Field(
        description="A confirmada quando existe, senão a estimada — é esta "
                    "que o motor de opções consulta"
    )
    data_estimada: dt.date | None
    data_confirmada: dt.date | None = Field(
        description="Coluna separada da estimada de propósito: manter as "
                    "duas preserva a discordância em vez de apagá-la"
    )
    hora_efetiva: dt.time | None
    sessao: str = Field(
        description="UNKNOWN não é ausência a ignorar — é estado que AMPLIA "
                    "a janela de risco"
    )
    status: str
    confianca: int
    faixa_confianca: str
    confirmado: bool
    conflitos: list = Field(
        description="Divergências entre fontes, preservadas em vez de "
                    "resolvidas em silêncio"
    )
    atualizado_em: dt.datetime
    fontes: list[FonteResultadoResposta]


class PendenteConsolidacaoResposta(BaseModel):
    """Data que o usuário registrou e que NUNCA virou evento consultável.

    Registrar não é consolidar: `earnings.manage add` grava o que o usuário
    leu no site de RI, e só `earnings.ingest` promove aquilo para
    `earnings_events`. Sem o segundo passo a data existe no banco e a
    avaliação segue bloqueada — a armadilha mais cara deste fluxo, e por
    isso ela é exposta como estado próprio em vez de ficar invisível.
    """

    ticker: str
    periodo_fiscal: str
    data_resultado: dt.date
    sessao: str
    origem: str | None
    registrado_em: dt.datetime
    comando_para_consolidar: str = Field(
        description="O comando exato que promove esta entrada a evento"
    )


class ResultadosResposta(BaseModel):
    eventos: list[EventoResultadoResposta]
    pendentes_consolidacao: list[PendenteConsolidacaoResposta]
    politica_resultado_desconhecido: str = Field(
        description="O que a avaliação faz sem data confiável: `bloquear` "
                    "(padrão, conservador) ou `sinalizar`. Reprovação em "
                    "critério de mercado sempre vence a política"
    )


class ColetaResposta(BaseModel):
    canal: str = Field(description="O que é coletado: cotações, opções, notícias, resultados")
    fonte: str
    ultima_entrega_em: dt.datetime | None = Field(
        description="Última vez que esta fonte GRAVOU dado. Não é 'última "
                    "tentativa': uma falha não deixa rastro no banco"
    )
    registros_hoje: int
    ja_entregou: bool


class OrcamentoResposta(BaseModel):
    fonte: str
    limite_diario: int
    gastos_hoje: int
    restante_hoje: int
    e_aproximacao: bool = Field(
        default=True,
        description="Sempre True: não há tabela de contagem de requests. O "
                    "gasto é estimado pelas linhas gravadas hoje, o que "
                    "SUBESTIMA quando um request falha antes de gravar",
    )


class OperacaoResposta(BaseModel):
    """Saúde da coleta, derivada do dado que já existe.

    Este recurso NÃO é um log de execução: o projeto não grava tentativas,
    erros nem duração. Ele responde "quando cada fonte entregou dado pela
    última vez", que é o que o banco realmente sabe. `rastreia_falhas`
    declara esse limite no próprio contrato para que a interface não
    apresente silêncio como se fosse saúde.
    """

    coletas: list[ColetaResposta]
    orcamento: OrcamentoResposta
    ultima_avaliacao_em: dt.datetime | None
    rastreia_falhas: bool = Field(
        default=False,
        description="Sempre False: nada registra execução com erro. Fonte "
                    "sem entrega recente pode estar quebrada OU apenas sem "
                    "novidade — o banco não distingue os dois casos",
    )


class VelaResposta(BaseModel):
    abertura_em: dt.datetime = Field(
        description="INÍCIO do período, não o momento da coleta"
    )
    abertura: float
    maxima: float
    minima: float
    fechamento: float
    volume: int | None


class CandlesResposta(BaseModel):
    """Série de velas de um ticker, em ordem cronológica.

    `intervalo` volta na resposta de propósito: é o que permite a interface
    desenhar o eixo correto sem supor a granularidade. Trocar o ETL para
    coletar 15m passa a refletir aqui sem mudança no contrato.
    """

    ticker: str
    intervalo: str
    velas: list[VelaResposta]
    intervalos_disponiveis: list[str] = Field(
        description="Intervalos que já têm vela gravada para este ticker"
    )


class ParametrosResposta(BaseModel):
    """Parâmetros de `params.yaml` que a interface precisa para explicar o
    que mostra.

    Existem no contrato porque a alternativa é a interface duplicar os
    números e passar a mentir em silêncio quando eles mudarem aqui.
    """

    cotacao_frescor_maximo_horas: float = Field(
        description="Idade máxima da cotação para valer como preço de "
                    "mercado. Passou disso, a avaliação para como 'dado "
                    "insuficiente' — não existe fallback para preço médio"
    )
    politica_resultado_desconhecido: str


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


def _como_lista(valor) -> list:
    """`conflicts` é JSONB e chega como lista ou como string, dependendo do
    driver — mesma normalização já feita com `criterios_json`."""
    if valor is None:
        return []
    if isinstance(valor, str):
        return json.loads(valor) or []
    return list(valor)


@app.get("/resultados", response_model=ResultadosResposta)
def resultados() -> ResultadosResposta:
    """Calendário de divulgação de resultado por ativo.

    Duas coisas que este endpoint não faz, de propósito: não roda o
    `ingest` (a API não dispara) e não decide se a data é boa o bastante —
    quem faz isso é `EarningsRiskService`. Aqui se expõe o estado como ele
    está no banco, inclusive quando esse estado é "o usuário registrou e
    ninguém consolidou".
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, ticker, company_name, fiscal_period,
                   expected_date, confirmed_date, expected_time, confirmed_time,
                   session, status, confidence, conflicts, updated_at
            FROM earnings_events
            ORDER BY COALESCE(confirmed_date, expected_date) NULLS LAST, ticker
            """
        )
        eventos_linhas = cur.fetchall()

        # Uma query só para todas as fontes, agrupadas em memória: a
        # alternativa seria uma consulta por evento, e o volume aqui é de
        # dezenas de linhas — não de milhares.
        cur.execute(
            """
            SELECT event_id, provider, reported_date, status, confidence,
                   retrieved_at, source_url
            FROM earnings_event_sources
            ORDER BY event_id, retrieved_at DESC
            """
        )
        fontes_linhas = cur.fetchall()

        cur.execute(
            """
            SELECT m.ticker, m.fiscal_period, m.data_resultado, m.session,
                   m.origem, m.registrado_em
            FROM earnings_manual_entries m
            LEFT JOIN earnings_events e
                   ON e.ticker = m.ticker
                  AND e.fiscal_period = m.fiscal_period
            WHERE e.id IS NULL
            ORDER BY m.data_resultado, m.ticker
            """
        )
        pendentes_linhas = cur.fetchall()

    fontes_por_evento: dict[str, list[FonteResultadoResposta]] = {}
    for evento_id, provedor, data, status, conf, obtida, url in fontes_linhas:
        fontes_por_evento.setdefault(evento_id, []).append(
            FonteResultadoResposta(
                provedor=provedor, data_reportada=data, status=status,
                confianca=conf, obtida_em=obtida, url=url,
            )
        )

    eventos = []
    for (evento_id, ticker, empresa, periodo, estimada, confirmada,
         hora_est, hora_conf, sessao, status, confianca, conflitos,
         atualizado) in eventos_linhas:
        eventos.append(EventoResultadoResposta(
            ticker=ticker,
            empresa=empresa,
            periodo_fiscal=periodo,
            data_efetiva=confirmada or estimada,
            data_estimada=estimada,
            data_confirmada=confirmada,
            hora_efetiva=hora_conf or hora_est,
            sessao=sessao,
            status=status,
            confianca=confianca,
            faixa_confianca=faixa_de_confianca(confianca).value,
            confirmado=confirmada is not None,
            conflitos=_como_lista(conflitos),
            atualizado_em=atualizado,
            fontes=fontes_por_evento.get(evento_id, []),
        ))

    pendentes = [
        PendenteConsolidacaoResposta(
            ticker=ticker,
            periodo_fiscal=periodo,
            data_resultado=data,
            sessao=sessao,
            origem=origem,
            registrado_em=registrado,
            comando_para_consolidar=(
                f"python -m src.earnings.ingest --tickers {ticker}"
            ),
        )
        for ticker, periodo, data, sessao, origem, registrado in pendentes_linhas
    ]

    return ResultadosResposta(
        eventos=eventos,
        pendentes_consolidacao=pendentes,
        politica_resultado_desconhecido=politica_resultado_desconhecido(
            carregar_params()
        ),
    )


#: Canais de coleta e a tabela onde cada um deixa rastro. `noticias` usa
#: `coletado_em` (quando o ETL gravou), não `publicado_em` (quando o veículo
#: publicou) — a pergunta aqui é sobre a coleta, não sobre a notícia.
_CANAIS_COLETA = (
    ("cotações", "cotacoes"),
    ("opções", "opcoes"),
    ("notícias", "noticias"),
)


@app.get("/operacao", response_model=OperacaoResposta)
def operacao() -> OperacaoResposta:
    """Quando cada fonte entregou dado pela última vez, e quanto do
    orçamento diário de requests já foi gasto.

    NÃO é um log de execução — o projeto não grava tentativa, erro nem
    duração em lugar nenhum. Por isso a resposta carrega
    `rastreia_falhas=False`: ausência de entrega recente aqui significa
    "não gravou nada", que pode ser fonte quebrada ou simplesmente dia sem
    novidade, e o banco não sabe qual dos dois.
    """
    hoje = dt.datetime.now(dt.timezone.utc).date()
    coletas: list[ColetaResposta] = []

    with get_connection() as conn, conn.cursor() as cur:
        for canal, tabela in _CANAIS_COLETA:
            # Nome de tabela vem da constante acima, nunca de entrada do
            # usuário — não há parâmetro a interpolar neste endpoint.
            cur.execute(
                f"""
                SELECT fonte, MAX(coletado_em),
                       COUNT(*) FILTER (WHERE coletado_em::date = %s)
                FROM {tabela}
                GROUP BY fonte
                ORDER BY fonte
                """,
                (hoje,),
            )
            for fonte, ultima, hoje_qtd in cur.fetchall():
                coletas.append(ColetaResposta(
                    canal=canal, fonte=fonte, ultima_entrega_em=ultima,
                    registros_hoje=hoje_qtd, ja_entregou=ultima is not None,
                ))

        # Earnings tem provedores próprios (manual, cvm, yahoo) e o carimbo
        # de coleta é `retrieved_at`, não `coletado_em`.
        cur.execute(
            """
            SELECT provider, MAX(retrieved_at),
                   COUNT(*) FILTER (WHERE retrieved_at::date = %s)
            FROM earnings_event_sources
            GROUP BY provider
            ORDER BY provider
            """,
            (hoje,),
        )
        for provedor, ultima, hoje_qtd in cur.fetchall():
            coletas.append(ColetaResposta(
                canal="resultados", fonte=provedor, ultima_entrega_em=ultima,
                registros_hoje=hoje_qtd, ja_entregou=ultima is not None,
            ))

        cur.execute("SELECT MAX(executado_em) FROM desfecho_avaliacao")
        ultima_avaliacao = cur.fetchone()[0]

        limite = get_settings().brapi_requests_dia_maximo
        gastos = requests_gastos_hoje(cur)

    return OperacaoResposta(
        coletas=coletas,
        orcamento=OrcamentoResposta(
            fonte="brapi",
            limite_diario=limite,
            gastos_hoje=gastos,
            restante_hoje=max(0, limite - gastos),
        ),
        ultima_avaliacao_em=ultima_avaliacao,
    )


@app.get("/candles", response_model=CandlesResposta)
def candles(
    ticker: str,
    intervalo: str = "1h",
    limite: int = 200,
) -> CandlesResposta:
    """Velas OHLC de um ticker, mais antigas primeiro.

    O corte por `limite` é feito pelas MAIS RECENTES (ORDER BY DESC no
    subselect) e só depois reordenado para o desenho: pedir 200 velas de uma
    série de 5.000 precisa devolver as 200 últimas, não as 200 primeiras.
    """
    ticker = ticker.strip().upper()
    limite = max(1, min(limite, 2000))

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT abertura_em, abertura, maxima, minima, fechamento, volume
            FROM (
                SELECT abertura_em, abertura, maxima, minima, fechamento, volume
                FROM candles
                WHERE ticker = %s AND intervalo = %s
                ORDER BY abertura_em DESC
                LIMIT %s
            ) recentes
            ORDER BY abertura_em
            """,
            (ticker, intervalo, limite),
        )
        linhas = cur.fetchall()

        # Sem isto a interface não teria como oferecer troca de intervalo
        # sem tentar e errar.
        cur.execute(
            "SELECT DISTINCT intervalo FROM candles WHERE ticker = %s "
            "ORDER BY intervalo",
            (ticker,),
        )
        disponiveis = [r[0] for r in cur.fetchall()]

    return CandlesResposta(
        ticker=ticker,
        intervalo=intervalo,
        intervalos_disponiveis=disponiveis,
        velas=[
            VelaResposta(
                abertura_em=quando,
                abertura=float(a), maxima=float(h),
                minima=float(l), fechamento=float(c),
                volume=vol,
            )
            for quando, a, h, l, c, vol in linhas
        ],
    )


@app.get("/parametros", response_model=ParametrosResposta)
def parametros() -> ParametrosResposta:
    """Os parâmetros de `params.yaml` que a interface precisa citar.

    Sem isto a interface duplicaria a janela de frescor e a política de
    resultado desconhecido — e passaria a mentir em silêncio no dia em que
    esses valores mudassem aqui.
    """
    params = carregar_params()
    return ParametrosResposta(
        cotacao_frescor_maximo_horas=frescor_maximo_horas(params),
        politica_resultado_desconhecido=politica_resultado_desconhecido(params),
    )
