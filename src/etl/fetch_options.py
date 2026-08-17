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

from src.config import get_options_settings
from src.assets.manage import universo_de_analise
from src.db.connection import get_connection
from src.etl.result import DetalheAlvo, EstadoAlvo, ResultadoColeta

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


class RecursoIndisponivelNoPlano(RuntimeError):
    """O provedor confirmou que o recurso exige outro plano."""


def _recurso_indisponivel_no_plano(resp: requests.Response) -> bool:
    """Reconhece somente códigos estruturados já confirmados no provedor."""
    if resp.status_code < 400:
        return False
    try:
        payload = resp.json()
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False

    codigos = [payload.get("code")]
    erro = payload.get("error")
    if isinstance(erro, dict):
        codigos.append(erro.get("code"))
    elif isinstance(erro, str):
        codigos.append(erro)
    return "FEATURE_NOT_AVAILABLE" in codigos


def fetch(ticker_objeto: str) -> list[dict]:
    settings = get_options_settings()
    if not settings.oplab_token:
        raise RuntimeError(
            "OPLAB_TOKEN não configurado: fetch_options ainda usa o provedor "
            "OpLab abandonado; não há coleta de opções disponível no plano atual."
        )
    resp = requests.get(
        OPLAB_OPTIONS_URL.format(ticker=ticker_objeto),
        headers={"Access-Token": settings.oplab_token},
        timeout=15,
    )
    if _recurso_indisponivel_no_plano(resp):
        raise RecursoIndisponivelNoPlano(
            f"Recurso de opções indisponível no plano para {ticker_objeto}."
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


def main(tickers: list[str] | None = None) -> ResultadoColeta:
    if tickers is None:
        tickers = _tickers_objeto_da_carteira()
    if not tickers:
        log.warning("Nenhum ticker na carteira ou watchlist — nada a coletar.")
        return ResultadoColeta.pulado("opcoes", "oplab", "universo_vazio")

    settings = get_options_settings()
    if not settings.oplab_token:
        motivo = (
            "OPLAB_TOKEN não configurado: fetch_options ainda usa o provedor "
            "OpLab abandonado; não há coleta de opções disponível no plano atual."
        )
        log.warning(motivo)
        return ResultadoColeta.de_detalhes("opcoes", "oplab", [
            DetalheAlvo(
                t,
                EstadoAlvo.BLOQUEADO,
                codigo_motivo="oplab_token_nao_configurado",
                detalhe=motivo,
                tentado=False,
            )
            for t in tickers
        ])

    total = 0
    falhas: dict[str, str] = {}
    bloqueados: dict[str, str] = {}
    detalhes: list[DetalheAlvo] = []
    for t in tickers:
        try:
            options = fetch(t)
            persistidas = upsert(t, options)
            total += persistidas
            detalhes.append(DetalheAlvo(
                t, EstadoAlvo.SUCESSO, registros_persistidos=persistidas,
            ))
            log.info("Opções de %s: %d registros.", t, len(options))
        except RecursoIndisponivelNoPlano as exc:
            bloqueados[t] = str(exc)
            detalhes.append(DetalheAlvo(
                t,
                EstadoAlvo.BLOQUEADO,
                codigo_motivo="recurso_indisponivel_no_plano",
                detalhe=str(exc),
            ))
            log.warning("Opções de %s bloqueadas pelo plano: %s", t, exc)
        except Exception as exc:  # noqa: BLE001 — isolamos falha por ticker de propósito
            falhas[t] = str(exc)
            detalhes.append(DetalheAlvo(
                t,
                EstadoAlvo.FALHA,
                codigo_motivo="erro_coleta",
                detalhe=str(exc),
            ))
            log.error("Falha ao coletar opções de %s: %s", t, exc)
    log.info(
        "Total de opções atualizadas: %d. Tickers bloqueados: %s. "
        "Tickers com falha: %s",
        total,
        sorted(bloqueados) if bloqueados else "nenhum",
        sorted(falhas) if falhas else "nenhum",
    )
    if bloqueados:
        for t, motivo in bloqueados.items():
            log.warning("  - %s: %s", t, motivo)
    if falhas:
        for t, motivo in falhas.items():
            log.error("  - %s: %s", t, motivo)
    return ResultadoColeta.de_detalhes("opcoes", "oplab", detalhes)


def _tickers_objeto_da_carteira() -> list[str]:
    """Universo de coleta: CARTEIRA ∪ VIGIADOS (migração 006).

    É o que permite procurar oportunidade em opção de ativo que ainda não
    se tem — sem isso a cadeia só era coletada para o que já estava em
    carteira, e nenhuma varredura era possível.
    """
    return universo_de_analise()


if __name__ == "__main__":
    main()
