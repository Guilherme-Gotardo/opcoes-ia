"""CLI operacional única: ``python -m src.operations <comando>``."""
import argparse
import sys

from src.observability.logging import configure_logging
from src.operations.orchestrator import (
    ETAPAS_EXTERNAS,
    executar_alerta,
    executar_daily,
    executar_intraday,
)


def _comuns(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--window", "--janela", dest="janela", default=None)
    parser.add_argument("--trigger", "--gatilho", dest="gatilho", default="manual")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--allow-external-retry", action="append", default=[], metavar="STAGE",
        choices=sorted(ETAPAS_EXTERNAS),
        help="autoriza repetir uma etapa externa que ficou ambígua após crash",
    )
    parser.add_argument(
        "--resume-after-minutes", type=int, default=60,
        help="idade mínima do heartbeat para retomar uma execução ainda ativa",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operações agendadas do opcoes-ia.")
    sub = parser.add_subparsers(dest="comando", required=True)
    intraday = sub.add_parser("intraday")
    _comuns(intraday)
    intraday.add_argument("--forcar", "--force", action="store_true")
    daily = sub.add_parser("daily")
    _comuns(daily)
    alert = sub.add_parser("alert")
    _comuns(alert)
    args = parser.parse_args(argv)

    configure_logging(f"operations-{args.comando}")
    comuns = {
        "janela": args.janela,
        "gatilho": args.gatilho,
        "resume": args.resume,
        "repetir_etapas_externas": frozenset(args.allow_external_retry),
        "minutos_resume": args.resume_after_minutes,
    }
    if args.comando == "intraday":
        resultado = executar_intraday(forcar=args.forcar, **comuns)
    elif args.comando == "daily":
        resultado = executar_daily(**comuns)
    else:
        resultado = executar_alerta(**comuns)
    return resultado.codigo_saida


if __name__ == "__main__":
    sys.exit(main())
