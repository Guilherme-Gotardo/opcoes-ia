"""Insumo do relatório do agente: tudo que os módulos determinísticos já
decidiram, num objeto só.

O QUE ENTRA, E O QUE FICA DE FORA — DE PROPÓSITO
------------------------------------------------
Entra o **resultado** de cada critério: aprovado ou reprovado, com o valor
que foi comparado e o limiar que valia. Não entra o dado de mercado cru que
permitiria refazer a conta.

A diferença é o guarda-corpo da Fase 4. Se o agente recebesse IV rank, delta
e preço soltos, ele PODERIA reavaliar — e um modelo que pode reavaliar
eventualmente reavalia, discorda, e escreve "esta opção parece elegível
apesar de reprovada". Entregando só o veredito e os números que o
sustentaram, discordar exigiria contradizer um dado explícito na frente
dele, o que é muito mais difícil de acontecer por acidente.

O enriquecimento quantitativo entra inteiro, com as ressalvas: ele É
contexto por natureza, e as ressalvas são o que impede o agente de tratar um
`None` como zero.

NADA AQUI CHAMA LLM
-------------------
Só leitura do banco. É a mesma disciplina de `report/daily.py`: quem monta
o insumo não é quem escreve o texto.
"""
import datetime as dt
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from src.db.connection import get_connection
from src.market.valuation import visao_carteira
from src.strategy.covered import carregar_params
from src.strategy.outcome_repository import ultima_execucao_do_dia

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class InsumoRelatorio:
    """O que o agente recebe. Serializável, para ir direto no prompt."""

    data: str
    #: Carteira a mercado: quanto, em quê, e o que ficou sem cotação.
    patrimonio: dict[str, Any] = field(default_factory=dict)
    #: Sugestões elegíveis do dia, com os critérios que cada uma passou.
    sugestoes: list[dict[str, Any]] = field(default_factory=list)
    #: Por que as demais NÃO viraram sugestão, agregado por motivo.
    desfecho: list[dict[str, Any]] = field(default_factory=list)
    #: Contexto quantitativo por opção, com as ressalvas de cada número.
    enriquecimento: list[dict[str, Any]] = field(default_factory=list)
    #: Limiares vigentes, para o agente CITAR sem precisar deduzir.
    criterios_vigentes: dict[str, Any] = field(default_factory=dict)
    #: O que faltou para o dia ser completo — coleta velha, migração
    #: pendente, orçamento estourado. O agente precisa poder dizer "não sei"
    #: com precisão.
    lacunas: list[str] = field(default_factory=list)

    def como_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, default=str)

    @property
    def vazio(self) -> bool:
        """Sem sugestão e sem desfecho não houve avaliação — não há relatório
        a escrever, e gastar uma chamada de LLM para dizer isso é desperdício."""
        return not self.sugestoes and not self.desfecho


