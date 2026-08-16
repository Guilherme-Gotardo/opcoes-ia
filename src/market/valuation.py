"""Valorização de posições a preço de mercado e cálculo de exposição
descoberta — o único lugar do projeto que traduz `cotacoes` em valor.

Existe porque `report/daily.py` e `strategy/covered.py` mantinham cada um a
sua própria noção de "valor da carteira", ambas sobre `preco_medio` (custo
de entrada). As duas divergiram do mercado ao mesmo tempo e ninguém notou
até um teste manual de ponta a ponta: o relatório mostrava R$ 14.250 contra
R$ 18.469 a mercado. Duas implementações da mesma conta é o formato do bug,
não um detalhe de organização.

DUAS REGRAS QUE ATRAVESSAM O MÓDULO
-----------------------------------
1. **Cotação ausente ou velha nunca vira número.** `cotacao_vigente`
   devolve um resultado explícito (`utilizavel` + `motivo`), no formato de
   `EarningsRiskService.avaliar()`, em vez de `float | None` mudo. Quem
   consome precisa saber *por que* não há valor, para poder dizer ao
   usuário. Cair para `preco_medio` seria estimar valor de mercado —
   proibido pela regra 1 do projeto.

2. **Exposição de operação coberta é só a parte descoberta.** Numa covered
   call o notional já está coberto pelas ações em carteira; contá-lo como
   exposição nova é contagem dupla, e era o que impedia qualquer covered
   call de passar no critério `exposicao_maxima_pct_ativo` numa carteira
   pequena. A cobertura é medida em CONTRATOS, não em reais: 100 ações
   cobrem 1 contrato independentemente da relação entre preço e strike.
"""
import datetime as dt
import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PARAMS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "covered-options-strategy" / "params.yaml"
)

#: Ações por contrato de opção na B3.
ACOES_POR_CONTRATO = 100

#: Janela de frescor padrão. 72h cobre sexta-fechamento → segunda-abertura
#: sem cotação nova, que é ausência de pregão, não dado velho. Feriado
#: prolongado estoura a janela — e parar nesse caso é o comportamento
#: correto, não uma falha.
DEFAULT_FRESCOR_HORAS = 72


class ParametroInvalido(ValueError):
    """Janela de frescor malformada em `params.yaml`."""


def carregar_params(path: Path | None = None) -> dict:
    """Carrega `params.yaml`, para quem só precisa da janela de frescor sem
    depender de `src.strategy` (mesmo padrão de `src/earnings/risk.py`)."""
    path = path or PARAMS_PATH
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _horas_positivas(params: dict, chave: str, padrao: float) -> float:
    """Lê uma janela de horas de `params.yaml`, com padrão declarado.

    Valor inválido falha alto em vez de cair no default: um fallback
    silencioso aqui mudaria a postura de risco sem o usuário perceber —
    mesma regra de `politica_resultado_desconhecido`.
    """
    if chave not in params:
        return float(padrao)
    valor = params[chave]
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ParametroInvalido(
            f"{chave} precisa ser um número de horas em params.yaml "
            f"(recebido: {valor!r})."
        )
    if valor <= 0 or math.isnan(valor) or math.isinf(valor):
        raise ParametroInvalido(
            f"{chave} precisa ser maior que zero e finito (recebido: {valor!r})."
        )
    return float(valor)


def frescor_maximo_horas(params: dict) -> float:
    """Janela de frescor da COTAÇÃO da ação."""
    return _horas_positivas(
        params, "cotacao_frescor_maximo_horas", DEFAULT_FRESCOR_HORAS
    )


def frescor_maximo_horas_opcao(params: dict) -> float:
    """Janela de frescor do DADO DA OPÇÃO (preço, delta, IV rank).

    Chave própria, e não a mesma da cotação, porque as duas grandezas
    envelhecem em ritmos diferentes: o preço da ação sobrevive a um fim de
    semana, enquanto delta e IV rank de uma opção mudam com o tempo até o
    vencimento mesmo sem negócio novo. Quem quiser uma janela mais curta
    para opção configura `opcao_frescor_maximo_horas` sem encurtar a da
    ação junto.

    O padrão é a janela da cotação: mudar a postura de risco por omissão
    seria pior do que a assimetria que este parâmetro corrige.
    """
    return _horas_positivas(
        params, "opcao_frescor_maximo_horas", frescor_maximo_horas(params)
    )


