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
from src.fiscal.calculo import avaliar_operacao, carregar_tributos
from src.pregao import execucao as execucao_pregao
from src.pregao.calendario import CalendarioInvalido, carregar as carregar_calendario
from src.market.valuation import (
    carregar_params,
    cotacao_vigente,
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


class CanalColetaResposta(BaseModel):
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


class ExecucaoResposta(BaseModel):
    """Um disparo do pipeline de pregão (`execucao_pipeline`, migração 007)."""

    id: int
    iniciado_em: dt.datetime
    encerrado_em: dt.datetime | None = Field(
        default=None,
        description="NULL com status='executando' é o rastro de um processo "
                    "que morreu no meio — a linha abre ANTES do trabalho",
    )
    status: str = Field(
        description="executando | executado | pulado_fora_de_pregao | falhou"
    )
    gatilho: str
    duracao_s: float | None = None
    detalhe: dict = Field(
        default_factory=dict,
        description="Resumo por etapa: janela, orçamento, avaliação; erro e "
                    "traceback quando o status é 'falhou'",
    )


class CalendarioPregaoResposta(BaseModel):
    """Estado do calendário que decide se há pregão.

    `anos_derivados` existe porque derivado não pode passar por conferido: as
    datas funcionam, mas não foram batidas contra a fonte oficial — a mesma
    distinção que `earnings` faz entre estimado e confirmado.
    """

    vigencia_de: dt.date
    vigencia_ate: dt.date
    conferido_em: dt.date | None
    anos_conferidos: list[int]
    anos_derivados: list[int]
    fonte: str
    erro: str | None = Field(
        default=None,
        description="Preenchido quando o arquivo não pôde ser lido. Nesse "
                    "estado NENHUM disparo roda: sem calendário não há como "
                    "distinguir dia útil de feriado",
    )


class AutomacaoResposta(BaseModel):
    """Execução automática do pipeline — o que `rastreia_falhas` não cobre.

    Diferente das coletas acima, aqui a falha É registrada: cada disparo grava
    uma linha antes de começar e a fecha com o desfecho. É o que permite
    distinguir "pulou porque não era pregão" de "quebrou" de "nunca rodou".
    """

    disponivel: bool = Field(
        description="False quando a migração 007 não foi aplicada neste banco"
    )
    rodou_hoje: bool
    ultima: ExecucaoResposta | None = None
    recentes: list[ExecucaoResposta] = Field(default_factory=list)
    interrompidas: list[ExecucaoResposta] = Field(
        default_factory=list,
        description="Abertas há mais de uma hora e nunca encerradas: "
                    "processos mortos no meio (OOM, kill, máquina desligada)",
    )
    calendario: CalendarioPregaoResposta | None = None


class SaudeColetaResposta(BaseModel):
    """Saúde da coleta, derivada do dado que já existe.

    Para as COLETAS este recurso não é um log: o projeto não grava tentativa
    nem erro por fonte, então ele responde "quando cada fonte entregou dado
    pela última vez", que é o que o banco sabe. Para a EXECUÇÃO do pipeline
    de pregão, `automacao` é um log de verdade — ver `AutomacaoResposta`.
    """

    coletas: list[CanalColetaResposta]
    orcamento: OrcamentoResposta
    ultima_avaliacao_em: dt.datetime | None
    automacao: AutomacaoResposta
    rastreia_falhas: bool = Field(
        default=False,
        description="Sempre False, e é sobre as COLETAS: nada registra falha "
                    "por fonte. Fonte sem entrega recente pode estar quebrada "
                    "OU apenas sem novidade, e o banco não distingue os dois. "
                    "A execução do pipeline, essa sim, é rastreada em "
                    "`automacao` — não confunda os dois escopos",
    )


class EnriquecimentoItemResposta(BaseModel):
    """Contexto quantitativo de UMA opção. Todo número é opcional: `None`
    quer dizer "não deu para calcular", e `ressalvas` diz por quê."""

    codigo_opcao: str
    ticker_objeto: str
    tipo: str | None = None
    strike: float | None = None
    vencimento: dt.date | None = None
    #: Preço coletado do provedor. Fica ao lado do teórico de propósito: a
    #: leitura útil é a DIFERENÇA entre os dois, e obrigar quem lê a buscar
    #: o preço noutra tela é o que faz ninguém comparar.
    preco_mercado: float | None = None
    preco_teorico: float | None = None
    delta_modelo: float | None = Field(
        default=None,
        description="Delta do MODELO. Não confundir com `opcoes.delta`, que "
                    "vem do provedor e é o que o critério de gate consome",
    )
    gamma: float | None = None
    theta_dia: float | None = Field(default=None, description="Por dia corrido")
    vega_pp: float | None = Field(default=None, description="Por ponto percentual de vol")
    rho_pp: float | None = Field(default=None, description="Por ponto percentual de juro")
    prob_exercicio_vencimento: float | None = Field(
        default=None,
        description="Risco-neutra, SÓ no vencimento — não inclui exercício "
                    "antecipado em contrato americano",
    )
    iv_percentil_252d: float | None = None
    skew_vs_cadeia: float | None = None
    volatilidade_usada: float | None = None
    estilo_exercicio: str | None = None
    ressalvas: list[str] = Field(default_factory=list)


class EnriquecimentoResposta(BaseModel):
    """Contexto quantitativo da última execução da avaliação.

    NÃO é critério. Os números aqui não aprovaram nem reprovaram nada — quem
    decide é `criterios_json`, em `/sugestoes` e `/desfecho`. A separação é a
    razão de existir um recurso próprio: misturar os dois faria um número de
    contexto parecer um critério que alguém precisou passar.
    """

    disponivel: bool = Field(
        description="False quando a migração 008 não foi aplicada neste banco"
    )
    executado_em: dt.datetime | None = None
    modelo: str | None = Field(
        default=None, description="Ex.: 'CRR-binomial-1024'"
    )
    taxa_livre_risco: float | None = Field(
        default=None, description="Fração ao ano usada no desconto"
    )
    taxa_observada_em: dt.date | None = None
    itens: list[EnriquecimentoItemResposta] = Field(default_factory=list)


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


class PernaResposta(BaseModel):
    nome: str
    resultado_bruto: float
    custos: float
    aliquota_pct: float
    imposto: float
    resultado_liquido: float


class CenarioResposta(BaseModel):
    """Desfecho hipotético de uma operação AINDA ABERTA.

    Não é previsão de preço: é aritmética sobre o que aconteceria se a
    opção terminasse de cada jeito, com os números que já existem.
    """

    nome: str
    descricao: str
    resultado_liquido: float


class OperacaoResposta(BaseModel):
    posicao_id: int
    codigo: str
    ticker_objeto: str | None
    quantidade: int = Field(description="Negativo = lançada. Em opções, não contratos")
    premio_unitario: float
    strike: float | None
    vencimento: dt.date | None
    dias_para_vencimento: int | None
    aberta_em: dt.datetime
    fechada_em: dt.datetime | None
    motivo_fechamento: str | None
    preco_fechamento: float | None

    #: Cotação do ATIVO-OBJETO. A da opção não existe: o ETL de opções está
    #: bloqueado no plano Free da Brapi, então não há marcação a mercado da
    #: opção — e a tela não finge que há.
    preco_objeto: float | None
    distancia_do_strike_pct: float | None = Field(
        description="Quanto o objeto está acima (+) ou abaixo (−) do strike. "
                    "É a pergunta central da venda coberta"
    )
    dentro_do_dinheiro: bool | None

    resultado_bruto: float
    custos: float
    imposto: float
    resultado_liquido: float
    pernas: list[PernaResposta]
    cenarios: list[CenarioResposta]
    estimativa: bool = Field(
        default=True,
        description="Sempre True: é estimativa por operação, não apuração "
                    "fiscal — a real é mensal e consolida operações",
    )
    ressalvas: list[str]


class OperacoesResposta(BaseModel):
    operacoes: list[OperacaoResposta]
    tem_cotacao_de_opcao: bool = Field(
        description="False enquanto o ETL de opções estiver bloqueado: sem "
                    "ele não há marcação a mercado da posição em opção"
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


def _float(valor) -> float | None:
    """`NUMERIC` do Postgres chega como `Decimal`; Pydantic aceita, mas o
    JSON sairia como string. Preserva `None` — que aqui significa "não deu
    para calcular", não zero."""
    return float(valor) if valor is not None else None


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


@app.get("/saude-coleta", response_model=SaudeColetaResposta)
def saude_coleta() -> SaudeColetaResposta:
    """Quando cada fonte entregou dado pela última vez, e quanto do
    orçamento diário de requests já foi gasto.

    NÃO é um log de execução — o projeto não grava tentativa, erro nem
    duração em lugar nenhum. Por isso a resposta carrega
    `rastreia_falhas=False`: ausência de entrega recente aqui significa
    "não gravou nada", que pode ser fonte quebrada ou simplesmente dia sem
    novidade, e o banco não sabe qual dos dois.
    """
    hoje = dt.datetime.now(dt.timezone.utc).date()
    coletas: list[CanalColetaResposta] = []

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
                coletas.append(CanalColetaResposta(
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
            coletas.append(CanalColetaResposta(
                canal="resultados", fonte=provedor, ultima_entrega_em=ultima,
                registros_hoje=hoje_qtd, ja_entregou=ultima is not None,
            ))

        cur.execute("SELECT MAX(executado_em) FROM desfecho_avaliacao")
        ultima_avaliacao = cur.fetchone()[0]

        limite = get_settings().brapi_requests_dia_maximo
        gastos = requests_gastos_hoje(cur)

        automacao = _automacao(cur, hoje)

    return SaudeColetaResposta(
        coletas=coletas,
        orcamento=OrcamentoResposta(
            fonte="brapi",
            limite_diario=limite,
            gastos_hoje=gastos,
            restante_hoje=max(0, limite - gastos),
        ),
        ultima_avaliacao_em=ultima_avaliacao,
        automacao=automacao,
    )


def _calendario_resposta() -> CalendarioPregaoResposta | None:
    """Estado do calendário de pregão, ou o erro que impede lê-lo.

    Nunca deixa a exceção subir: este endpoint é justamente o que se abre
    para descobrir o que está quebrado, e um 500 aqui apagaria a resposta
    junto com a pergunta.
    """
    try:
        cal = carregar_calendario()
    except CalendarioInvalido as e:
        return CalendarioPregaoResposta(
            vigencia_de=dt.date.min, vigencia_ate=dt.date.min,
            conferido_em=None, anos_conferidos=[], anos_derivados=[],
            fonte="", erro=str(e),
        )
    anos = range(cal.vigencia_de.year, cal.vigencia_ate.year + 1)
    return CalendarioPregaoResposta(
        vigencia_de=cal.vigencia_de,
        vigencia_ate=cal.vigencia_ate,
        conferido_em=cal.conferido_em,
        anos_conferidos=sorted(cal.anos_conferidos),
        anos_derivados=sorted(a for a in anos if a not in cal.anos_conferidos),
        fonte=cal.fonte,
    )


def _automacao(cur, hoje: dt.date) -> AutomacaoResposta:
    """Estado da execução automática, tolerante a banco sem a migração 007.

    A tolerância não é defensividade gratuita: o banco gerenciado já esteve
    atrás das migrações, e é exatamente nesse estado que alguém abre esta
    tela para entender por que a automação não aparece. Devolver
    `disponivel=False` responde; um 500 não.
    """
    cur.execute("SELECT to_regclass('public.execucao_pipeline')")
    if cur.fetchone()[0] is None:
        return AutomacaoResposta(disponivel=False, rodou_hoje=False)

    recentes = [ExecucaoResposta(**e) for e in execucao_pregao.ultimas(20, cur=cur)]
    return AutomacaoResposta(
        disponivel=True,
        rodou_hoje=execucao_pregao.rodou_em(hoje, cur=cur),
        ultima=(
            ExecucaoResposta(**u)
            if (u := execucao_pregao.ultima_conclusao(cur=cur))
            else None
        ),
        recentes=recentes,
        interrompidas=[
            ExecucaoResposta(**e) for e in execucao_pregao.orfas(minutos=60, cur=cur)
        ],
        calendario=_calendario_resposta(),
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


def _cenarios_da_operacao(
    quantidade: int, premio: float, strike: float | None,
    preco_medio_acao: float | None, tributos: dict,
) -> list[CenarioResposta]:
    """Os dois desfechos de uma call lançada em aberto.

    Existe porque a pergunta "como está indo" não tem resposta em dinheiro
    realizado enquanto a operação está aberta — e inventar uma marcação a
    mercado sem cotação de opção seria estimar valor, proibido pela regra 1
    do projeto. O que dá para responder honestamente é: quanto sobra em
    cada final possível.
    """
    cenarios = []

    expira = avaliar_operacao(
        quantidade=quantidade, premio_unitario=premio,
        motivo_fechamento="expirada", preco_fechamento=None,
        strike=strike, preco_medio_acao=preco_medio_acao, params=tributos,
    )
    cenarios.append(CenarioResposta(
        nome="expira sem exercício",
        descricao="a opção vira pó e o prêmio fica inteiro",
        resultado_liquido=expira.resultado_liquido,
    ))

    if strike is not None and preco_medio_acao is not None:
        exercida = avaliar_operacao(
            quantidade=quantidade, premio_unitario=premio,
            motivo_fechamento="exercida", preco_fechamento=None,
            strike=strike, preco_medio_acao=preco_medio_acao, params=tributos,
        )
        cenarios.append(CenarioResposta(
            nome="exercida",
            descricao="as ações são entregues ao strike; soma o prêmio ao "
                      "resultado da venda",
            resultado_liquido=exercida.resultado_liquido,
        ))
    return cenarios


@app.get("/operacoes", response_model=OperacoesResposta)
def operacoes() -> OperacoesResposta:
    """Operações de opção — abertas e encerradas — com resultado estimado.

    NÃO há marcação a mercado da opção: o ETL de opções está bloqueado no
    plano Free do provedor e `opcoes` fica vazia. O que se usa é a cotação
    do ATIVO-OBJETO, que responde a pergunta central da venda coberta ("a
    ação passou do strike?") sem precisar do preço da opção. A resposta
    declara esse limite em `tem_cotacao_de_opcao`.
    """
    params = carregar_params()
    tributos = carregar_tributos()

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, ticker, ticker_objeto, quantidade, preco_medio, strike,
                   vencimento, aberta_em, fechada_em, motivo_fechamento,
                   preco_fechamento
            FROM posicoes
            WHERE tipo_ativo = 'OPCAO'
            ORDER BY fechada_em NULLS FIRST, vencimento NULLS LAST, ticker
            """
        )
        linhas = cur.fetchall()

        # Preço médio da ação por objeto: é a base da perna de ação quando a
        # call é exercida.
        cur.execute(
            """
            SELECT ticker,
                   SUM(quantidade * preco_medio) / NULLIF(SUM(quantidade), 0)
            FROM posicoes
            WHERE tipo_ativo = 'ACAO' AND fechada_em IS NULL
            GROUP BY ticker
            """
        )
        preco_medio_por_ticker = {t: float(p) for t, p in cur.fetchall() if p is not None}

        cur.execute("SELECT COUNT(*) FROM opcoes")
        tem_cotacao_de_opcao = cur.fetchone()[0] > 0

        objetos = {l[2] for l in linhas if l[2]}
        cotacao_por_objeto = {}
        for objeto in objetos:
            vigente = cotacao_vigente(cur, objeto, params)
            cotacao_por_objeto[objeto] = vigente.preco if vigente.utilizavel else None

    hoje = dt.date.today()
    respostas = []
    for (pid, codigo, objeto, qtd, premio, strike, venc, aberta, fechada,
         motivo, preco_fech) in linhas:
        premio = float(premio)
        strike = float(strike) if strike is not None else None
        preco_fech = float(preco_fech) if preco_fech is not None else None
        preco_objeto = cotacao_por_objeto.get(objeto)
        preco_medio_acao = preco_medio_por_ticker.get(objeto)

        resultado = avaliar_operacao(
            quantidade=qtd, premio_unitario=premio, motivo_fechamento=motivo,
            preco_fechamento=preco_fech, strike=strike,
            preco_medio_acao=preco_medio_acao, params=tributos,
        )

        distancia = None
        dentro = None
        if strike and preco_objeto is not None:
            distancia = (preco_objeto - strike) / strike * 100
            dentro = preco_objeto > strike

        respostas.append(OperacaoResposta(
            posicao_id=pid, codigo=codigo, ticker_objeto=objeto,
            quantidade=qtd, premio_unitario=premio, strike=strike,
            vencimento=venc,
            dias_para_vencimento=(venc - hoje).days if venc else None,
            aberta_em=aberta, fechada_em=fechada, motivo_fechamento=motivo,
            preco_fechamento=preco_fech,
            preco_objeto=preco_objeto,
            distancia_do_strike_pct=distancia,
            dentro_do_dinheiro=dentro,
            resultado_bruto=resultado.resultado_bruto,
            custos=resultado.custos,
            imposto=resultado.imposto,
            resultado_liquido=resultado.resultado_liquido,
            pernas=[
                PernaResposta(
                    nome=p.nome, resultado_bruto=p.resultado_bruto,
                    custos=p.custos, aliquota_pct=p.aliquota_pct,
                    imposto=p.imposto, resultado_liquido=p.resultado_liquido,
                )
                for p in resultado.pernas
            ],
            cenarios=(
                _cenarios_da_operacao(qtd, premio, strike, preco_medio_acao, tributos)
                if motivo is None else []
            ),
            ressalvas=resultado.ressalvas,
        ))

    return OperacoesResposta(
        operacoes=respostas, tem_cotacao_de_opcao=tem_cotacao_de_opcao
    )


@app.get("/enriquecimento", response_model=EnriquecimentoResposta)
def enriquecimento() -> EnriquecimentoResposta:
    """Contexto quantitativo da última execução da avaliação.

    Uma execução por vez, não a união do dia: rodar de novo SUBSTITUI a
    leitura. Somar rodadas mostraria a mesma opção duas vezes com números
    ligeiramente diferentes, e ninguém saberia qual é a de agora — é a mesma
    razão de `ultima_execucao_do_dia` existir no desfecho.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.enriquecimento_quant')")
        if cur.fetchone()[0] is None:
            return EnriquecimentoResposta(disponivel=False)

        cur.execute("SELECT MAX(executado_em) FROM enriquecimento_quant")
        linha = cur.fetchone()
        executado_em = linha[0] if linha else None
        if executado_em is None:
            return EnriquecimentoResposta(disponivel=True)

        # O preço de mercado da opção vem de `opcoes`, na coleta mais
        # recente: o valor da tela é a DIFERENÇA contra o teórico, e obrigar
        # quem lê a cruzar duas telas é o que faz ninguém comparar.
        cur.execute(
            """
            SELECT e.codigo_opcao, e.ticker_objeto, o.tipo, o.strike,
                   o.vencimento, o.preco, e.preco_teorico, e.delta_modelo,
                   e.gamma, e.theta_dia, e.vega_pp, e.rho_pp,
                   e.prob_exercicio_vencimento, e.iv_percentil_252d,
                   e.skew_vs_cadeia, e.volatilidade_usada, e.estilo_exercicio,
                   e.ressalvas, e.modelo, e.taxa_livre_risco, e.taxa_observada_em
            FROM enriquecimento_quant e
            LEFT JOIN (
                SELECT DISTINCT ON (codigo) codigo, tipo, strike, vencimento, preco
                FROM opcoes ORDER BY codigo, coletado_em DESC
            ) o ON o.codigo = e.codigo_opcao
            WHERE e.executado_em = %s
            ORDER BY e.ticker_objeto, o.strike NULLS LAST, e.codigo_opcao
            """,
            (executado_em,),
        )
        linhas = cur.fetchall()

    itens = [
        EnriquecimentoItemResposta(
            codigo_opcao=r[0], ticker_objeto=r[1], tipo=r[2],
            strike=_float(r[3]), vencimento=r[4], preco_mercado=_float(r[5]),
            preco_teorico=_float(r[6]), delta_modelo=_float(r[7]),
            gamma=_float(r[8]), theta_dia=_float(r[9]), vega_pp=_float(r[10]),
            rho_pp=_float(r[11]), prob_exercicio_vencimento=_float(r[12]),
            iv_percentil_252d=_float(r[13]), skew_vs_cadeia=_float(r[14]),
            volatilidade_usada=_float(r[15]), estilo_exercicio=r[16],
            ressalvas=list(r[17] or []),
        )
        for r in linhas
    ]
    primeira = linhas[0] if linhas else None
    return EnriquecimentoResposta(
        disponivel=True,
        executado_em=executado_em,
        modelo=primeira[18] if primeira else None,
        taxa_livre_risco=_float(primeira[19]) if primeira else None,
        taxa_observada_em=primeira[20] if primeira else None,
        itens=itens,
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
