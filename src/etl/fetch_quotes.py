"""ETL de cotações de ações via brapi.dev.
Rodar: python -m src.etl.fetch_quotes

NOTA: a resposta real de `v2/stocks/quote` aninha os campos de mercado
(regularMarketPrice/regularMarketVolume) dentro da chave `data` de cada item
de `results` — validado contra a API real em 2026-08-14. `_extrair_campos`
valida essa estrutura explicitamente antes de gravar; nunca grava `NULL` em
`preco` por causa de um formato inesperado.

NOTA: o plano Free da Brapi permite apenas 1 ativo por requisição (validado
contra a API real em 2026-08-15: erro `QUOTES_PER_REQUEST_EXCEEDED` ao
mandar mais de 1 símbolo) — por isso `fetch_um` faz uma requisição por
ticker, e `main()` isola falha por ticker (um ticker com problema não
interrompe os demais) e respeita o orçamento diário de requests
(`src.etl.budget`, ver design.md decisão 7).
"""
import logging

import requests

from src.assets.manage import tickers_cadastrados, universo_de_analise
from src.config import get_settings
from src.db.connection import get_connection
from src.etl.budget import orcamento_restante_hoje

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BRAPI_URL = "https://brapi.dev/api/v2/stocks/quote"


class FormatoRespostaInvalido(RuntimeError):
    """Levantado quando a resposta da Brapi não bate com o formato
    validado — nunca gravamos `preco`/`volume` ausentes silenciosamente."""


def fetch_um(ticker: str) -> dict:
    """Busca a cotação de UM ticker — o plano Free só permite 1 ativo por
    requisição, então não há uma versão em lote."""
    settings = get_settings()
    resp = requests.get(
        BRAPI_URL,
        params={"symbols": ticker},
        headers={"Authorization": f"Bearer {settings.brapi_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        raise FormatoRespostaInvalido(
            f"Nenhum resultado retornado pela Brapi para {ticker!r}."
        )
    return results[0]


def _extrair_campos(row: dict) -> tuple[str, float, int | None]:
    symbol = row.get("symbol")
    dados = row.get("data")
    if not symbol or not isinstance(dados, dict) or dados.get("regularMarketPrice") is None:
        raise FormatoRespostaInvalido(
            f"Resposta de cotação em formato inesperado para {symbol!r}: "
            "esperado 'symbol' e 'data.regularMarketPrice'. Verifique se o "
            "formato da API Brapi mudou."
        )
    return symbol, dados["regularMarketPrice"], dados.get("regularMarketVolume")


def upsert(rows: list[dict]) -> int:
    if not rows:
        return 0
    with get_connection() as conn, conn.cursor() as cur:
        for r in rows:
            symbol, preco, volume = _extrair_campos(r)
            cur.execute(
                """
                INSERT INTO cotacoes (ticker, preco, volume, fonte)
                VALUES (%s, %s, %s, 'brapi')
                """,
                (symbol, preco, volume),
            )
        conn.commit()
    return len(rows)


def main(tickers: list[str] | None = None) -> None:
    tickers = tickers or _tickers_da_carteira()
    if not tickers:
        log.warning("Nenhum ticker na carteira — nada a coletar.")
        return

    with get_connection() as conn, conn.cursor() as cur:
        restante = orcamento_restante_hoje(cur, get_settings().brapi_requests_dia_maximo)

    # Uma consulta só, antes de gastar request: sem o ativo cadastrado, o
    # INSERT em `cotacoes` viola a FK para `ativos` e o erro que chega ao
    # usuário é a mensagem crua do Postgres, que não diz o que fazer.
    # Conferir aqui é mais direto do que capturar `ForeignKeyViolation` e
    # adivinhar qual constraint falhou — isso acoplaria a mensagem ao nome
    # da constraint no schema.
    cadastrados = tickers_cadastrados(tickers)
    nao_cadastrados = [t for t in tickers if t.upper() not in cadastrados]
    tickers = [t for t in tickers if t.upper() in cadastrados]

    if nao_cadastrados:
        log.error(
            "Ativo não cadastrado (a cotação seria recusada pelo banco): %s. "
            'Cadastre com: python -m src.assets.manage add <TICKER> "<nome>" acao',
            ", ".join(sorted(nao_cadastrados)),
        )
    if not tickers:
        log.warning("Nenhum ticker cadastrado para coletar.")
        return

    a_processar, fora_do_orcamento = tickers, []
    if restante < len(tickers):
        a_processar, fora_do_orcamento = tickers[:restante], tickers[restante:]
        log.warning(
            "Orçamento diário de requests da Brapi insuficiente para toda a "
            "carteira (%d tickers, %d requests restantes hoje). Tickers fora "
            "do orçamento hoje: %s",
            len(tickers), restante, sorted(fora_do_orcamento),
        )

    total = 0
    falhas: dict[str, str] = {}
    for t in a_processar:
        try:
            row = fetch_um(t)
            total += upsert([row])
        except Exception as exc:  # noqa: BLE001 — isolamos falha por ticker de propósito
            falhas[t] = str(exc)
            log.error("Falha ao coletar cotação de %s: %s", t, exc)

    log.info(
        "Cotações atualizadas: %d/%d tickers. Falhas: %s. "
        "Não cadastrados: %s. Fora do orçamento: %s",
        total, len(tickers),
        sorted(falhas) if falhas else "nenhuma",
        sorted(nao_cadastrados) if nao_cadastrados else "nenhum",
        sorted(fora_do_orcamento) if fora_do_orcamento else "nenhum",
    )


def _tickers_da_carteira() -> list[str]:
    """Universo de coleta: CARTEIRA ∪ VIGIADOS (migração 006).

    Antes era só a carteira, o que fechava a porta para procurar
    oportunidade em ativo que ainda não se tem. A união importa nos dois
    sentidos: ativo em carteira entra mesmo sem estar vigiado — senão parar
    de vigiar deixaria a posição sem preço.
    """
    return universo_de_analise()


if __name__ == "__main__":
    main()
