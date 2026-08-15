"""Gestão do "estoque de patrimônio": entrada, encerramento e consulta de
posições em `posicoes`. Espelho manual do que o usuário realmente tem
alocado — nunca executa ordem real em corretora.

Uso:
    python -m src.portfolio.manage add PETR4 ACAO 100 32.50
    python -m src.portfolio.manage add PETRJ380 OPCAO -100 0.85
    python -m src.portfolio.manage close 1
    python -m src.portfolio.manage list
"""
import argparse
import logging

from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

TIPOS_ATIVO_VALIDOS = {"ACAO", "OPCAO"}


class PosicaoInvalida(ValueError):
    """Levantado quando os dados de uma posição não são válidos para gravação."""


def add_posicao(
    ticker: str,
    tipo_ativo: str,
    quantidade: int,
    preco_medio: float,
    origem: str = "manual",
) -> int:
    """Registra uma nova posição em `posicoes`. Retorna o id gerado.

    Regras de validação (nunca "arredondar" para aceitar uma entrada
    inválida):
    - tipo_ativo precisa ser 'ACAO' ou 'OPCAO'
    - quantidade não pode ser zero (não é uma posição)
    - preco_medio precisa ser maior que zero
    """
    tipo_ativo = tipo_ativo.upper()
    if tipo_ativo not in TIPOS_ATIVO_VALIDOS:
        raise PosicaoInvalida(
            f"tipo_ativo inválido: {tipo_ativo!r}. "
            f"Use um de {sorted(TIPOS_ATIVO_VALIDOS)}."
        )
    if quantidade == 0:
        raise PosicaoInvalida(
            "quantidade não pode ser zero — isso não representa uma posição."
        )
    if preco_medio <= 0:
        raise PosicaoInvalida(
            f"preco_medio precisa ser maior que zero (recebido: {preco_medio})."
        )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO posicoes (ticker, tipo_ativo, quantidade, preco_medio, origem)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (ticker.upper(), tipo_ativo, quantidade, preco_medio, origem),
        )
        posicao_id = cur.fetchone()[0]
        conn.commit()
    log.info(
        "Posição registrada: id=%d ticker=%s tipo=%s quantidade=%d",
        posicao_id, ticker.upper(), tipo_ativo, quantidade,
    )
    return posicao_id


def close_posicao(posicao_id: int) -> None:
    """Encerra uma posição em aberto (marca `fechada_em`), preservando o
    histórico — a linha nunca é removida."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE posicoes SET fechada_em = now()
            WHERE id = %s AND fechada_em IS NULL
            """,
            (posicao_id,),
        )
        atualizado = cur.rowcount
        conn.commit()
    if atualizado == 0:
        raise PosicaoInvalida(
            f"Nenhuma posição aberta encontrada com id={posicao_id} "
            "(ou ela já está encerrada)."
        )
    log.info("Posição encerrada: id=%d", posicao_id)


def list_posicoes_abertas(ticker: str | None = None) -> list[dict]:
    """Consulta as posições atualmente abertas (fechada_em IS NULL),
    opcionalmente filtradas por ticker. Fonte usada pelo ETL de mercado e
    pela avaliação de estratégia."""
    query = (
        "SELECT id, ticker, tipo_ativo, quantidade, preco_medio, aberta_em, origem "
        "FROM posicoes WHERE fechada_em IS NULL"
    )
    params: tuple = ()
    if ticker:
        query += " AND ticker = %s"
        params = (ticker.upper(),)
    query += " ORDER BY ticker"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        colunas = [d.name for d in cur.description]
        return [dict(zip(colunas, row)) for row in cur.fetchall()]


def _cmd_add(args: argparse.Namespace) -> None:
    posicao_id = add_posicao(
        args.ticker, args.tipo_ativo, args.quantidade, args.preco_medio
    )
    print(f"Posição {posicao_id} registrada.")


def _cmd_close(args: argparse.Namespace) -> None:
    close_posicao(args.posicao_id)
    print(f"Posição {args.posicao_id} encerrada.")


def _cmd_list(args: argparse.Namespace) -> None:
    posicoes = list_posicoes_abertas(args.ticker)
    if not posicoes:
        print("Nenhuma posição aberta.")
        return
    for p in posicoes:
        print(
            f"[{p['id']}] {p['ticker']:<12} {p['tipo_ativo']:<5} "
            f"qtd={p['quantidade']:<8} preco_medio={p['preco_medio']} "
            f"origem={p['origem']}"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Gestão do estoque de patrimônio (posições)."
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_add = sub.add_parser("add", help="Registrar nova posição")
    p_add.add_argument("ticker")
    p_add.add_argument("tipo_ativo", choices=["ACAO", "OPCAO", "acao", "opcao"])
    p_add.add_argument("quantidade", type=int)
    p_add.add_argument("preco_medio", type=float)
    p_add.set_defaults(func=_cmd_add)

    p_close = sub.add_parser("close", help="Encerrar posição existente")
    p_close.add_argument("posicao_id", type=int)
    p_close.set_defaults(func=_cmd_close)

    p_list = sub.add_parser("list", help="Listar posições abertas")
    p_list.add_argument("--ticker", default=None)
    p_list.set_defaults(func=_cmd_list)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
