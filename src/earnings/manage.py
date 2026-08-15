"""Gestão manual de datas de divulgação de resultado.

Espelho manual da agenda de resultados, no mesmo espírito de
`src/portfolio/manage.py`: o usuário lê a data no site de RI da companhia
e registra aqui. Nunca inferimos, estimamos ou derivamos essa data de
histórico.

Uso:
    python -m src.earnings.manage add PETR4 2026-11-06 --sessao AFTER_CLOSE \\
        --origem https://petrobras.com.br/ri/calendario
    python -m src.earnings.manage list
    python -m src.earnings.manage list --ticker PETR4
    python -m src.earnings.manage remove PETR4 2026Q3
"""
import argparse
import datetime as dt
import logging

from src.db.connection import get_connection
from src.earnings.models import (
    ModeloInvalido,
    Session,
    fiscal_period_from_release_date,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class EntradaInvalida(ValueError):
    """Entrada manual que não pode ser gravada como está.

    Falha alto em vez de normalizar: uma data ajustada silenciosamente é
    exatamente o "dado errado com cara de dado bom" que o serviço inteiro
    existe para impedir.
    """


def _parse_data(texto: str) -> dt.date:
    try:
        return dt.date.fromisoformat(texto)
    except ValueError as exc:
        raise EntradaInvalida(
            f"data inválida: {texto!r}. Use o formato AAAA-MM-DD (ex.: 2026-11-06)."
        ) from exc


def _parse_hora(texto: str | None) -> dt.time | None:
    if not texto:
        return None
    try:
        return dt.time.fromisoformat(texto)
    except ValueError as exc:
        raise EntradaInvalida(
            f"hora inválida: {texto!r}. Use HH:MM (ex.: 18:30)."
        ) from exc


def _parse_sessao(texto: str | None) -> Session:
    if not texto:
        return Session.UNKNOWN
    try:
        return Session(texto.upper())
    except ValueError as exc:
        validos = ", ".join(s.value for s in Session)
        raise EntradaInvalida(
            f"sessão inválida: {texto!r}. Use uma de: {validos}."
        ) from exc


def add_data_resultado(
    ticker: str,
    data: dt.date,
    fiscal_period: str | None = None,
    hora: dt.time | None = None,
    sessao: Session = Session.UNKNOWN,
    origem: str | None = None,
    observacao: str | None = None,
) -> str:
    """Registra (ou corrige) a data de resultado de um ativo.

    Regravar o mesmo (ticker, trimestre) é uma CORREÇÃO: atualiza a linha e
    renova `atualizado_em`, em vez de empilhar duas datas divergentes que
    depois brigariam entre si na resolução de conflitos.
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise EntradaInvalida("ticker é obrigatório.")

    if fiscal_period is None:
        fiscal_period = fiscal_period_from_release_date(data)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO earnings_manual_entries (
                ticker, fiscal_period, data_resultado, hora_resultado,
                session, origem, observacao
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (ticker, fiscal_period) DO UPDATE SET
                data_resultado = EXCLUDED.data_resultado,
                hora_resultado = EXCLUDED.hora_resultado,
                session        = EXCLUDED.session,
                origem         = EXCLUDED.origem,
                observacao     = EXCLUDED.observacao,
                atualizado_em  = now()
            """,
            (ticker, fiscal_period, data, hora, sessao.value, origem, observacao),
        )
        conn.commit()

    log.info(
        "Data de resultado registrada: %s %s em %s (sessão %s).",
        ticker, fiscal_period, data.isoformat(), sessao.value,
    )
    return fiscal_period


def remove_data_resultado(ticker: str, fiscal_period: str) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM earnings_manual_entries "
            "WHERE ticker = %s AND fiscal_period = %s",
            (ticker.upper(), fiscal_period),
        )
        removidas = cur.rowcount
        conn.commit()
    if removidas == 0:
        raise EntradaInvalida(
            f"nenhuma entrada manual encontrada para {ticker.upper()} {fiscal_period}."
        )
    log.info("Entrada removida: %s %s.", ticker.upper(), fiscal_period)


def list_datas_resultado(ticker: str | None = None) -> list[dict]:
    query = (
        "SELECT ticker, fiscal_period, data_resultado, hora_resultado, "
        "session, origem, atualizado_em FROM earnings_manual_entries"
    )
    params: tuple = ()
    if ticker:
        query += " WHERE ticker = %s"
        params = (ticker.upper(),)
    query += " ORDER BY ticker, data_resultado"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        colunas = [d.name for d in cur.description]
        return [dict(zip(colunas, row)) for row in cur.fetchall()]


def _cmd_add(args: argparse.Namespace) -> None:
    periodo = add_data_resultado(
        ticker=args.ticker,
        data=_parse_data(args.data),
        fiscal_period=args.periodo,
        hora=_parse_hora(args.hora),
        sessao=_parse_sessao(args.sessao),
        origem=args.origem,
        observacao=args.observacao,
    )
    print(f"Registrado: {args.ticker.upper()} {periodo} em {args.data}.")


def _cmd_remove(args: argparse.Namespace) -> None:
    remove_data_resultado(args.ticker, args.periodo)
    print(f"Removido: {args.ticker.upper()} {args.periodo}.")


def _cmd_list(args: argparse.Namespace) -> None:
    entradas = list_datas_resultado(args.ticker)
    if not entradas:
        print("Nenhuma data de resultado registrada.")
        return
    hoje = dt.datetime.now(dt.timezone.utc).date()
    for e in entradas:
        dias = (e["data_resultado"] - hoje).days
        quando = f"em {dias}d" if dias >= 0 else f"há {-dias}d"
        hora = e["hora_resultado"].isoformat(timespec="minutes") if e["hora_resultado"] else "--:--"
        print(
            f"{e['ticker']:<8} {e['fiscal_period']:<8} "
            f"{e['data_resultado'].isoformat()} {hora}  "
            f"{e['session']:<15} {quando:>8}"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Gestão manual de datas de divulgação de resultado.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_add = sub.add_parser("add", help="Registrar ou corrigir uma data")
    p_add.add_argument("ticker")
    p_add.add_argument("data", help="AAAA-MM-DD")
    p_add.add_argument("--periodo", default=None,
                       help="Trimestre fiscal (ex.: 2026Q3). Derivado da data se omitido.")
    p_add.add_argument("--hora", default=None, help="HH:MM")
    p_add.add_argument("--sessao", default=None,
                       help="BEFORE_OPEN | DURING_SESSION | AFTER_CLOSE | UNKNOWN")
    p_add.add_argument("--origem", default=None, help="URL do RI de onde veio a data")
    p_add.add_argument("--observacao", default=None)
    p_add.set_defaults(func=_cmd_add)

    p_rm = sub.add_parser("remove", help="Remover uma entrada")
    p_rm.add_argument("ticker")
    p_rm.add_argument("periodo", help="Trimestre fiscal (ex.: 2026Q3)")
    p_rm.set_defaults(func=_cmd_remove)

    p_ls = sub.add_parser("list", help="Listar datas registradas")
    p_ls.add_argument("--ticker", default=None)
    p_ls.set_defaults(func=_cmd_list)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (EntradaInvalida, ModeloInvalido) as exc:
        parser.exit(2, f"erro: {exc}\n")


if __name__ == "__main__":
    main()
