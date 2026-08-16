"""Cadastro dos ativos acompanhados pela carteira (tabela `ativos`).

`ativos` é a entidade de REFERÊNCIA do projeto: `cotacoes.ticker`,
`opcoes.ticker_objeto` e `noticias.ticker` apontam para ela por chave
estrangeira. Até esta change, nada no projeto inseria nessa tabela — o
resultado é que numa base nova o `fetch_quotes` falhava em todo ticker com
violação de chave estrangeira. O banco local só funcionava porque as linhas
tinham sido inseridas à mão.

Uso:
    python -m src.assets.manage add PETR4 "Petrobras PN" acao \\
        --cnpj-raiz 33000167
    python -m src.assets.manage list

NOME NÃO É INVENTADO
--------------------
Cadastrar exige o nome informado por quem cadastra. O sistema não deriva
nome a partir do ticker nem consulta provedor para preencher sozinho: um
ativo chamado `PETR4` com nome `PETR4` é dado inventado com aparência de
dado bom — a regra 1 do projeto existe para impedir exatamente isso.

É por essa razão que registrar posição em ticker desconhecido FALHA em vez
de criar o ativo automaticamente.

`cnpj_raiz` é opcional para a coleta de cotações, mas é o que permite ao
`CvmProvider` mapear o dump da CVM para o ticker. Sem ele, aquele provider
avisa e pula o ativo.
"""
import argparse
import logging

from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

#: Valores aceitos em `ativos.tipo` (ver comentário em `schema.sql`).
TIPOS_VALIDOS = {"acao", "fii", "bdr"}


class AtivoInvalido(ValueError):
    """Dados de ativo que não podem ser gravados como estão.

    Falha alto em vez de completar: um cadastro "consertado" em silêncio
    grava uma referência que ninguém pediu.
    """


def _normalizar_cnpj_raiz(valor: str | None) -> str | None:
    """Aceita `33.000.167` ou `33000167`; rejeita o que não for 8 dígitos.

    A raiz do CNPJ tem 8 dígitos por definição. Aceitar 7 ou 9 gravaria um
    identificador que nunca casaria com o dump da CVM, e o sintoma seria
    "esse ativo nunca tem resultado" — indistinguível de cobertura real.
    """
    if valor is None:
        return None
    digitos = "".join(c for c in valor if c.isdigit())
    if not digitos:
        return None
    if len(digitos) != 8:
        raise AtivoInvalido(
            f"cnpj_raiz precisa ter 8 dígitos (recebido: {valor!r} → "
            f"{len(digitos)} dígito(s)). É a RAIZ do CNPJ, sem filial nem "
            "dígito verificador — ex.: 33000167 para PETR4."
        )
    return digitos


def add_ativo(
    ticker: str,
    nome: str,
    tipo: str = "acao",
    cnpj_raiz: str | None = None,
) -> str:
    """Registra (ou corrige) um ativo. Retorna o ticker normalizado.

    Regravar o mesmo ticker é uma CORREÇÃO: atualiza a linha em vez de
    duplicar ou falhar. As referências existentes sobrevivem porque a chave
    primária não muda — as cotações já coletadas continuam associadas.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise AtivoInvalido("ticker é obrigatório.")

    nome = (nome or "").strip()
    if not nome:
        raise AtivoInvalido(
            f"nome é obrigatório para {ticker} — informe o nome do ativo. "
            "O sistema não deriva nome a partir do ticker."
        )

    tipo = (tipo or "").strip().lower()
    if tipo not in TIPOS_VALIDOS:
        raise AtivoInvalido(
            f"tipo inválido: {tipo!r}. Use um de: "
            f"{', '.join(sorted(TIPOS_VALIDOS))}."
        )

    cnpj_raiz = _normalizar_cnpj_raiz(cnpj_raiz)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ativos (ticker, nome, tipo, cnpj_raiz)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (ticker) DO UPDATE SET
                nome      = EXCLUDED.nome,
                tipo      = EXCLUDED.tipo,
                -- Não apaga um CNPJ já cadastrado quando o recadastro vem
                -- sem ele: corrigir o nome não deveria custar o vínculo
                -- com a CVM.
                cnpj_raiz = COALESCE(EXCLUDED.cnpj_raiz, ativos.cnpj_raiz)
            """,
            (ticker, nome, tipo, cnpj_raiz),
        )
        conn.commit()

    log.info("Ativo cadastrado: %s (%s, tipo=%s, cnpj_raiz=%s)",
             ticker, nome, tipo, cnpj_raiz or "não informado")
    return ticker


def ativo_existe(ticker: str) -> bool:
    """O ticker está cadastrado? Usado por quem precisa validar antes de
    gravar uma referência para ele."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ativos WHERE ticker = %s",
            ((ticker or "").strip().upper(),),
        )
        return cur.fetchone() is not None


def tickers_cadastrados(tickers: list[str]) -> set[str]:
    """Subconjunto de `tickers` que está cadastrado — uma consulta só.

    Existe para o ETL conferir a lista inteira antes de inserir, em vez de
    descobrir ticker a ticker pela violação de chave estrangeira.
    """
    alvo = [(t or "").strip().upper() for t in tickers if t]
    if not alvo:
        return set()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT ticker FROM ativos WHERE ticker = ANY(%s)", (alvo,))
        return {linha[0] for linha in cur.fetchall()}


def list_ativos() -> list[dict]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, nome, tipo, cnpj_raiz, criado_em "
            "FROM ativos ORDER BY ticker"
        )
        colunas = [d.name for d in cur.description]
        return [dict(zip(colunas, row)) for row in cur.fetchall()]


def _cmd_add(args: argparse.Namespace) -> None:
    ticker = add_ativo(args.ticker, args.nome, args.tipo, args.cnpj_raiz)
    print(f"Ativo {ticker} cadastrado.")


def _cmd_list(args: argparse.Namespace) -> None:
    ativos = list_ativos()
    if not ativos:
        print(
            "Nenhum ativo cadastrado. Cadastre antes de registrar posição:\n"
            "  python -m src.assets.manage add PETR4 \"Petrobras PN\" acao "
            "--cnpj-raiz 33000167"
        )
        return
    for a in ativos:
        cnpj = a["cnpj_raiz"] or "— sem CNPJ (CVM não mapeia)"
        print(f"{a['ticker']:<8} {a['tipo']:<5} {a['nome']:<28} {cnpj}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Cadastro dos ativos acompanhados pela carteira.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_add = sub.add_parser("add", help="Cadastrar ou corrigir um ativo")
    p_add.add_argument("ticker")
    p_add.add_argument("nome", help='Nome do ativo (ex.: "Petrobras PN")')
    p_add.add_argument(
        "tipo", nargs="?", default="acao",
        help=f"Um de: {', '.join(sorted(TIPOS_VALIDOS))}. Padrão: acao.",
    )
    p_add.add_argument(
        "--cnpj-raiz", dest="cnpj_raiz", default=None,
        help="Raiz do CNPJ (8 dígitos) — liga o ativo ao dump da CVM.",
    )
    p_add.set_defaults(func=_cmd_add)

    p_list = sub.add_parser("list", help="Listar ativos cadastrados")
    p_list.set_defaults(func=_cmd_list)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except AtivoInvalido as exc:
        parser.exit(2, f"erro: {exc}\n")


if __name__ == "__main__":
    main()
