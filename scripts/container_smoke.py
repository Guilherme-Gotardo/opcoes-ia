"""Build-time smoke tests and post-build image security inspection."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile


API_MODULES = ("fastapi", "jwt", "mangum", "psycopg", "requests", "yaml")
OPERATIONS_MODULES = (
    "anthropic",
    "QuantLib",
    "psycopg",
    "requests",
    "yaml",
    "yfinance",
)
OPTIONAL_MODULES = ("anthropic", "QuantLib", "yfinance")
SECRET_ENV = {
    "ANTHROPIC_API_KEY",
    "BRAPI_TOKEN",
    "DATABASE_URL",
    "NEWS_API_KEY",
    "OPLAB_TOKEN",
    "SMTP_PASSWORD",
}


def _importar(modulos: tuple[str, ...]) -> None:
    for modulo in modulos:
        __import__(modulo)


def smoke_api() -> None:
    _importar(API_MODULES)
    presentes = [nome for nome in OPTIONAL_MODULES if importlib.util.find_spec(nome)]
    if presentes:
        raise AssertionError(f"dependencias operacionais presentes na API: {presentes}")

    from src.api.lambda_handler import handler

    evento = {
        "version": "2.0",
        "routeKey": "GET /health/live",
        "rawPath": "/health/live",
        "rawQueryString": "",
        "headers": {},
        "requestContext": {
            "http": {
                "method": "GET",
                "path": "/health/live",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
            },
            "stage": "$default",
        },
        "isBase64Encoded": False,
    }
    contexto = type(
        "LambdaContext",
        (),
        {"aws_request_id": "container-smoke", "function_name": "opcoes-ia-api"},
    )()
    resposta = handler(evento, contexto)
    if resposta["statusCode"] != 200:
        raise AssertionError(f"handler retornou {resposta['statusCode']}: {resposta}")
    if json.loads(resposta["body"]).get("status") != "disponivel":
        raise AssertionError(f"liveness inesperado: {resposta['body']}")


def smoke_operations() -> None:
    _importar(OPERATIONS_MODULES)
    for comando in ("intraday", "daily", "alert"):
        concluido = subprocess.run(
            [sys.executable, "-m", "src.operations", comando, "--help"],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "OPCOES_IA_ENV": "container-smoke"},
        )
        if concluido.returncode != 0 or "usage:" not in concluido.stdout.lower():
            raise AssertionError(
                f"smoke {comando} falhou ({concluido.returncode}): "
                f"{concluido.stdout}{concluido.stderr}"
            )


def verify_static(root: Path) -> None:
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")
    regras = {
        linha.strip()
        for linha in dockerignore.splitlines()
        if linha.strip() and not linha.lstrip().startswith("#")
    }
    esperadas = {
        "*",
        "**/.env",
        "**/.env.*",
        "**/*.key",
        "**/*.pem",
        "**/credentials",
        "**/credentials.*",
        "!Dockerfile.api",
        "!Dockerfile.operations",
        "!requirements/**",
        "!scripts/container_smoke.py",
        "!src/**",
        "!skills/**",
    }
    faltantes = esperadas - regras
    if faltantes:
        raise AssertionError(f"allowlist incompleta no .dockerignore: {faltantes}")
    if any(regra.startswith("!") and ".env" in regra.lower() for regra in regras):
        raise AssertionError(".env nao pode ser reincluido no contexto Docker")

    api = (root / "Dockerfile.api").read_text(encoding="utf-8")
    operations = (root / "Dockerfile.operations").read_text(encoding="utf-8")
    for nome, conteudo in (("api", api), ("operations", operations)):
        minusculo = conteudo.lower()
        if ".env" in minusculo or "copy . " in minusculo or "add . " in minusculo:
            raise AssertionError(f"Dockerfile {nome} copia contexto amplo ou .env")
        if conteudo.count("FROM --platform=linux/amd64") < 2:
            raise AssertionError(f"Dockerfile {nome} nao e multi-stage linux/amd64")
        for segredo in SECRET_ENV:
            for instrucao in ("ARG", "ENV"):
                if f"{instrucao} {segredo}" in conteudo:
                    raise AssertionError(
                        f"Dockerfile {nome} persiste segredo via {instrucao}: {segredo}"
                    )
    if 'CMD ["src.api.lambda_handler.handler"]' not in api:
        raise AssertionError("handler Lambda incorreto")
    if "QuantLib" in api or "anthropic" in api or "yfinance" in api:
        raise AssertionError("Dockerfile API referencia dependencia operacional")
    for trecho in ("USER app", "chmod 1777 /tmp", 'ENTRYPOINT ["python", "-m", "src.operations"]'):
        if trecho not in operations:
            raise AssertionError(f"guardrail operacional ausente: {trecho}")

    api_lock = (root / "requirements/api.lock").read_text(encoding="utf-8").lower()
    operations_lock = (root / "requirements/operations.lock").read_text(
        encoding="utf-8"
    ).lower()
    for pacote in ("pytest==", "httpx==", "quantlib==", "anthropic==", "yfinance=="):
        if pacote in api_lock:
            raise AssertionError(f"pacote indevido no lock API: {pacote}")
    if "pytest==" in operations_lock:
        raise AssertionError("pytest nao pertence ao lock operacional")
    for pacote in ("quantlib==", "anthropic==", "yfinance=="):
        if pacote not in operations_lock:
            raise AssertionError(f"pacote obrigatorio ausente do lock operacional: {pacote}")


def verify_image(image: str, runtime: str) -> None:
    inspecao = json.loads(
        subprocess.check_output(["docker", "image", "inspect", image], text=True)
    )[0]
    if inspecao.get("Architecture") != "amd64" or inspecao.get("Os") != "linux":
        raise AssertionError(
            f"plataforma inesperada: "
            f"{inspecao.get('Os')}/{inspecao.get('Architecture')}"
        )
    ambiente = inspecao.get("Config", {}).get("Env") or []
    expostos = [item for item in ambiente if item.split("=", 1)[0] in SECRET_ENV]
    if expostos:
        raise AssertionError(f"segredos persistidos em Config.Env: {expostos}")

    historico = subprocess.check_output(
        ["docker", "history", "--no-trunc", "--format", "{{.CreatedBy}}", image],
        text=True,
    )
    for linha in historico.splitlines():
        for segredo in SECRET_ENV:
            if f"{segredo}=" in linha:
                raise AssertionError(f"segredo persistido no historico: {segredo}")

    container_id = subprocess.check_output(
        ["docker", "create", image], text=True
    ).strip()
    try:
        processo = subprocess.Popen(["docker", "export", container_id], stdout=subprocess.PIPE)
        assert processo.stdout is not None
        proibidos = []
        with tarfile.open(fileobj=processo.stdout, mode="r|") as arquivo:
            for membro in arquivo:
                caminho = "/" + membro.name.lstrip("./")
                if Path(caminho).name == ".env" or caminho.endswith("/.aws/credentials"):
                    proibidos.append(caminho)
        if processo.wait() != 0:
            raise RuntimeError("docker export falhou")
        if proibidos:
            raise AssertionError(f"arquivos de credencial na imagem: {proibidos}")
    finally:
        subprocess.run(["docker", "rm", container_id], check=True, capture_output=True)

    if runtime == "operations":
        usuario = str(inspecao.get("Config", {}).get("User") or "")
        if not usuario or usuario in {"0", "root"}:
            raise AssertionError("imagem operacional executa como root")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("api")
    sub.add_parser("operations")
    static = sub.add_parser("static")
    static.add_argument("--root", type=Path, default=Path.cwd())
    image = sub.add_parser("image")
    image.add_argument("--name", required=True)
    image.add_argument("--runtime", choices=("api", "operations"), required=True)
    args = parser.parse_args()

    if args.command == "api":
        smoke_api()
    elif args.command == "operations":
        smoke_operations()
    elif args.command == "static":
        verify_static(args.root)
    else:
        verify_image(args.name, args.runtime)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