def _sugestoes(cur, data: dt.date) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT ticker_objeto, tipo_operacao, codigo_opcao, strike, vencimento,
               premio_estimado, criterios_json
        FROM sugestoes WHERE gerado_em::date = %s ORDER BY ticker_objeto
        """,
        (data,),
    )
    saida = []
    for ticker, tipo, codigo, strike, venc, premio, criterios in cur.fetchall():
        if isinstance(criterios, str):
            criterios = json.loads(criterios)
        saida.append({
            "ticker_objeto": ticker, "tipo_operacao": tipo,
            "codigo_opcao": codigo,
            "strike": float(strike) if strike is not None else None,
            "vencimento": str(venc) if venc else None,
            "premio_estimado": float(premio) if premio is not None else None,
            # O VEREDITO de cada critério, não o insumo dele.
            "criterios": (criterios or {}).get("criterios", []),
        })
    return saida


def _enriquecimento(
    cur, executado_em: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    cur.execute("SELECT to_regclass('public.enriquecimento_quant')")
    if cur.fetchone()[0] is None:
        return []
    if executado_em is None:
        cur.execute("SELECT MAX(executado_em) FROM enriquecimento_quant")
        linha = cur.fetchone()
        if not linha or linha[0] is None:
            return []
        executado_em = linha[0]
    cur.execute(
        """
        SELECT codigo_opcao, ticker_objeto, delta_modelo, gamma, theta_dia,
               vega_pp, preco_teorico, prob_exercicio_vencimento,
               iv_percentil_252d, skew_vs_cadeia, estilo_exercicio, ressalvas
        FROM enriquecimento_quant WHERE executado_em = %s
        ORDER BY ticker_objeto, codigo_opcao
        """,
        (executado_em,),
    )
    campos = ("codigo_opcao", "ticker_objeto", "delta_modelo", "gamma",
              "theta_dia", "vega_pp", "preco_teorico",
              "prob_exercicio_vencimento", "iv_percentil_252d",
              "skew_vs_cadeia", "estilo_exercicio", "ressalvas")
    return [
        {
            c: (float(v) if isinstance(v, (int, float)) or hasattr(v, "as_tuple") else v)
            for c, v in zip(campos, row)
        }
        for row in cur.fetchall()
    ]


def _criterios_vigentes(params: dict) -> dict[str, Any]:
    """Os limiares que valeram, para o agente CITAR em vez de deduzir.

    Sem isto ele escreveria "IV rank abaixo do mínimo" sem saber qual era o
    mínimo — ou pior, chutaria um número plausível.
    """
    interessam = (
        "iv_rank_minimo", "delta_min", "delta_max", "dias_vencimento_min",
        "dias_vencimento_max", "premio_minimo_pct", "premio_minimo_pct_ao_mes",
        "exposicao_maxima_pct_ativo", "dias_bloqueio_antes_resultado",
        "cotacao_frescor_maximo_horas", "opcao_frescor_maximo_horas",
        "politica_resultado_desconhecido",
    )
    return {k: params[k] for k in interessam if k in params}


def _lacunas(cur, patrimonio, sugestoes, desfecho, enriquecimento) -> list[str]:
    """O que impede o dia de ser completo.

    Existe para o agente poder dizer "não sei" com precisão em vez de
    silenciar — silêncio sobre uma lacuna é indistinguível de ausência dela.
    """
    lacunas = []
    if patrimonio.get("parcial"):
        sem = ", ".join(patrimonio.get("tickers_sem_cotacao") or [])
        lacunas.append(
            f"patrimônio a mercado incompleto: sem cotação utilizável para "
            f"{sem} — o denominador do critério de exposição está subestimado "
            "para TODAS as posições"
        )
    if not enriquecimento:
        cur.execute("SELECT to_regclass('public.enriquecimento_quant')")
        if cur.fetchone()[0] is None:
            lacunas.append(
                "contexto quantitativo indisponível: migração 008 não aplicada "
                "neste banco"
            )
        else:
            lacunas.append(
                "nenhum contexto quantitativo: não houve opção coletada para "
                "enriquecer"
            )
    if not sugestoes and desfecho:
        lacunas.append(
            "nenhuma sugestão elegível hoje — o desfecho abaixo diz por quê, "
            "motivo a motivo"
        )
    return lacunas


def coletar(
    data: dt.date | None = None, *, executado_em: dt.datetime | None = None,
) -> InsumoRelatorio:
    """Junta o insumo do dia. Só leitura."""
    data = data or dt.datetime.now(dt.timezone.utc).date()
    params = carregar_params()
    agora = dt.datetime.now(dt.timezone.utc)

    with get_connection() as conn, conn.cursor() as cur:
        visao = visao_carteira(cur, params, agora)
        patrimonio = {
            "total_a_mercado": visao.total_patrimonio,
            "parcial": visao.patrimonio_parcial,
            "tickers_sem_cotacao": list(visao.tickers_sem_cotacao),
            "motivos_sem_cotacao": list(visao.motivos_sem_cotacao),
            "exposicao_pct_por_ativo": dict(visao.exposicao_pct_por_ativo),
            "posicoes": [
                {
                    "ticker": p.ticker, "tipo_ativo": p.tipo_ativo,
                    "quantidade": p.quantidade,
                    # `preco_medio` é CUSTO e nunca vira valor de mercado —
                    # os dois viajam separados para o agente não somar um
                    # pelo outro ao escrever.
                    "preco_medio_custo": p.preco_medio,
                    "preco_mercado": p.preco_mercado,
                    "valor_a_mercado": p.valor,
                    "motivo_sem_cotacao": p.motivo_sem_cotacao,
                }
                for p in visao.posicoes
            ],
        }
        sugestoes = _sugestoes(cur, data)
        enriquecimento = _enriquecimento(cur, executado_em)
        desfecho_linhas = ultima_execucao_do_dia(data)
        desfecho = [
            {
                "ticker_objeto": linha.ticker_objeto, "motivo": linha.motivo,
                "quantidade": linha.quantidade,
                "criterios_contagem": linha.criterios_contagem,
            }
            for linha in desfecho_linhas
        ]
        lacunas = _lacunas(cur, patrimonio, sugestoes, desfecho, enriquecimento)

    return InsumoRelatorio(
        data=data.isoformat(),
        patrimonio=patrimonio,
        sugestoes=sugestoes,
        desfecho=desfecho,
        enriquecimento=enriquecimento,
        criterios_vigentes=_criterios_vigentes(params),
        lacunas=lacunas,
    )
