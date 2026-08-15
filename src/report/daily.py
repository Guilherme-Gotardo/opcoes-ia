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


def _resumo_carteira(cur) -> dict:
    posicoes = _posicoes_abertas(cur)
    for p in posicoes:
        p["valor"] = abs(p["quantidade"]) * p["preco_medio"]
    total_patrimonio = sum(p["valor"] for p in posicoes)

    exposicao_por_ativo: dict[str, float] = {}
    for p in posicoes:
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
        linhas.append(
            f"  → destrave com: `python -m src.earnings.manage add "
            f"{b.ticker_objeto} AAAA-MM-DD --sessao AFTER_CLOSE --origem <url do RI>`"
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
        linhas.append(f"Patrimônio total (proxy, a preço médio de entrada): R$ {resumo['total_patrimonio']:.2f}")
        linhas.append("")
        linhas.append("| Ticker | Tipo | Quantidade | Preço médio | Valor |")
        linhas.append("|---|---|---|---|---|")
        for p in resumo["posicoes"]:
            linhas.append(
                f"| {p['ticker']} | {p['tipo_ativo']} | {p['quantidade']} | "
                f"{p['preco_medio']:.4f} | {p['valor']:.2f} |"
            )
        linhas.append("")
        linhas.append("**Exposição por ativo-objeto:**")
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

    with get_connection() as conn, conn.cursor() as cur:
        resumo = _resumo_carteira(cur)
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
