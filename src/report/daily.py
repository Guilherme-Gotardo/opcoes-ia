"""Geração do relatório diário consolidado (carteira, alertas, sugestões).

Quando recebe uma execução, o Markdown é persistido no Postgres; `reports/`
é apenas export local opcional. Nunca preenche lacuna de dado com suposição,
sempre sinaliza como alerta.

Uso pelo agente `orchestrator`, ao final do fluxo diário:
    python -m src.report.daily
"""
import datetime as dt
import json
import logging
from pathlib import Path
from uuid import UUID

from src.config import get_news_settings
from src.db.connection import get_connection
from src.market.valuation import carregar_params, visao_carteira
from src.report.repository import salvar as salvar_relatorio
from src.strategy.outcome_repository import ultima_execucao_do_dia

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


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


def _resumo_carteira(cur, params: dict, agora: dt.datetime) -> dict:
    """Adaptador fino sobre `visao_carteira` (o domínio, compartilhado com a
    API). A conversão para dict existe só porque o renderizador Markdown e
    seus testes falam dict — a conta mora em `src/market/valuation.py`.
    """
    visao = visao_carteira(cur, params, agora)
    return {
        "posicoes": [vars(p) for p in visao.posicoes],
        "total_patrimonio": visao.total_patrimonio,
        "patrimonio_parcial": visao.patrimonio_parcial,
        "tickers_sem_cotacao": visao.tickers_sem_cotacao,
        "motivos_sem_cotacao": visao.motivos_sem_cotacao,
        "exposicao_pct_por_ativo": visao.exposicao_pct_por_ativo,
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
        settings = get_news_settings()
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


#: Como cada motivo do desfecho aparece no relatório.
_ROTULO_MOTIVO = {
    "bloqueio_data_resultado": (
        "bloqueadas por data de resultado não verificável",
        "Passaram nos critérios de mercado, mas não há data de divulgação "
        "confiável para o ativo.",
    ),
    "criterio_reprovado": (
        "reprovadas em critério de mercado",
        "Avaliadas contra valores reais e não atenderam ao critério — "
        "diferente de faltar dado.",
    ),
    "dado_insuficiente": (
        "não avaliadas por falta de dado",
        "Faltou dado para avaliar. Não é reprovação: não sabemos se "
        "passariam.",
    ),
    "pre_requisito": (
        "descartadas por pré-requisito",
        "Lote ou caixa insuficiente para a operação, antes dos critérios de "
        "mercado.",
    ),
    "sem_opcoes": (
        "sem opções para avaliar",
        "Nenhuma opção coletada para o ativo — nada a avaliar, o que é "
        "diferente de avaliar e nada passar.",
    ),
}


def _renderizar_desfecho(linhas: list[str], desfecho: list) -> None:
    """Seção das avaliações que não geraram sugestão, a partir do desfecho
    persistido.

    Existe porque "nenhuma sugestão hoje" sem explicação é indistinguível de
    "nada valia a pena" — e as duas coisas exigem ações opostas. Diferente da
    versão anterior, cobre TODOS os motivos, não só data de resultado, e lê
    do banco em vez de depender de ter rodado no mesmo processo.
    """
    nao_sugeridas = [l for l in desfecho if l.motivo != "sugerida"]
    if not nao_sugeridas:
        return

    linhas.append("## Avaliações sem sugestão")
    linhas.append("")
    for l in sorted(nao_sugeridas, key=lambda x: (x.ticker_objeto, x.motivo)):
        rotulo, explicacao = _ROTULO_MOTIVO.get(
            l.motivo, (l.motivo, "")
        )
        linhas.append(f"### {l.ticker_objeto} — {l.quantidade} opção(ões) {rotulo}")
        if explicacao:
            linhas.append(explicacao)

        if l.criterios_contagem:
            linhas.append("")
            linhas.append("Critérios que barraram (uma opção pode contar em mais de um):")
            for nome, n in sorted(l.criterios_contagem.items(), key=lambda kv: -kv[1]):
                linhas.append(f"  - {nome}: {n} opção(ões)")

        amostra = l.amostra or {}
        if amostra.get("codigo_opcao"):
            linhas.append("")
            linhas.append(
                f"Exemplo — {amostra['codigo_opcao']} | strike {amostra.get('strike')} "
                f"| vencimento {amostra.get('vencimento')} "
                f"| prêmio {amostra.get('premio_estimado')}"
            )
            for c in amostra.get("criterios", []):
                estado = c.get("estado")
                marca = "⚠️" if estado == "indisponivel" else ("✅" if estado == "aprovado" else "❌")
                linhas.append(f"  - {c.get('nome')}: {c.get('detalhe')} {marca}")

        if l.motivo == "bloqueio_data_resultado":
            linhas.append("")
            linhas.append("  → destrave com os dois passos:")
            linhas.append(
                f"     1. `python -m src.earnings.manage add {l.ticker_objeto} "
                "AAAA-MM-DD --sessao AFTER_CLOSE --origem <url do RI>`"
            )
            linhas.append(
                f"     2. `python -m src.earnings.ingest --tickers {l.ticker_objeto}`"
                "  (registrar não é consolidar)"
            )
        linhas.append("")


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
    bloqueios: list | None = None, desfecho: list | None = None,
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
    _renderizar_desfecho(linhas, desfecho or [])

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
    data: dt.date | None = None, avaliacoes: list | None = None, *,
    execution_id: UUID | str | None = None, exportar_arquivo: bool = True,
) -> Path | None:
    # Convenção do projeto: todo timestamp é UTC (ver cabeçalho de
    # schema.sql). `coletado_em` é gravado e lido em UTC, então o "dia" do
    # relatório também precisa ser UTC — usar a data local aqui causaria
    # falso alerta de "dado desatualizado" sempre que o horário local
    # estiver atrasado em relação ao UTC (ex.: à noite no Brasil).
    data = data or dt.datetime.now(dt.timezone.utc).date()
    params = carregar_params()
    with get_connection() as conn, conn.cursor() as cur:
        resumo = _resumo_carteira(cur, params, _referencia_de_frescor(data))
        alertas = _alertas(cur, resumo["posicoes"], data)
        sugestoes = _sugestoes_do_dia(cur, data)

    # Duas fontes para a seção de não-sugestões, nesta ordem:
    #
    # 1. `avaliacoes`, quando informado — vem de
    #    `executar_avaliacao_carteira()` no MESMO processo. Continua aceito
    #    para não quebrar quem já chama assim.
    # 2. O desfecho persistido da execução mais recente do dia. É o que
    #    permite gerar relatório num processo separado, e o que garante que
    #    relatório e interface leiam a mesma coisa.
    bloqueios = [a for a in (avaliacoes or []) if a.bloqueado_por_resultado]
    desfecho = [] if avaliacoes is not None else ultima_execucao_do_dia(data)

    conteudo = _renderizar_markdown(
        data, resumo, alertas, sugestoes, bloqueios, desfecho
    )
    if execution_id is not None:
        salvar_relatorio(execution_id, data, conteudo)
    if not exportar_arquivo:
        log.info("Relatório persistido sem export local: %s", data.isoformat())
        return None

    REPORTS_DIR.mkdir(exist_ok=True)
    caminho = REPORTS_DIR / f"{data.isoformat()}.md"
    caminho.write_text(conteudo, encoding="utf-8")
    log.info("Relatório gerado: %s", caminho)
    return caminho


def main() -> None:
    gerar_relatorio()


if __name__ == "__main__":
    main()