def idade_em_horas(
    momento: dt.datetime | None, agora: dt.datetime | None = None
) -> float | None:
    """Horas decorridas desde `momento`, ou `None` se não houver momento.

    Público porque a mesma conta é feita para cotação de ação e para dado de
    opção — duplicá-la abriria espaço para as duas divergirem no tratamento
    de fuso, que é exatamente onde esse tipo de bug mora.
    """
    if momento is None:
        return None
    agora = _como_utc(agora or dt.datetime.now(dt.timezone.utc))
    return (agora - _como_utc(momento)).total_seconds() / 3600


def _como_utc(momento: dt.datetime) -> dt.datetime:
    """Toda a convenção de timestamp do projeto é UTC (ver `schema.sql`).
    Um datetime ingênuo vindo de fixture ou de driver sem tzinfo é lido
    como UTC em vez de comparado com um aware — o que levantaria TypeError
    no meio do cálculo."""
    if momento.tzinfo is None:
        return momento.replace(tzinfo=dt.timezone.utc)
    return momento.astimezone(dt.timezone.utc)


@dataclass(frozen=True)
class CotacaoVigente:
    """Cotação de um ticker na visão de quem precisa decidir com ela.

    `utilizavel=False` significa "não temos preço confiável", nunca "o
    preço é zero". `motivo` é escrito para ser mostrado ao usuário: nomeia
    o ticker e a idade do dado.
    """

    ticker: str
    preco: float | None
    coletado_em: dt.datetime | None
    idade_horas: float | None
    utilizavel: bool
    motivo: str


def cotacao_vigente(
    cur, ticker: str, params: dict, agora: dt.datetime | None = None
) -> CotacaoVigente:
    """Última cotação do ticker, se estiver dentro da janela de frescor."""
    agora = _como_utc(agora or dt.datetime.now(dt.timezone.utc))
    limite_horas = frescor_maximo_horas(params)

    cur.execute(
        "SELECT preco, coletado_em FROM cotacoes WHERE ticker = %s "
        "ORDER BY coletado_em DESC LIMIT 1",
        (ticker,),
    )
    linha = cur.fetchone()
    if linha is None or linha[0] is None:
        return CotacaoVigente(
            ticker=ticker, preco=None, coletado_em=None, idade_horas=None,
            utilizavel=False,
            motivo=f"{ticker}: nenhuma cotação registrada",
        )

    preco, coletado_em = float(linha[0]), _como_utc(linha[1])
    idade_horas = (agora - coletado_em).total_seconds() / 3600
    if idade_horas > limite_horas:
        return CotacaoVigente(
            ticker=ticker, preco=None, coletado_em=coletado_em,
            idade_horas=idade_horas, utilizavel=False,
            motivo=(
                f"{ticker}: cotação de {idade_horas:.1f}h atrás, fora da "
                f"janela de {limite_horas:.0f}h "
                f"(coletada em {coletado_em.date().isoformat()})"
            ),
        )

    return CotacaoVigente(
        ticker=ticker, preco=preco, coletado_em=coletado_em,
        idade_horas=idade_horas, utilizavel=True,
        motivo=f"{ticker}: cotação de {idade_horas:.1f}h atrás",
    )


@dataclass
class PatrimonioMercado:
    """Patrimônio a mercado, com as posições que ficaram de fora explícitas.

    `parcial` existe para o relatório poder dizer que o total não cobre a
    carteira inteira. Um total que aparenta ser completo quando não é seria
    a mesma classe de erro que motivou esta valorização.
    """

    total: float = 0.0
    valor_por_ticker: dict[str, float] = field(default_factory=dict)
    #: `CotacaoVigente` não utilizável de cada ticker sem valorização.
    sem_cotacao: list[CotacaoVigente] = field(default_factory=list)

    @property
    def parcial(self) -> bool:
        return bool(self.sem_cotacao)

    @property
    def tickers_sem_cotacao(self) -> list[str]:
        return [c.ticker for c in self.sem_cotacao]


