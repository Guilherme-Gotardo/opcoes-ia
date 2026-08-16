"""ETL de candles OHLC via brapi.dev.
Rodar: python -m src.etl.fetch_candles [--intervalo 1h] [--janela 5d]

O QUE ESTE ETL COLETA, E POR QUE É SEPARADO DO `fetch_quotes`
------------------------------------------------------------
`fetch_quotes` grava UM preço por coleta — "quanto vale agora" — e é o que
a valorização da carteira consome. Aqui se coleta o histórico em janelas
(abertura, máxima, mínima, fechamento por período), que serve para desenhar
o gráfico e NÃO alimenta decisão nenhuma. Misturar os dois faria a
valorização competir com linhas de granularidade diferente.

FORMATO VALIDADO CONTRA A API REAL (2026-08-16)
-----------------------------------------------
`GET /api/quote/{ticker}?range=5d&interval=1h` devolve
`results[0].historicalDataPrice` como lista de
`{date, open, high, low, close, volume, adjustedClose}`, com `date` em epoch
segundos. `range=1d` devolveu lista VAZIA no teste — provável efeito de dia
sem pregão — então lista vazia é tratada como "nada a gravar", nunca como
erro de formato.

O par (range, interval) não é livre: a Brapi rejeita combinações inválidas
(ex.: 1h com janela longa demais). `JANELA_PADRAO_POR_INTERVALO` guarda os
pares confirmados; passar `--janela` sobrescreve, por sua conta.

IDEMPOTÊNCIA IMPORTA AQUI
-------------------------
A vela do período corrente ainda está mudando: máxima, mínima e fechamento
sobem e descem até o período fechar. Por isso o upsert atualiza a linha da
mesma janela em vez de empilhar — a chave é (ticker, intervalo, abertura_em).
"""
import argparse
import datetime as dt
import logging

import requests

from src.assets.manage import tickers_cadastrados, universo_de_analise
from src.config import get_settings
from src.db.connection import get_connection
from src.etl.budget import orcamento_restante_hoje

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BRAPI_URL = "https://brapi.dev/api/quote"

#: Janela padrão por intervalo — pares confirmados contra a API real.
JANELA_PADRAO_POR_INTERVALO = {
    "1m": "1d",
    "5m": "5d",
    "15m": "5d",
    "30m": "5d",
    "1h": "5d",
    "1d": "3mo",
    "1wk": "1y",
}

INTERVALO_PADRAO = "1h"


class FormatoRespostaInvalido(RuntimeError):
    """A resposta não bate com o formato validado. Nunca gravamos uma vela
    com campo faltando: meia vela é pior do que vela nenhuma, porque o
    gráfico a desenha como se fosse dado bom."""


def fetch_um(ticker: str, intervalo: str, janela: str) -> list[dict]:
    """Histórico de UM ticker. Devolve lista possivelmente vazia."""
    settings = get_settings()
    resp = requests.get(
        f"{BRAPI_URL}/{ticker}",
        params={"range": janela, "interval": intervalo},
        headers={"Authorization": f"Bearer {settings.brapi_token}"},
        timeout=20,
    )
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if not results:
        raise FormatoRespostaInvalido(
            f"Nenhum resultado retornado pela Brapi para {ticker!r}."
        )
    historico = results[0].get("historicalDataPrice")
    if historico is None:
        raise FormatoRespostaInvalido(
            f"Resposta sem 'historicalDataPrice' para {ticker!r} — verifique "
            "se o formato da API Brapi mudou."
        )
    return historico


def _vela(ponto: dict, ticker: str) -> tuple:
    """Traduz um ponto da API para os campos da tabela, recusando o que
    estiver incompleto."""
    faltando = [c for c in ("date", "open", "high", "low", "close")
                if ponto.get(c) is None]
    if faltando:
        raise FormatoRespostaInvalido(
            f"Vela incompleta para {ticker}: faltam {', '.join(faltando)}."
        )
    abertura_em = dt.datetime.fromtimestamp(ponto["date"], tz=dt.timezone.utc)
    return (
        ticker, abertura_em,
        ponto["open"], ponto["high"], ponto["low"], ponto["close"],
        ponto.get("volume"),
    )


