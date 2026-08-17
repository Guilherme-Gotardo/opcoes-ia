"""Deriva a senha SMTP do SES a partir de uma secret access key da IAM.

O console do SES entrega a credencial pronta, mas por um caminho que também
cria um usuário IAM fora do Terraform — dois donos para o mesmo recurso. Aqui o
usuário é do Terraform e só a derivação acontece localmente, de forma
reproduzível.

A chave nunca é aceita por argumento de linha de comando: argumento fica no
histórico do shell e na tabela de processos, visível para qualquer processo da
máquina. A leitura é por `stdin` ou por variável de ambiente.

    aws iam create-access-key --user-name opcoes-ia-prod-smtp
    printf %s "<SecretAccessKey>" | python -m scripts.ses_smtp_password sa-east-1

O algoritmo é o publicado pela AWS: a mesma derivação SigV4 usada para assinar
requisições, com data fixa `11111111` (a credencial não expira), serviço `ses`
e mensagem `SendRawEmail`, prefixada pelo byte de versão do formato.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import sys

DATA_FIXA = "11111111"
SERVICO = "ses"
TERMINAL = "aws4_request"
MENSAGEM = "SendRawEmail"
VERSAO = 0x04

VARIAVEL_CHAVE = "AWS_SECRET_ACCESS_KEY"


def _assinar(chave: bytes, mensagem: str) -> bytes:
    return hmac.new(chave, mensagem.encode("utf-8"), hashlib.sha256).digest()


def derivar(secret_access_key: str, regiao: str) -> str:
    """Converte uma secret access key na senha SMTP daquela região.

    A região faz parte da derivação: a mesma chave produz senhas diferentes por
    região, e usar a senha de outra região falha como credencial inválida.
    """
    if not secret_access_key:
        raise ValueError("secret access key vazia")
    if not regiao:
        raise ValueError("região vazia")

    assinatura = f"AWS4{secret_access_key}".encode("utf-8")
    for parte in (DATA_FIXA, regiao, SERVICO, TERMINAL, MENSAGEM):
        assinatura = _assinar(assinatura, parte)
    return base64.b64encode(bytes([VERSAO]) + assinatura).decode("ascii")


def _ler_chave() -> str:
    """Lê a chave de stdin quando houver entrada, senão do ambiente."""
    if not sys.stdin.isatty():
        chave = sys.stdin.read().strip()
        if chave:
            return chave
    chave = os.environ.get(VARIAVEL_CHAVE, "").strip()
    if chave:
        return chave
    raise SystemExit(
        "Nenhuma chave recebida. Passe por stdin "
        f"(printf %s '<SecretAccessKey>' | ...) ou em {VARIAVEL_CHAVE}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deriva a senha SMTP do SES. A chave vem por stdin ou por "
            f"{VARIAVEL_CHAVE}, nunca por argumento."
        )
    )
    parser.add_argument("regiao", help="região da AWS, por exemplo sa-east-1")
    args = parser.parse_args(argv)

    # Um argumento com cara de chave é recusado em vez de derivado: aceitar
    # silenciosamente ensinaria o caminho que vaza no histórico do shell.
    if len(args.regiao) > 30 or args.regiao.count("-") < 1:
        raise SystemExit(
            "O primeiro argumento é a região, não a chave. "
            "A chave é lida de stdin ou do ambiente, por segurança."
        )

    print(derivar(_ler_chave(), args.regiao))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