def _posicoes_acao(cur) -> list[tuple[str, int]]:
    cur.execute(
        "SELECT ticker, quantidade FROM posicoes "
        "WHERE tipo_ativo = 'ACAO' AND fechada_em IS NULL"
    )
    return [(t, int(q)) for t, q in cur.fetchall()]


def patrimonio_a_mercado(
    cur, params: dict, agora: dt.datetime | None = None
) -> PatrimonioMercado:
    """Patrimônio total a preço de mercado, somando APENAS posições em ação.

    Posições em opção ficam fora do total porque seu valor é derivado das
    mesmas ações já contadas — incluí-las seria a mesma contagem dupla que
    este módulo existe para remover, só que no denominador do percentual de
    exposição.
    """
    patrimonio = PatrimonioMercado()
    for ticker, quantidade in _posicoes_acao(cur):
        cotacao = cotacao_vigente(cur, ticker, params, agora)
        if not cotacao.utilizavel:
            patrimonio.sem_cotacao.append(cotacao)
            continue
        valor = abs(quantidade) * cotacao.preco
        patrimonio.valor_por_ticker[ticker] = (
            patrimonio.valor_por_ticker.get(ticker, 0.0) + valor
        )
        patrimonio.total += valor
    return patrimonio


def _calls_vendidas_abertas(cur, ticker_objeto: str) -> list[tuple[int, float]]:
    """Calls vendidas em aberto sobre o ativo: (contratos, strike).

    `DISTINCT ON (codigo)` porque `opcoes` guarda uma linha por coleta; o
    strike da série não muda, mas a junção duplicaria a posição.
    """
    cur.execute(
        """
        SELECT p.quantidade, o.strike
        FROM posicoes p
        JOIN (
            SELECT DISTINCT ON (codigo) codigo, ticker_objeto, tipo, strike
            FROM opcoes ORDER BY codigo, coletado_em DESC
        ) o ON o.codigo = p.ticker
        WHERE p.tipo_ativo = 'OPCAO' AND p.fechada_em IS NULL
          AND p.quantidade < 0 AND o.tipo = 'CALL' AND o.ticker_objeto = %s
        """,
        (ticker_objeto,),
    )
    return [(abs(int(q)), float(s)) for q, s in cur.fetchall()]


def _puts_vendidas_abertas(cur, ticker_objeto: str) -> list[tuple[int, float]]:
    cur.execute(
        """
        SELECT p.quantidade, o.strike
        FROM posicoes p
        JOIN (
            SELECT DISTINCT ON (codigo) codigo, ticker_objeto, tipo, strike
            FROM opcoes ORDER BY codigo, coletado_em DESC
        ) o ON o.codigo = p.ticker
        WHERE p.tipo_ativo = 'OPCAO' AND p.fechada_em IS NULL
          AND p.quantidade < 0 AND o.tipo = 'PUT' AND o.ticker_objeto = %s
        """,
        (ticker_objeto,),
    )
    return [(abs(int(q)), float(s)) for q, s in cur.fetchall()]


def acoes_em_carteira(cur, ticker_objeto: str) -> int:
    cur.execute(
        "SELECT COALESCE(SUM(quantidade), 0) FROM posicoes "
        "WHERE tipo_ativo = 'ACAO' AND fechada_em IS NULL AND ticker = %s",
        (ticker_objeto,),
    )
    return int(cur.fetchone()[0] or 0)


def cobertura_disponivel_em_contratos(cur, ticker_objeto: str) -> int:
    """Contratos que as ações ainda livres do ativo conseguem cobrir.

    Desconta as ações já comprometidas com calls vendidas em aberto: sem
    isso, duas calls sucessivas sobre o mesmo lote de 100 ações apareceriam
    ambas como cobertas — a segunda é descoberta e precisa contar.
    """
    acoes = acoes_em_carteira(cur, ticker_objeto)
    comprometidas = sum(
        contratos for contratos, _ in _calls_vendidas_abertas(cur, ticker_objeto)
    ) * ACOES_POR_CONTRATO
    livres = max(0, acoes - comprometidas)
    return livres // ACOES_POR_CONTRATO