def upsert(ticker: str, intervalo: str, pontos: list[dict]) -> int:
    """Grava as velas, atualizando as janelas que já existiam."""
    if not pontos:
        return 0
    velas = [_vela(p, ticker) for p in pontos]

    with get_connection() as conn, conn.cursor() as cur:
        for tk, abertura_em, o, h, l, c, vol in velas:
            cur.execute(
                """
                INSERT INTO candles (ticker, intervalo, abertura_em, abertura,
                                     maxima, minima, fechamento, volume, fonte)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'brapi')
                ON CONFLICT (ticker, intervalo, abertura_em) DO UPDATE SET
                    -- A vela do período corrente ainda se move; recoletar
                    -- corrige a linha em vez de criar uma segunda verdade
                    -- para a mesma janela.
                    abertura    = EXCLUDED.abertura,
                    maxima      = EXCLUDED.maxima,
                    minima      = EXCLUDED.minima,
                    fechamento  = EXCLUDED.fechamento,
                    volume      = EXCLUDED.volume,
                    coletado_em = now()
                """,
                (tk, intervalo, abertura_em, o, h, l, c, vol),
            )
        conn.commit()
    return len(velas)


def main(
    tickers: list[str] | None = None,
    intervalo: str = INTERVALO_PADRAO,
    janela: str | None = None,
) -> None:
    janela = janela or JANELA_PADRAO_POR_INTERVALO.get(intervalo)
    if janela is None:
        log.error(
            "Intervalo sem janela padrão conhecida: %s. Informe --janela "
            "explicitamente ou use um de: %s",
            intervalo, ", ".join(sorted(JANELA_PADRAO_POR_INTERVALO)),
        )
        return

    tickers = tickers or _tickers_da_carteira()
    if not tickers:
        log.warning("Nenhum ticker na carteira — nada a coletar.")
        return

    # Mesma checagem do `fetch_quotes`, pela mesma razão: `candles.ticker`
    # tem FK para `ativos`, e sem o cadastro o erro que chega ao usuário é a
    # mensagem crua do Postgres, que não diz o que fazer.
    cadastrados = tickers_cadastrados(tickers)
    nao_cadastrados = [t for t in tickers if t.upper() not in cadastrados]
    tickers = [t for t in tickers if t.upper() in cadastrados]
    if nao_cadastrados:
        log.error(
            "Ativo não cadastrado (a vela seria recusada pelo banco): %s. "
            'Cadastre com: python -m src.assets.manage add <TICKER> "<nome>" acao',
            ", ".join(sorted(nao_cadastrados)),
        )
    if not tickers:
        log.warning("Nenhum ticker cadastrado para coletar.")
        return

    with get_connection() as conn, conn.cursor() as cur:
        restante = orcamento_restante_hoje(cur, get_settings().brapi_requests_dia_maximo)

    a_processar, fora_do_orcamento = tickers, []
    if restante < len(tickers):
        a_processar, fora_do_orcamento = tickers[:restante], tickers[restante:]
        log.warning(
            "Orçamento diário insuficiente para toda a carteira (%d tickers, "
            "%d requests restantes). Fora do orçamento hoje: %s",
            len(tickers), restante, sorted(fora_do_orcamento),
        )

    total = 0
    falhas: dict[str, str] = {}
    for t in a_processar:
        try:
            pontos = fetch_um(t, intervalo, janela)
            gravadas = upsert(t.upper(), intervalo, pontos)
            total += gravadas
            if gravadas == 0:
                log.info("Sem velas para %s em %s/%s (janela sem pregão?)",
                         t, intervalo, janela)
        except Exception as exc:  # noqa: BLE001 — falha por ticker é isolada de propósito
            falhas[t] = str(exc)
            log.error("Falha ao coletar velas de %s: %s", t, exc)

    log.info(
        "Velas gravadas: %d (intervalo=%s janela=%s) em %d ticker(s). "
        "Falhas: %s. Fora do orçamento: %s",
        total, intervalo, janela, len(a_processar),
        sorted(falhas) if falhas else "nenhuma",
        sorted(fora_do_orcamento) if fora_do_orcamento else "nenhum",
    )


def _tickers_da_carteira() -> list[str]:
    """Universo de coleta: CARTEIRA ∪ VIGIADOS (migração 006).

    Opção fica de fora de qualquer jeito: `posicoes.ticker` guarda o CÓDIGO
    da opção, que não é linha em `ativos` e não tem série histórica própria
    na Brapi.
    """
    return universo_de_analise()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coleta candles OHLC.")
    parser.add_argument("--intervalo", default=INTERVALO_PADRAO,
                        help=f"padrão: {INTERVALO_PADRAO}")
    parser.add_argument("--janela", default=None,
                        help="range da Brapi; padrão depende do intervalo")
    parser.add_argument("--tickers", default=None,
                        help="lista separada por vírgula; padrão: carteira aberta")
    args = parser.parse_args()
    main(
        tickers=args.tickers.split(",") if args.tickers else None,
        intervalo=args.intervalo,
        janela=args.janela,
    )
