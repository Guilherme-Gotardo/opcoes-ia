"""Prepara um banco alvo: aplica `schema.sql` e as migrações em ordem.

Existe porque subir o schema num banco novo era um `psql` decorado — o
`README.md` de `migrations/` dizia "ainda não há runner automático". Para
uma instância só isso é tolerável; para manter o banco gerenciado e o local
descartável com a MESMA estrutura, não é.

Uso:
    python -m src.db.bootstrap
    python -m src.db.bootstrap --dry-run

SEMPRE OS DOIS, SEMPRE NA ORDEM
-------------------------------
Aplica `schema.sql` e depois cada migração, sem verificar o que já existe.
É seguro porque tudo é idempotente (`CREATE TABLE IF NOT EXISTS` etc., regra
1 do README de migrações) e mantém um caminho único para banco novo e banco
existente. Detectar "está vazio?" e escolher entre os dois criaria duas
trilhas, sendo a mais rara — banco parcialmente migrado — a menos testada.

FALHA É TOTAL, NUNCA PARCIAL
----------------------------
Qualquer erro interrompe com código não zero, nomeando o arquivo. Um
bootstrap que aplica metade do schema e reporta sucesso deixa o banco num
estado que ninguém consegue descrever, e o sintoma aparece muito depois como
coluna faltando em produção. Cada arquivo roda na sua própria transação: um
`.sql` que falha não deixa metade de si mesmo aplicado.

A SENHA NUNCA APARECE
---------------------
O relato identifica host e base antes de aplicar qualquer coisa — o modo de
falha previsível deste comando é rodar no ambiente errado, e ver o destino a
tempo é o que permite abortar. Mas a string de conexão completa em log de CI
seria vazamento de credencial, então ela é sempre reduzida a host/base.
"""
import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

DB_DIR = Path(__file__).resolve().parent
SCHEMA = DB_DIR / "schema.sql"
MIGRATIONS_DIR = DB_DIR / "migrations"
MIGRATION_LOCK_ID = 7168735202640912781

#: Prefixo numérico da migração (`001_earnings_events.sql`).
_PREFIXO = re.compile(r"^(\d+)_")


class BootstrapError(RuntimeError):
    """Falha ao preparar o banco. Sempre nomeia a causa."""


def alvo_legivel(url: str) -> str:
    """`host:porta/base` a partir da URL, SEM usuário nem senha.

    Nunca devolve a URL crua: é isto que impede a credencial de cair no log
    do CI ou numa mensagem de erro.
    """
    partes = urlsplit(url)
    host = partes.hostname or "(host desconhecido)"
    porta = f":{partes.port}" if partes.port else ""
    base = (partes.path or "").lstrip("/") or "(base desconhecida)"
    return f"{host}{porta}/{base}"


def migracoes() -> list[Path]:
    """Migrações em ordem crescente de número.

    Ordena pelo prefixo convertido para inteiro, não pelo nome: com ordem
    alfabética, um dia `10_...` viria antes de `9_...` e a migração seria
    aplicada fora de ordem sem ninguém notar.
    """
    if not MIGRATIONS_DIR.is_dir():
        return []
    encontradas = []
    for caminho in MIGRATIONS_DIR.glob("*.sql"):
        m = _PREFIXO.match(caminho.name)
        if not m:
            raise BootstrapError(
                f"migração fora da convenção de nomes: {caminho.name}. "
                "Use NNN_descricao_curta.sql (ver migrations/README.md)."
            )
        encontradas.append((int(m.group(1)), caminho))
    return [caminho for _, caminho in sorted(encontradas)]


def arquivos_a_aplicar() -> list[Path]:
    """`schema.sql` primeiro, migrações depois."""
    if not SCHEMA.is_file():
        raise BootstrapError(f"schema não encontrado: {SCHEMA}")
    return [SCHEMA, *migracoes()]


def _database_url() -> str:
    """Lê a URL administrativa direta usada somente pela migração.

    A aplicação usa o loader isolado de banco e o endpoint pooled; bootstrap
    permanece explícito porque migração pode depender de estado de sessão.
    """
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv(DB_DIR.parent.parent / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        raise BootstrapError(
            "DATABASE_URL não está definida no ambiente. Copie .env.example "
            "para .env e preencha, ou exporte a variável antes de rodar."
        )
    return url


def aplicar(url: str, arquivos: list[Path]) -> None:
    """Aplica cada arquivo em sua própria transação."""
    try:
        conn = psycopg.connect(url)
    except psycopg.Error as exc:
        # `exc` do psycopg não traz a senha, mas o alvo é reimpresso a partir
        # de `alvo_legivel` para garantir que nada cru vaze aqui.
        raise BootstrapError(
            f"não foi possível conectar em {alvo_legivel(url)}: {exc}"
        ) from exc

    lock_adquirido = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
        lock_adquirido = True
        for caminho in arquivos:
            sql = caminho.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
            except psycopg.Error as exc:
                conn.rollback()
                raise BootstrapError(
                    f"falha ao aplicar {caminho.name}: {exc}"
                ) from exc
            print(f"  aplicado: {caminho.name}")
    finally:
        try:
            if lock_adquirido:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))
        except psycopg.Error:
            # Fechar a sessão libera o advisory lock mesmo se o unlock explícito
            # falhar; nunca substitui o erro original da migração.
            pass
        finally:
            conn.close()


def executar(dry_run: bool = False) -> int:
    url = _database_url()
    arquivos = arquivos_a_aplicar()

    # O alvo vem ANTES de qualquer escrita: é a última chance de abortar
    # depois de perceber que a variável aponta para o banco errado.
    print(f"Alvo: {alvo_legivel(url)}")
    print(f"Arquivos a aplicar ({len(arquivos)}), nesta ordem:")
    for caminho in arquivos:
        print(f"  - {caminho.name}")

    if dry_run:
        print("Dry-run: nada foi aplicado.")
        return 0

    aplicar(url, arquivos)
    print(f"Banco preparado: {alvo_legivel(url)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Aplica schema.sql e as migrações, em ordem, ao banco indicado "
            "por DATABASE_URL. Idempotente: rodar de novo é inofensivo."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Mostra o alvo e os arquivos que seriam aplicados, sem escrever.",
    )
    args = parser.parse_args(argv)

    try:
        return executar(dry_run=args.dry_run)
    except BootstrapError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
