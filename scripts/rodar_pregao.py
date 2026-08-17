#!/usr/bin/env python3
"""Compatibilidade do timer systemd com a CLI operacional única."""
import argparse
import sys

from src.observability.logging import configure_logging
from src.operations.orchestrator import executar_intraday


def rodar(gatilho: str = "manual", forcar: bool = False) -> int:
    return executar_intraday(gatilho=gatilho, forcar=forcar).codigo_saida


def main(argv: list[str] | None = None) -> int:
    configure_logging("intraday")
    parser = argparse.ArgumentParser(description="Um disparo do pipeline de pregão.")
    parser.add_argument("--gatilho", default="manual")
    parser.add_argument("--forcar", action="store_true")
    parser.add_argument("--janela", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-external-retry", action="append", default=[])
    args = parser.parse_args(argv)
    return executar_intraday(
        gatilho=args.gatilho,
        forcar=args.forcar,
        janela=args.janela,
        resume=args.resume,
        repetir_etapas_externas=frozenset(args.allow_external_retry),
    ).codigo_saida


if __name__ == "__main__":
    sys.exit(main())
