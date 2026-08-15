"""Avaliação determinística de venda coberta (covered call/put), aplicando
os critérios de `skills/covered-options-strategy/SKILL.md` e
`params.yaml`. Nunca decide por julgamento livre de LLM — todo critério é
comparado a um número vindo do banco ou de `params.yaml`.

Uso pelo agente `strategy-covered`:
    python -m src.strategy.covered

Separação proposital (ver design.md, decisão 4):
- `avaliar()` é uma função pura (sem I/O) — testável sem banco.
- `executar_avaliacao_carteira()` busca dados reais e persiste o resultado.

GAPS CONHECIDOS deste MVP (documentados, não escondidos):
- Não existe, ainda, fonte de dados de calendário de resultados
  trimestrais. Por isso o critério "sem evento de resultado próximo" é
  sempre avaliado como "dado insuficiente" em `executar_avaliacao_carteira`
  até que essa fonte seja integrada — nunca assumimos "sem evento" por
  omissão.
- Não existe, ainda, uma forma de registrar caixa/garantia disponível na
  carteira. Por isso `executar_avaliacao_carteira` não gera candidatas de
  covered put nesta fase (a função `avaliar` já suporta covered put e é
  testada para esse caso, bastando informar `caixa_disponivel` quando essa
  fonte existir).
"""
import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

PARAMS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "covered-options-strategy" / "params.yaml"
)


def carregar_params() -> dict:
    """Carrega os limiares de `params.yaml` — nunca hardcode esses valores
    em código (regra da skill)."""
    return yaml.safe_load(PARAMS_PATH.read_text())


@dataclass
class CriterioAvaliado:
    nome: str
    valor: float | None
    detalhe: str
    aprovado: bool


@dataclass
class ResultadoAvaliacao:
    ticker_objeto: str
    codigo_opcao: str
    tipo_operacao: str  # 'covered_call' | 'covered_put'
    elegivel: bool
    motivo_nao_elegivel: str | None = None
    criterios: list[CriterioAvaliado] = field(default_factory=list)
    strike: float | None = None
    vencimento: str | None = None
    premio_estimado: float | None = None

    def criterios_json(self) -> dict:
        return {
            "criterios": [
                {"nome": c.nome, "valor": c.valor, "detalhe": c.detalhe, "aprovado": c.aprovado}
                for c in self.criterios
            ],
            "motivo_nao_elegivel": self.motivo_nao_elegivel,
        }


_CAMPOS_MERCADO_OBRIGATORIOS = (
    "iv_rank", "delta", "dias_vencimento", "preco",
    "exposicao_pct_apos_operacao", "dias_para_resultado",
)


