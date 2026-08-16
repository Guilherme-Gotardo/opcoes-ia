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
import datetime as dt
import logging

from src.assets.manage import ativo_existe
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
    ticker_objeto: str | None = None,
    strike: float | None = None,
    vencimento: "dt.date | str | None" = None,
) -> int:
    """Registra uma nova posição em `posicoes`. Retorna o id gerado.

    Regras de validação (nunca "arredondar" para aceitar uma entrada
    inválida):
    - tipo_ativo precisa ser 'ACAO' ou 'OPCAO'
    - quantidade não pode ser zero (não é uma posição)
    - preco_medio precisa ser maior que zero
    - `ticker_objeto`, `strike` e `vencimento` só fazem sentido em OPCAO

    Os três campos de opção são OPCIONAIS por compatibilidade com o que já
    está gravado, mas sem eles a operação não pode ser acompanhada: não há
    como comparar strike com cotação nem contar dias para o vencimento.
    Quem registrar opção sem eles recebe a posição em carteira e fica sem o
    módulo de operações — o custo é declarado, não escondido.
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

    campos_de_opcao = {
        "ticker_objeto": ticker_objeto, "strike": strike, "vencimento": vencimento,
    }
    informados = [k for k, v in campos_de_opcao.items() if v is not None]
    if tipo_ativo == "ACAO" and informados:
        raise PosicaoInvalida(
            f"posição em ACAO não aceita {', '.join(sorted(informados))} — "
            "esses campos descrevem uma opção."
        )
    if strike is not None and strike <= 0:
        raise PosicaoInvalida(
            f"strike precisa ser maior que zero (recebido: {strike})."
        )
    if ticker_objeto is not None and not ativo_existe(ticker_objeto):
        raise PosicaoInvalida(
            f"ativo-objeto não cadastrado: {ticker_objeto.upper()}. Cadastre "
            "antes de registrar a opção:\n"
            f'  python -m src.assets.manage add {ticker_objeto.upper()} "<nome>" acao'
        )

    # O ativo precisa existir: `cotacoes.ticker` tem FK para `ativos`, então
    # uma posição em ticker não cadastrado é uma posição que o ETL não
    # consegue acompanhar. Cadastrar automaticamente exigiria inventar o
    # nome do ativo, o que a regra 1 do projeto proíbe.
    #
    # A validação só vale para ACAO: em OPCAO, `posicoes.ticker` guarda o
    # CÓDIGO da opção (ex.: PETRJ380), que não é — nem deve ser — linha em
    # `ativos`. Quem tem FK para `ativos` é `opcoes.ticker_objeto`, e essa
    # tabela é preenchida pelo ETL, que já valida o ativo-objeto. Não é
    # esquecimento: derivar o objeto a partir do código exigiria parsing de
    # código B3, que o projeto não faz em lugar nenhum.
    if tipo_ativo == "ACAO" and not ativo_existe(ticker):
        raise PosicaoInvalida(
            f"ativo não cadastrado: {ticker.upper()}. Cadastre antes de "
            "registrar a posição:\n"
            f'  python -m src.assets.manage add {ticker.upper()} "<nome do ativo>" acao'
        )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO posicoes (ticker, tipo_ativo, quantidade, preco_medio,
                                  origem, ticker_objeto, strike, vencimento)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (ticker.upper(), tipo_ativo, quantidade, preco_medio, origem,
             ticker_objeto.upper() if ticker_objeto else None, strike, vencimento),
        )
        posicao_id = cur.fetchone()[0]
        conn.commit()
    log.info(
        "Posição registrada: id=%d ticker=%s tipo=%s quantidade=%d",
        posicao_id, ticker.upper(), tipo_ativo, quantidade,
    )
    return posicao_id


#: Espelha o CHECK da migração 005. Conjunto fechado porque texto livre
#: viraria "expirou"/"expirada"/"venceu" na mesma base, e a apuração não
#: teria como somar.
MOTIVOS_FECHAMENTO = ("expirada", "recomprada", "exercida", "encerrada")


def close_posicao(
    posicao_id: int,
    motivo: str = "encerrada",
    preco_fechamento: float | None = None,
) -> None:
    """Encerra uma posição em aberto, preservando o histórico — a linha
    nunca é removida.

    `motivo` é obrigatório no banco desde a migração 005: `fechada_em`
    sozinho diz quando fechou e nunca como, e sem o como não há resultado a
    apurar. O padrão `encerrada` cobre posição em ação, que não tem
    desfecho de opção.

    `recomprada` exige preço: é o que se pagou para sair, e sem ele o
    resultado sairia superestimado.
    """
    if motivo not in MOTIVOS_FECHAMENTO:
        raise PosicaoInvalida(
            f"motivo de fechamento inválido: {motivo!r}. "
            f"Use um de: {', '.join(MOTIVOS_FECHAMENTO)}."
        )
    if motivo == "recomprada" and preco_fechamento is None:
        raise PosicaoInvalida(
            "recompra exige o preço pago para sair — sem ele o resultado da "
            "operação ficaria superestimado."
        )
    if preco_fechamento is not None and preco_fechamento < 0:
        raise PosicaoInvalida(
            f"preco_fechamento não pode ser negativo (recebido: {preco_fechamento})."
        )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE posicoes
               SET fechada_em = now(),
                   motivo_fechamento = %s,
                   preco_fechamento = %s
            WHERE id = %s AND fechada_em IS NULL
            """,
            (motivo, preco_fechamento, posicao_id),
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
    try:
        args.func(args)
    except PosicaoInvalida as exc:
        # Sem isto a orientação de cadastro sairia como traceback, enterrada
        # — mesmo tratamento de `earnings.manage` e `assets.manage`.
        parser.exit(2, f"erro: {exc}\n")


if __name__ == "__main__":
    main()
