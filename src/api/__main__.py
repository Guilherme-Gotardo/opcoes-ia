"""Sobe a API de desenvolvimento em 127.0.0.1 — NUNCA 0.0.0.0.

É a diferença entre "acessível na minha máquina" e "acessível na rede
local". Produção usa o handler Mangum e autenticação Cognito;
este entrypoint Uvicorn permanece para o fluxo local.

Uso:
    python -m src.api

Comandos auxiliares:
    python -m src.api --schema saida.json   # salva o OpenAPI sem subir o
                                            # servidor (geração de tipos do
                                            # frontend não depende da API
                                            # estar no ar)
"""
import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    from src.observability.logging import configure_logging

    configure_logging("api")
    parser = argparse.ArgumentParser(description="API de leitura da carteira.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--schema", metavar="ARQUIVO", default=None,
        help="Salva o schema OpenAPI no arquivo e sai, sem subir o servidor.",
    )
    args = parser.parse_args(argv)

    from src.api.app import app  # import adiado: --schema não exige banco

    if args.schema:
        with open(args.schema, "w", encoding="utf-8") as f:
            json.dump(app.openapi(), f, ensure_ascii=False, indent=2)
        print(f"Schema OpenAPI salvo em {args.schema}")
        return 0

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