def avaliar(posicao: dict, opcao: dict, params: dict) -> ResultadoAvaliacao:
    """Avalia UMA posição contra UMA opção candidata.

    `posicao`: {"ticker": str, "quantidade": int, "preco_medio": float,
                "caixa_disponivel": float | None}
    `opcao`: {"codigo": str, "tipo": "CALL"|"PUT", "strike": float,
              "vencimento": str, "preco": float, "delta": float,
              "iv_rank": float, "dias_vencimento": int,
              "exposicao_pct_apos_operacao": float,
              "dias_para_resultado": int | None}
              (campos ausentes/`None` em qualquer chave obrigatória =
              "dado insuficiente", nunca um valor assumido)
    """
    tipo_operacao = "covered_call" if opcao["tipo"] == "CALL" else "covered_put"
    resultado = ResultadoAvaliacao(
        ticker_objeto=posicao["ticker"],
        codigo_opcao=opcao["codigo"],
        tipo_operacao=tipo_operacao,
        elegivel=False,
        strike=opcao.get("strike"),
        vencimento=opcao.get("vencimento"),
        premio_estimado=opcao.get("preco"),
    )

    # 1. Pré-requisito estrutural (antes de qualquer critério de mercado)
    if tipo_operacao == "covered_call":
        qtd = posicao["quantidade"]
        if qtd < 100 or qtd % 100 != 0:
            resultado.motivo_nao_elegivel = (
                f"lote insuficiente para covered call: {qtd} ações em "
                "carteira (mínimo 100, múltiplos de 100)"
            )
            return resultado
    else:  # covered_put
        caixa = posicao.get("caixa_disponivel")
        garantia_necessaria = opcao["strike"] * 100
        if caixa is None:
            resultado.motivo_nao_elegivel = (
                "dado insuficiente: caixa/garantia disponível não informado "
                "para avaliar covered put"
            )
            return resultado
        if caixa < garantia_necessaria:
            resultado.motivo_nao_elegivel = (
                f"caixa insuficiente para covered put: {caixa} disponível, "
                f"{garantia_necessaria} necessário"
            )
            return resultado

    # 2. Dado de mercado insuficiente?
    faltando = [c for c in _CAMPOS_MERCADO_OBRIGATORIOS if opcao.get(c) is None]
    if faltando:
        resultado.motivo_nao_elegivel = (
            f"dado insuficiente: {', '.join(faltando)} ausente/desatualizado"
        )
        return resultado

    # 3. Critérios de mercado — TODOS precisam passar
    criterios = []

    iv_rank = opcao["iv_rank"]
    criterios.append(CriterioAvaliado(
        "iv_rank", iv_rank,
        f"{iv_rank} (mínimo {params['iv_rank_minimo']})",
        iv_rank >= params["iv_rank_minimo"],
    ))

    delta_abs = abs(opcao["delta"])
    criterios.append(CriterioAvaliado(
        "delta", delta_abs,
        f"{delta_abs} (faixa {params['delta_min']}–{params['delta_max']})",
        params["delta_min"] <= delta_abs <= params["delta_max"],
    ))

    dias_venc = opcao["dias_vencimento"]
    criterios.append(CriterioAvaliado(
        "dias_vencimento", dias_venc,
        f"{dias_venc} (faixa {params['dias_vencimento_min']}–{params['dias_vencimento_max']})",
        params["dias_vencimento_min"] <= dias_venc <= params["dias_vencimento_max"],
    ))

    valor_posicao_coberta = posicao["preco_medio"] * 100
    premio_total = opcao["preco"] * 100
    premio_pct = (premio_total / valor_posicao_coberta * 100) if valor_posicao_coberta else 0.0
    criterios.append(CriterioAvaliado(
        "premio_pct", round(premio_pct, 4),
        f"{premio_pct:.2f}% (mínimo {params['premio_minimo_pct']}%)",
        premio_pct >= params["premio_minimo_pct"],
    ))

    exposicao_pct = opcao["exposicao_pct_apos_operacao"]
    criterios.append(CriterioAvaliado(
        "exposicao_pct_apos_operacao", exposicao_pct,
        f"{exposicao_pct:.2f}% (limite {params['exposicao_maxima_pct_ativo']}%)",
        exposicao_pct <= params["exposicao_maxima_pct_ativo"],
    ))

    dias_resultado = opcao["dias_para_resultado"]
    sem_evento_proximo = dias_resultado >= params["dias_bloqueio_antes_resultado"]
    criterios.append(CriterioAvaliado(
        "dias_para_resultado", dias_resultado,
        f"{dias_resultado} dias até resultado (bloqueio < {params['dias_bloqueio_antes_resultado']})",
        sem_evento_proximo,
    ))

    resultado.criterios = criterios
    resultado.elegivel = all(c.aprovado for c in criterios)
    if not resultado.elegivel:
        reprovados = [c.nome for c in criterios if not c.aprovado]
        resultado.motivo_nao_elegivel = f"critério(s) não atendido(s): {', '.join(reprovados)}"
    return resultado


def _posicoes_acao_abertas(cur) -> list[dict]:
    cur.execute(
        "SELECT ticker, quantidade, preco_medio FROM posicoes "
        "WHERE tipo_ativo = 'ACAO' AND fechada_em IS NULL"
    )
    return [
        {"ticker": t, "quantidade": q, "preco_medio": float(p)}
        for t, q, p in cur.fetchall()
    ]


def _opcoes_call_candidatas(cur, ticker_objeto: str) -> list[dict]:
    cur.execute(
        """
        SELECT DISTINCT ON (codigo)
            codigo, strike, vencimento, preco, delta, iv_rank, coletado_em
        FROM opcoes
        WHERE ticker_objeto = %s AND tipo = 'CALL'
        ORDER BY codigo, coletado_em DESC
        """,
        (ticker_objeto,),
    )
    candidatas = []
    hoje = dt.date.today()
    for codigo, strike, vencimento, preco, delta, iv_rank, _coletado_em in cur.fetchall():
        dias_vencimento = (vencimento - hoje).days if vencimento else None
        candidatas.append({
            "codigo": codigo, "tipo": "CALL", "strike": float(strike) if strike is not None else None,
            "vencimento": str(vencimento) if vencimento else None,
            "preco": float(preco) if preco is not None else None,
            "delta": float(delta) if delta is not None else None,
            "iv_rank": float(iv_rank) if iv_rank is not None else None,
            "dias_vencimento": dias_vencimento,
            # GAP conhecido (ver docstring do módulo): sem fonte de calendário
            # de resultados ainda — nunca assumimos "sem evento", marcamos
            # ausente para virar "dado insuficiente" em `avaliar`.
            "dias_para_resultado": None,
        })
    return candidatas