def notional_descoberto(
    contratos: int, strike: float, cobertura_em_contratos: int
) -> float:
    """Notional da parte NÃO coberta da operação, com piso em zero.

    Uma covered call totalmente coberta devolve 0: a operação não adiciona
    risco direcional que a carteira já não carregue.
    """
    descobertos = max(0, contratos - max(0, cobertura_em_contratos))
    return descobertos * strike * ACOES_POR_CONTRATO


def cobertura_em_contratos_por_caixa(caixa: float | None, strike: float) -> int:
    """Contratos que o caixa/garantia informado cobre, para covered put."""
    if caixa is None or strike <= 0:
        return 0
    return int(caixa // (strike * ACOES_POR_CONTRATO))


# ---------------------------------------------------------------------------
# Visão de carteira por posição — extraída de `report/daily.py`.
#
# Era privada do relatório (`_resumo_carteira`, `_valorizar`); virou domínio
# público porque a API de leitura precisa dos MESMOS números. Uma segunda
# implementação da valorização por posição seria o formato exato do bug que
# este módulo existiu para corrigir: relatório e motor de estratégia com
# noções próprias de "valor da carteira", divergindo sem ninguém notar.
# ---------------------------------------------------------------------------

@dataclass
class PosicaoValorizada:
    """Uma posição aberta com sua valorização a mercado — ou o motivo de
    não ter. `preco_medio` é base de custo e nunca vira `valor`."""

    ticker: str
    tipo_ativo: str          # 'ACAO' | 'OPCAO'
    quantidade: int
    preco_medio: float
    preco_mercado: float | None = None
    cotacao_em: dt.datetime | None = None
    motivo_sem_cotacao: str | None = None
    valor: float | None = None


@dataclass
class VisaoCarteira:
    """A carteira como relatório e API a apresentam.

    `patrimonio_parcial` existe para nenhum consumidor apresentar um total
    que aparente cobrir a carteira inteira quando não cobre.
    """

    posicoes: list[PosicaoValorizada] = field(default_factory=list)
    total_patrimonio: float = 0.0
    patrimonio_parcial: bool = False
    tickers_sem_cotacao: list[str] = field(default_factory=list)
    motivos_sem_cotacao: list[str] = field(default_factory=list)
    #: Quanto do PATRIMÔNIO está em cada ativo. Como o patrimônio conta só
    #: ação, o numerador também — as fatias somam 100%. Não mede exposição a
    #: opção: para isso existe `notional_descoberto_em_carteira`, com outra
    #: semântica (parte descoberta, não valor de posição).
    exposicao_pct_por_ativo: dict[str, float] = field(default_factory=dict)


def preco_opcao_vigente(cur, codigo: str) -> tuple[float | None, dt.datetime | None]:
    """Último preço coletado de uma opção, com o momento da coleta."""
    cur.execute(
        "SELECT preco, coletado_em FROM opcoes WHERE codigo = %s "
        "ORDER BY coletado_em DESC LIMIT 1",
        (codigo,),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return None, None
    return float(row[0]), row[1]


def _valorizar_posicao(
    cur, posicao: PosicaoValorizada, params: dict, agora: dt.datetime
) -> None:
    """Preenche preço de mercado e valor, ou o motivo de não ter.

    Nunca cai para `preco_medio`: valorizar custo como se fosse mercado é o
    bug que esta função existe para não repetir.
    """
    if posicao.tipo_ativo == "ACAO":
        cotacao = cotacao_vigente(cur, posicao.ticker, params, agora)
        preco, momento = cotacao.preco, cotacao.coletado_em
        motivo = None if cotacao.utilizavel else cotacao.motivo
    else:
        preco, momento = preco_opcao_vigente(cur, posicao.ticker)
        motivo = (
            None if preco is not None
            else f"{posicao.ticker}: nenhum preço de opção coletado"
        )

    posicao.preco_mercado = preco
    posicao.cotacao_em = momento
    posicao.motivo_sem_cotacao = motivo
    posicao.valor = None if preco is None else abs(posicao.quantidade) * preco


def visao_carteira(cur, params: dict, agora: dt.datetime) -> VisaoCarteira:
    """A carteira valorizada a mercado, posição a posição.

    Fonte ÚNICA para relatório e API — os dois precisam mostrar os mesmos
    números por construção, não por coincidência.
    """
    cur.execute(
        "SELECT ticker, tipo_ativo, quantidade, preco_medio FROM posicoes "
        "WHERE fechada_em IS NULL ORDER BY ticker"
    )
    posicoes = [
        PosicaoValorizada(ticker=t, tipo_ativo=ta, quantidade=q, preco_medio=float(p))
        for t, ta, q, p in cur.fetchall()
    ]
    for p in posicoes:
        _valorizar_posicao(cur, p, params, agora)

    # Só posição em AÇÃO entra no patrimônio: o valor de uma opção é derivado
    # das mesmas ações já contadas, e somar os dois é contagem dupla — a
    # mesma que inviabilizava o critério de exposição.
    acoes = [p for p in posicoes if p.tipo_ativo == "ACAO"]
    total = sum(p.valor for p in acoes if p.valor is not None)

    # O numerador cobre a MESMA coisa que o denominador: só ação.
    #
    # Antes somava também o valor das opções, com o total continuando
    # stock-only — numerador e denominador mediam coisas diferentes, e as
    # fatias podiam passar de 100%. Não era hipótese: o teste que descrevia
    # o comportamento afirmava exatamente `(4200 + 1,10) / 4200`.
    #
    # Pior, `_valorizar_posicao` usa `abs(quantidade)`, então uma call
    # LANÇADA entrava com valor positivo e INFLAVA a concentração do ativo
    # — o oposto do que uma venda coberta faz com a exposição. Ficou latente
    # só porque `opcoes` está vazia enquanto o ETL do provedor está
    # bloqueado; passaria a mentir no dia em que houvesse preço de opção.
    #
    # Isto NÃO é a exposição a opção — essa tem medida própria e outra
    # semântica (`notional_descoberto_em_carteira`, usada pelo critério de
    # estratégia). Aqui se responde "quanto do patrimônio está em cada
    # ativo", e o patrimônio é de ações.
    exposicao_por_ativo: dict[str, float] = {}
    for p in acoes:
        if p.valor is None:
            continue
        exposicao_por_ativo[p.ticker] = (
            exposicao_por_ativo.get(p.ticker, 0.0) + p.valor
        )

    return VisaoCarteira(
        posicoes=posicoes,
        total_patrimonio=total,
        patrimonio_parcial=any(p.valor is None for p in acoes),
        tickers_sem_cotacao=[p.ticker for p in acoes if p.valor is None],
        motivos_sem_cotacao=[
            p.motivo_sem_cotacao for p in posicoes if p.motivo_sem_cotacao
        ],
        exposicao_pct_por_ativo={
            objeto: (valor / total * 100 if total else 0.0)
            for objeto, valor in exposicao_por_ativo.items()
        },
    )


def notional_descoberto_em_carteira(cur, ticker_objeto: str) -> float:
    """Notional descoberto das posições em opção JÁ abertas do ativo.

    Só posição vendida entra: opção comprada é direito, não obrigação — o
    risco dela está limitado ao prêmio já pago, não a um notional.

    As ações disponíveis cobrem os strikes MAIS BAIXOS primeiro, deixando
    descobertos os de maior notional. É a alocação conservadora entre as
    possíveis, e é determinística — não depende da ordem em que o banco
    devolveu as linhas.

    Put vendida conta integralmente: o projeto ainda não tem fonte de
    caixa/garantia registrada, e tratar garantia desconhecida como
    cobertura seria assumir um dado que não existe.
    """
    contratos_cobriveis = acoes_em_carteira(cur, ticker_objeto) // ACOES_POR_CONTRATO

    descoberto = 0.0
    for contratos, strike in sorted(
        _calls_vendidas_abertas(cur, ticker_objeto), key=lambda x: x[1]
    ):
        cobertos = min(contratos, contratos_cobriveis)
        contratos_cobriveis -= cobertos
        descoberto += (contratos - cobertos) * strike * ACOES_POR_CONTRATO

    for contratos, strike in _puts_vendidas_abertas(cur, ticker_objeto):
        descoberto += contratos * strike * ACOES_POR_CONTRATO

    return descoberto
