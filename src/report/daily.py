"""Geração do relatório diário consolidado (carteira, alertas, sugestões)
como um arquivo Markdown persistido — ver design.md, decisão 5. Nunca
sobrescreve o relatório de um dia anterior; nunca preenche lacuna de dado
com suposição, sempre sinaliza como alerta.

Uso pelo agente `orchestrator`, ao final do fluxo diário:
    python -m src.report.daily
"""
import datetime as dt
import json
import logging
from pathlib import Path

from src.config import get_settings
from src.db.connection import get_connection
from src.market.valuation import carregar_params, cotacao_vigente

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


def _posicoes_abertas(cur) -> list[dict]:
    cur.execute(
        "SELECT ticker, tipo_ativo, quantidade, preco_medio FROM posicoes "
        "WHERE fechada_em IS NULL ORDER BY ticker"
    )
    return [
        {"ticker": t, "tipo_ativo": ta, "quantidade": q, "preco_medio": float(p)}
        for t, ta, q, p in cur.fetchall()
    ]


def _ticker_objeto_da_opcao(cur, codigo: str) -> str | None:
    cur.execute(
        "SELECT ticker_objeto FROM opcoes WHERE codigo = %s "
        "ORDER BY coletado_em DESC LIMIT 1",
        (codigo,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _preco_opcao(cur, codigo: str) -> tuple[float | None, dt.datetime | None]:
    cur.execute(
        "SELECT preco, coletado_em FROM opcoes WHERE codigo = %s "
        "ORDER BY coletado_em DESC LIMIT 1",
        (codigo,),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return None, None
    return float(row[0]), row[1]


def _referencia_de_frescor(data: dt.date) -> dt.datetime:
    """Momento contra o qual a idade das cotações é medida.

    Para o relatório de hoje é agora. Para um relatório gerado com data
    anterior é o fim daquele dia — senão o frescor seria julgado contra o
    presente e um relatório de duas semanas atrás apareceria inteiro como
    "sem cotação utilizável".
    """
    agora = dt.datetime.now(dt.timezone.utc)
    fim_do_dia = dt.datetime.combine(
        data, dt.time.max, tzinfo=dt.timezone.utc
    )
    return min(agora, fim_do_dia)


def _valorizar(cur, posicao: dict, params: dict, agora: dt.datetime) -> None:
    """Preenche preço de mercado e valor da posição, ou o motivo de não ter.

    Nunca cai para `preco_medio`: valorizar custo como se fosse mercado é o
    bug que esta função existe para não repetir. Sem cotação utilizável a
    posição fica sem valor e o relatório diz por quê.
    """
    if posicao["tipo_ativo"] == "ACAO":
        cotacao = cotacao_vigente(cur, posicao["ticker"], params, agora)
        preco, momento = cotacao.preco, cotacao.coletado_em
        motivo = None if cotacao.utilizavel else cotacao.motivo
    else:
        preco, momento = _preco_opcao(cur, posicao["ticker"])
        motivo = (
            None if preco is not None
            else f"{posicao['ticker']}: nenhum preço de opção coletado"
        )

    posicao["preco_mercado"] = preco
    posicao["cotacao_em"] = momento
    posicao["motivo_sem_cotacao"] = motivo
    posicao["valor"] = None if preco is None else abs(posicao["quantidade"]) * preco


def _resumo_carteira(cur, params: dict, agora: dt.datetime) -> dict:
    posicoes = _posicoes_abertas(cur)
    for p in posicoes:
        _valorizar(cur, p, params, agora)

    # Só posição em AÇÃO entra no patrimônio: o valor de uma opção é derivado
    # das mesmas ações já contadas, e somar os dois é contagem dupla — a
    # mesma que inviabilizava o critério de exposição.
    acoes = [p for p in posicoes if p["tipo_ativo"] == "ACAO"]
    total_patrimonio = sum(p["valor"] for p in acoes if p["valor"] is not None)
    sem_cotacao = [
        p["motivo_sem_cotacao"] for p in posicoes if p["motivo_sem_cotacao"]
    ]
    patrimonio_parcial = any(p["valor"] is None for p in acoes)

    exposicao_por_ativo: dict[str, float] = {}
    for p in posicoes:
        if p["valor"] is None:
            continue
        if p["tipo_ativo"] == "ACAO":
            objeto = p["ticker"]
        else:
            objeto = _ticker_objeto_da_opcao(cur, p["ticker"]) or "desconhecido"
        exposicao_por_ativo[objeto] = exposicao_por_ativo.get(objeto, 0.0) + p["valor"]

    exposicao_pct = {
        objeto: (valor / total_patrimonio * 100 if total_patrimonio else 0.0)
        for objeto, valor in exposicao_por_ativo.items()
    }
    return {
        "posicoes": posicoes,
        "total_patrimonio": total_patrimonio,
        "patrimonio_parcial": patrimonio_parcial,
        "tickers_sem_cotacao": [
            p["ticker"] for p in acoes if p["valor"] is None
        ],
        "motivos_sem_cotacao": sem_cotacao,
        "exposicao_pct_por_ativo": exposicao_pct,
    }


def _ultima_coleta(cur, tabela: str, coluna_ticker: str, ticker: str) -> dt.datetime | None:
    cur.execute(
        f"SELECT MAX(coletado_em) FROM {tabela} WHERE {coluna_ticker} = %s",
        (ticker,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _alertas(cur, posicoes: list[dict], data: dt.date) -> list[str]:
    alertas: list[str] = []
    tickers_acao = sorted({p["ticker"] for p in posicoes if p["tipo_ativo"] == "ACAO"})

    # Posições que ficaram sem valorização vêm primeiro: são as que tornam o
    # patrimônio incompleto, e o motivo já traz ticker e idade do dado.
    for p in posicoes:
        if p.get("motivo_sem_cotacao"):
            alertas.append(
                f"{p['motivo_sem_cotacao']} — posição não valorizada a mercado."
            )

    for ticker in tickers_acao:
        ultima_cotacao = _ultima_coleta(cur, "cotacoes", "ticker", ticker)
        if ultima_cotacao is None:
            alertas.append(f"{ticker}: nenhuma cotação coletada ainda.")
        elif ultima_cotacao.date() != data:
            alertas.append(f"{ticker}: cotação desatualizada (última coleta em {ultima_cotacao.date()}).")

        ultima_opcao = _ultima_coleta(cur, "opcoes", "ticker_objeto", ticker)
        if ultima_opcao is None:
            alertas.append(f"{ticker}: nenhum dado de opções coletado ainda.")
        elif ultima_opcao.date() != data:
            alertas.append(f"{ticker}: dado de opções desatualizado (última coleta em {ultima_opcao.date()}).")

    try:
        settings = get_settings()
        if not settings.news_api_key:
            alertas.append("Notícias: coleta não configurada (NEWS_API_KEY ausente) — etapa pulada.")
    except RuntimeError as exc:
        alertas.append(f"Configuração incompleta ao checar notícias: {exc}")

    return alertas


def _sugestoes_do_dia(cur, data: dt.date) -> list[dict]:
    cur.execute(
        """
        SELECT ticker_objeto, tipo_operacao, codigo_opcao, strike, vencimento,
               premio_estimado, criterios_json, status
        FROM sugestoes
        WHERE gerado_em::date = %s
        ORDER BY ticker_objeto
        """,
        (data,),
    )
    sugestoes = []
    for row in cur.fetchall():
        ticker_objeto, tipo_operacao, codigo, strike, vencimento, premio, criterios_json, status = row
        criterios = criterios_json
        if isinstance(criterios, str):
            criterios = json.loads(criterios)
        sugestoes.append({
            "ticker_objeto": ticker_objeto, "tipo_operacao": tipo_operacao,
            "codigo_opcao": codigo, "strike": strike, "vencimento": vencimento,
            "premio_estimado": premio, "criterios": criterios or {}, "status": status,
        })
    return sugestoes


def _renderizar_bloqueios(linhas: list[str], bloqueios: list) -> None:
    """Seção das avaliações barradas por data de resultado não verificável.

    Existe porque "nenhuma sugestão hoje" sem explicação é indistinguível
    de "nada valia a pena" — e as duas coisas exigem ações opostas do
    usuário. Aqui ele vê o quão perto a oportunidade estava e o que
    destrava.
    """
    if not bloqueios:
        return
    linhas.append("## Avaliações bloqueadas por data de resultado")
    linhas.append("")
    linhas.append(
        "Estas opções passaram nos critérios de mercado, mas não há data de "
        "divulgação de resultado confiável para o ativo. Registre a data "
        "lida no site de RI para destravar:"
    )
    linhas.append("")
    for b in bloqueios:
        linhas.append(f"### {b.ticker_objeto} — {b.codigo_opcao}")
        linhas.append(
            f"Strike: {b.strike} | Vencimento: {b.vencimento} | "
            f"Prêmio estimado: {b.premio_estimado}"
        )
        for c in b.criterios:
            if c.indisponivel:
                marca = "⚠️"
            elif c.aprovado:
                marca = "✅"
            else:
                marca = "❌"
            linhas.append(f"  - {c.nome}: {c.detalhe} {marca}")
        linhas.append("")
        # Os DOIS passos: registrar grava o que você leu no RI, consolidar é
        # o que torna a data consultável pela avaliação. Citar só o primeiro
        # produzia outro silêncio — o usuário seguia a instrução e continuava
        # sem sugestão, sem saber por quê.
        linhas.append("  → destrave com os dois passos:")
        linhas.append(
            f"     1. `python -m src.earnings.manage add {b.ticker_objeto} "
            "AAAA-MM-DD --sessao AFTER_CLOSE --origem <url do RI>`"
        )
        linhas.append(
            f"     2. `python -m src.earnings.ingest --tickers {b.ticker_objeto}`"
            "  (registrar não é consolidar)"
        )
        linhas.append("")


def _renderizar_markdown(
    data: dt.date, resumo: dict, alertas: list[str], sugestoes: list[dict],
    bloqueios: list | None = None,
) -> str:
    linhas = [f"# Relatório diário — {data.isoformat()}", ""]

    linhas.append("## Carteira atual")
    if not resumo["posicoes"]:
        linhas.append("Nenhuma posição aberta.")
    else:
        linhas.append(
            f"Patrimônio total (a preço de mercado): R$ {resumo['total_patrimonio']:.2f}"
        )
        if resumo.get("patrimonio_parcial"):
            sem = ", ".join(resumo.get("tickers_sem_cotacao", []))
            linhas.append("")
            linhas.append(
                f"⚠️ **Patrimônio parcial:** não cobre {sem} — sem cotação "
                "utilizável, e valorizar pelo preço de entrada seria estimar."
            )
        linhas.append("")
        linhas.append(
            "Só posições em ação entram no patrimônio: o valor de uma opção "
            "deriva das mesmas ações já contadas."
        )
        linhas.append("")
        linhas.append(
            "| Ticker | Tipo | Quantidade | Preço médio (custo) | "
            "Preço de mercado | Cotação de | Valor a mercado |"
        )
        linhas.append("|---|---|---|---|---|---|---|")
        for p in resumo["posicoes"]:
            if p["valor"] is None:
                preco_mercado = valor = "—"
                momento = "sem cotação"
            else:
                preco_mercado = f"{p['preco_mercado']:.4f}"
                valor = f"{p['valor']:.2f}"
                momento = (
                    p["cotacao_em"].date().isoformat() if p["cotacao_em"] else "—"
                )
            linhas.append(
                f"| {p['ticker']} | {p['tipo_ativo']} | {p['quantidade']} | "
                f"{p['preco_medio']:.4f} | {preco_mercado} | {momento} | {valor} |"
            )
        linhas.append("")
        linhas.append("**Exposição por ativo-objeto** (sobre o patrimônio a mercado):")
        for objeto, pct in sorted(resumo["exposicao_pct_por_ativo"].items()):
            linhas.append(f"- {objeto}: {pct:.2f}% do patrimônio")
    linhas.append("")

    linhas.append("## Alertas")
    if not alertas:
        linhas.append("Nenhum alerta hoje.")
    else:
        for a in alertas:
            linhas.append(f"- ⚠️ {a}")
    linhas.append("")

    _renderizar_bloqueios(linhas, bloqueios or [])

    linhas.append("## Sugestões")
    if not sugestoes:
        linhas.append("Nenhuma sugestão hoje.")
    else:
        for s in sugestoes:
            linhas.append(
                f"### {s['ticker_objeto']} — {s['tipo_operacao']} ({s['codigo_opcao']})"
            )
            linhas.append(
                f"Strike: {s['strike']} | Vencimento: {s['vencimento']} | "
                f"Prêmio estimado: {s['premio_estimado']}"
            )
            linhas.append("**Pendente de revisão humana — nenhuma ordem foi executada.**")
            aviso = s["criterios"].get("aviso_resultado")
            if aviso:
                linhas.append(f"⚠️ **{aviso}**")
            criterios = s["criterios"].get("criterios", [])
            for c in criterios:
                if c.get("estado") == "indisponivel":
                    marca = "⚠️"
                elif c.get("aprovado"):
                    marca = "✅"
                else:
                    marca = "❌"
                linhas.append(f"  - {c.get('nome')}: {c.get('detalhe')} {marca}")
            linhas.append("")

    return "\n".join(linhas) + "\n"


def gerar_relatorio(
    data: dt.date | None = None, avaliacoes: list | None = None
) -> Path:
    # Convenção do projeto: todo timestamp é UTC (ver cabeçalho de
    # schema.sql). `coletado_em` é gravado e lido em UTC, então o "dia" do
    # relatório também precisa ser UTC — usar a data local aqui causaria
    # falso alerta de "dado desatualizado" sempre que o horário local
    # estiver atrasado em relação ao UTC (ex.: à noite no Brasil).
    data = data or dt.datetime.now(dt.timezone.utc).date()
    REPORTS_DIR.mkdir(exist_ok=True)
    caminho = REPORTS_DIR / f"{data.isoformat()}.md"

    params = carregar_params()
    with get_connection() as conn, conn.cursor() as cur:
        resumo = _resumo_carteira(cur, params, _referencia_de_frescor(data))
        alertas = _alertas(cur, resumo["posicoes"], data)
        sugestoes = _sugestoes_do_dia(cur, data)

    # `avaliacoes` vem de `executar_avaliacao_carteira()`, que já retorna
    # todos os resultados — inclusive os não elegíveis. Reaproveitamos em
    # vez de reavaliar. Sem esse argumento o relatório segue funcionando,
    # só não mostra a seção de bloqueios.
    bloqueios = [a for a in (avaliacoes or []) if a.bloqueado_por_resultado]

    conteudo = _renderizar_markdown(data, resumo, alertas, sugestoes, bloqueios)
    caminho.write_text(conteudo, encoding="utf-8")
    log.info("Relatório gerado: %s", caminho)
    return caminho


def main() -> None:
    gerar_relatorio()


if __name__ == "__main__":
    main()