def _exposicao_pct_apos_operacao(cur, ticker_objeto: str, nova_operacao_notional: float) -> float | None:
    cur.execute(
        "SELECT COALESCE(SUM(ABS(p.quantidade) * p.preco_medio), 0) "
        "FROM posicoes p JOIN opcoes o ON o.codigo = p.ticker "
        "WHERE p.tipo_ativo = 'OPCAO' AND p.fechada_em IS NULL AND o.ticker_objeto = %s",
        (ticker_objeto,),
    )
    exposicao_atual = float(cur.fetchone()[0])

    cur.execute(
        "SELECT COALESCE(SUM(ABS(quantidade) * preco_medio), 0) FROM posicoes "
        "WHERE fechada_em IS NULL"
    )
    total_patrimonio = float(cur.fetchone()[0])
    if not total_patrimonio:
        return None
    return (exposicao_atual + nova_operacao_notional) / total_patrimonio * 100


def _sugestao_ja_existe_hoje(cur, codigo_opcao: str) -> bool:
    cur.execute(
        "SELECT 1 FROM sugestoes WHERE codigo_opcao = %s "
        "AND status = 'pendente' AND gerado_em::date = CURRENT_DATE LIMIT 1",
        (codigo_opcao,),
    )
    return cur.fetchone() is not None


def _persistir_sugestao(cur, resultado: ResultadoAvaliacao) -> None:
    cur.execute(
        """
        INSERT INTO sugestoes (
            ticker_objeto, tipo_operacao, codigo_opcao, strike, vencimento,
            premio_estimado, criterios_json, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendente')
        """,
        (
            resultado.ticker_objeto, resultado.tipo_operacao, resultado.codigo_opcao,
            resultado.strike, resultado.vencimento, resultado.premio_estimado,
            _to_jsonb(resultado.criterios_json()),
        ),
    )


def _to_jsonb(d: dict):
    import json
    return json.dumps(d)


def executar_avaliacao_carteira() -> list[ResultadoAvaliacao]:
    """Avalia todas as posições de ação elegíveis para covered call contra
    as opções reais do banco, e persiste em `sugestoes` apenas as que
    passarem em todos os critérios. Retorna todos os resultados avaliados
    (inclusive os não elegíveis), para o relatório diário poder explicar
    o motivo de cada não-sugestão."""
    params = carregar_params()
    resultados: list[ResultadoAvaliacao] = []

    with get_connection() as conn, conn.cursor() as cur:
        posicoes = _posicoes_acao_abertas(cur)
        for posicao in posicoes:
            candidatas = _opcoes_call_candidatas(cur, posicao["ticker"])
            for opcao in candidatas:
                notional = (opcao["strike"] or 0) * 100
                opcao["exposicao_pct_apos_operacao"] = _exposicao_pct_apos_operacao(
                    cur, posicao["ticker"], notional
                )
                resultado = avaliar(posicao, opcao, params)
                resultados.append(resultado)
                if resultado.elegivel and not _sugestao_ja_existe_hoje(cur, resultado.codigo_opcao):
                    _persistir_sugestao(cur, resultado)
                    log.info(
                        "Sugestão persistida: %s %s strike=%s venc=%s",
                        resultado.ticker_objeto, resultado.codigo_opcao,
                        resultado.strike, resultado.vencimento,
                    )
        conn.commit()

    n_sugeridas = sum(1 for r in resultados if r.elegivel)
    log.info(
        "Avaliação concluída: %d posição(ões) x opção(ões) avaliadas, %d sugestão(ões) gerada(s).",
        len(resultados), n_sugeridas,
    )
    return resultados


def main() -> None:
    executar_avaliacao_carteira()


if __name__ == "__main__":
    main()
