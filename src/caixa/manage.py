"""Registro do caixa/garantia disponível.

POR QUE ISTO EXISTE
-------------------
`strategy.covered.avaliar()` suporta covered put desde sempre e exige
`caixa_disponivel`: sem garantia para honrar o exercício ao strike, a
operação não é coberta — é put descoberta, com risco que o projeto não
aceita. Só que não havia onde registrar esse caixa, então nenhuma put era
avaliada contra a carteira real. O gap estava documentado no `CLAUDE.md`;
esta é a peça que faltava.

LANÇAMENTOS, NÃO SALDO
----------------------
O saldo é a SOMA dos lançamentos, nunca um número que se sobrescreve. Um
saldo sobrescrito perde como se chegou até ele — e é esse "como" que
explica, meses depois, por que a avaliação de uma data aceitou ou recusou
uma operação. Mesma razão de `posicoes` nunca apagar linha.

ISTO NÃO FALA COM BANCO NENHUM
------------------------------
É espelho do que o usuário informa, como todo o resto do cadastro. O
sistema não consulta corretora nem concilia extrato.
"""
import argparse
import logging

from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class LancamentoInvalido(ValueError):
    """Lançamento que não representa movimento de caixa."""


def registrar(valor: float, descricao: str | None = None) -> int:
    """Registra um lançamento. Positivo aporta, negativo retira.

    Zero é recusado: não é movimento, e aceitar produziria linha que só
    polui o extrato sem mudar o saldo.
    """
    if valor == 0:
        raise LancamentoInvalido(
            "valor não pode ser zero — isso não é um movimento de caixa."
        )
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO caixa_lancamentos (valor, descricao) VALUES (%s, %s) "
            "RETURNING id",
            (valor, descricao),
        )
        lancamento_id = cur.fetchone()[0]
        conn.commit()
    log.info("Lançamento de caixa: id=%d valor=%.2f", lancamento_id, valor)
    return lancamento_id


def saldo() -> float:
    """Soma dos lançamentos. Zero quando não há nenhum — e zero aqui
    significa "sem garantia registrada", que é o que barra a put coberta."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(valor), 0) FROM caixa_lancamentos")
        return float(cur.fetchone()[0])


def extrato(limite: int = 50) -> list[dict]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, valor, descricao, ocorrido_em FROM caixa_lancamentos "
            "ORDER BY ocorrido_em DESC, id DESC LIMIT %s",
            (limite,),
        )
        colunas = [d.name for d in cur.description]
        return [dict(zip(colunas, row)) for row in cur.fetchall()]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Caixa/garantia disponível.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="registra um lançamento")
    p_add.add_argument("valor", type=float, help="positivo aporta, negativo retira")
    p_add.add_argument("--descricao", default=None)

    sub.add_parser("saldo", help="mostra o saldo atual")
    sub.add_parser("extrato", help="lista os lançamentos recentes")

    args = parser.parse_args(argv)
    if args.cmd == "add":
        registrar(args.valor, args.descricao)
        print(f"Saldo atual: R$ {saldo():,.2f}")
    elif args.cmd == "saldo":
        print(f"R$ {saldo():,.2f}")
    else:
        for l in extrato():
            print(f"{l['ocorrido_em']:%d/%m/%Y}  {l['valor']:>12,.2f}  "
                  f"{l['descricao'] or ''}")


if __name__ == "__main__":
    main()
