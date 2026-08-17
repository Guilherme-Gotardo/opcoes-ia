"""ETL de notícias relevantes por ativo, via uma News API genérica (estilo
NewsAPI.org) configurada por `NEWS_API_KEY`.
Rodar: python -m src.etl.fetch_news

Este ETL grava apenas metadados (título, url, data, fonte) — nunca o texto
completo do artigo. O resumo em texto próprio (`noticias.resumo`) é
responsabilidade do agente `market-analyst` ao consumir a notícia, não
deste ETL (ver `.claude/agents/market-analyst.md`): assim nunca copiamos
texto de terceiros para o banco.

Se `NEWS_API_KEY` não estiver definida, a coleta é pulada de forma
explícita — nunca silenciosamente, e sem tratar isso como erro que bloqueie
os demais passos do fluxo diário.
"""
import logging

import requests

from src.assets.manage import universo_de_analise
from src.config import get_news_settings
from src.db.connection import get_connection
from src.etl.result import DetalheAlvo, EstadoAlvo, ResultadoColeta

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

NEWS_API_URL = "https://newsapi.org/v2/everything"


def fetch(ticker: str) -> list[dict]:
    settings = get_news_settings()
    resp = requests.get(
        NEWS_API_URL,
        params={"q": ticker, "language": "pt", "sortBy": "publishedAt", "pageSize": 10},
        headers={"X-Api-Key": settings.news_api_key},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("articles", [])


def _noticia_ja_existe(cur, ticker: str, url: str) -> bool:
    cur.execute(
        "SELECT 1 FROM noticias WHERE ticker = %s AND url = %s LIMIT 1",
        (ticker, url),
    )
    return cur.fetchone() is not None


def upsert(ticker: str, articles: list[dict]) -> int:
    if not articles:
        return 0
    inseridas = 0
    with get_connection() as conn, conn.cursor() as cur:
        for a in articles:
            url = a.get("url")
            if not url or _noticia_ja_existe(cur, ticker, url):
                continue
            fonte = (a.get("source") or {}).get("name") or "newsapi"
            cur.execute(
                """
                INSERT INTO noticias (ticker, titulo, url, publicado_em, fonte)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (ticker, a.get("title"), url, a.get("publishedAt"), fonte),
            )
            inseridas += 1
        conn.commit()
    return inseridas


def main(tickers: list[str] | None = None) -> ResultadoColeta:
    settings = get_news_settings()
    if not settings.news_api_key:
        log.warning(
            "fetch_news: NEWS_API_KEY não configurada — etapa de notícias "
            "pulada nesta execução (não é um erro; configure em .env para habilitar)."
        )
        return ResultadoColeta.pulado(
            "noticias", "newsapi", "fonte_nao_configurada",
        )

    if tickers is None:
        tickers = _tickers_da_carteira()
    if not tickers:
        log.warning("Nenhum ticker na carteira ou watchlist — nada a coletar.")
        return ResultadoColeta.pulado("noticias", "newsapi", "universo_vazio")

    total = 0
    falhas: dict[str, str] = {}
    detalhes: list[DetalheAlvo] = []
    for t in tickers:
        try:
            articles = fetch(t)
            n = upsert(t, articles)
            total += n
            detalhes.append(DetalheAlvo(
                t, EstadoAlvo.SUCESSO, registros_persistidos=n,
            ))
            log.info("Notícias de %s: %d novas (de %d retornadas).", t, n, len(articles))
        except Exception as exc:  # noqa: BLE001 — isolamos falha por ticker de propósito
            falhas[t] = str(exc)
            detalhes.append(DetalheAlvo(
                t,
                EstadoAlvo.FALHA,
                codigo_motivo="erro_coleta",
                detalhe=str(exc),
            ))
            log.error("Falha ao coletar notícias de %s: %s", t, exc)

    log.info(
        "Total de notícias novas: %d. Tickers com falha: %s",
        total, sorted(falhas) if falhas else "nenhum",
    )
    if falhas:
        for t, motivo in falhas.items():
            log.error("  - %s: %s", t, motivo)
    return ResultadoColeta.de_detalhes("noticias", "newsapi", detalhes)


def _tickers_da_carteira() -> list[str]:
    return universo_de_analise()


if __name__ == "__main__":
    main()
