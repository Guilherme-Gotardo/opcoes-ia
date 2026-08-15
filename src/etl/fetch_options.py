"""ETL de opções (preço, gregas, IV/IV rank) via API da OpLab.
Rodar: python -m src.etl.fetch_options

NOTA: valide o endpoint exato e o formato de resposta na documentação oficial
da OpLab (https://oplab.com.br) antes do primeiro uso com um token real — o
formato assumido abaixo (`CHAVES_ESPERADAS`) é validado defensivamente em
`_validar_formato`, então uma resposta em formato diferente falha alto e
claro em vez de gravar dado incorreto. Ajuste `CHAVES_ESPERADAS` e o
mapeamento em `upsert` assim que o formato real for confirmado.
"""
import logging

import requests

from src.config import get_settings
from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

OPLAB_OPTIONS_URL = "https://api.oplab.com.br/v3/market/options/{ticker}"

CHAVES_ESPERADAS = {
    "symbol", "type", "strike", "due_date", "close",
    "delta", "gamma", "theta", "vega", "rho", "volatility", "iv_rank",
}


class FormatoRespostaInvalido(RuntimeError):
    """Levantado quando a resposta da API de opções não bate com o formato
    validado — nunca gravamos dado parcial/incorreto nesse caso."""


def fetch(ticker_objeto: str) -> list[dict]:
    settings = get_settings()
    resp = requests.get(
        OPLAB_OPTIONS_URL.format(ticker=ticker_objeto),
        headers={"Access-Token": settings.oplab_token},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _validar_formato(ticker_objeto: str, options: list[dict]) -> None:
    """Garante que cada item da resposta tem todas as chaves esperadas
    antes de qualquer insert. Levanta `FormatoRespostaInvalido` explícito
    em vez de deixar `upsert` gravar `NULL`s silenciosos para campo
    ausente."""
    for i, item in enumerate(options):
        faltando = CHAVES_ESPERADAS - item.keys()
        if faltando:
            raise FormatoRespostaInvalido(
                f"Resposta de opções para {ticker_objeto} no índice {i} "
                f"não tem as chaves esperadas: {sorted(faltando)}. "
                "Verifique se o formato da API OpLab mudou."
            )


def upsert(ticker_objeto: str, options: list[dict]) -> int:
    if not options:
        return 0
    _validar_formato(ticker_objeto, options)
    with get_connection() as conn, conn.cursor() as cur:
        for o in options:
            cur.execute(
                """
                INSERT INTO opcoes (
                    codigo, ticker_objeto, tipo, strike, vencimento, preco,
                    delta, gamma, theta, vega, rho,
                    volatilidade_implicita, iv_rank, fonte
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'oplab')
                """,
                (
                    o.get("symbol"), ticker_objeto, o.get("type"),
                    o.get("strike"), o.get("due_date"), o.get("close"),
                    o.get("delta"), o.get("gamma"), o.get("theta"),
                    o.get("vega"), o.get("rho"),
                    o.get("volatility"), o.get("iv_rank"),
                ),
            )
        conn.commit()
    return len(options)


def main(tickers: list[str] | None = None) -> None:
    tickers = tickers or _tickers_objeto_da_carteira()
    total = 0
    falhas: dict[str, str] = {}
    for t in tickers:
        try:
            options = fetch(t)
            total += upsert(t, options)
            log.info("Opções de %s: %d registros.", t, len(options))
        except Exception as exc:  # noqa: BLE001 — isolamos falha por ticker de propósito
            falhas[t] = str(exc)
            log.error("Falha ao coletar opções de %s: %s", t, exc)
    log.info(
        "Total de opções atualizadas: %d. Tickers com falha: %s",
        total, sorted(falhas) if falhas else "nenhum",
    )
    if falhas:
        for t, motivo in falhas.items():
            log.error("  - %s: %s", t, motivo)


def _tickers_objeto_da_carteira() -> list[str]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ticker FROM posicoes "
            "WHERE tipo_ativo = 'ACAO' AND fechada_em IS NULL"
        )
        return [row[0] for row in cur.fetchall()]


if __name__ == "__main__":
    main()
