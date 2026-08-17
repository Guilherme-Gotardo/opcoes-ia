"""Testes de src.db.bootstrap.

Os que não precisam de banco rodam sempre; o de integração é pulado sem
Postgres, no padrão de `tests/test_earnings_integration.py`."""
import os

import pytest

from src.db import bootstrap
from src.db.bootstrap import (
    BootstrapError,
    alvo_legivel,
    arquivos_a_aplicar,
    migracoes,
)

psycopg = pytest.importorskip("psycopg")


# --- Identificação do alvo -------------------------------------------------

def test_alvo_mostra_host_e_base():
    url = "postgresql://usuario:senha@ep-abc-123.us-east-2.aws.neon.tech/opcoes_ia"
    assert alvo_legivel(url) == "ep-abc-123.us-east-2.aws.neon.tech/opcoes_ia"


def test_alvo_inclui_porta_quando_ha():
    url = "postgresql://opcoes_ia:opcoes_ia@localhost:5433/opcoes_ia"
    assert alvo_legivel(url) == "localhost:5433/opcoes_ia"


@pytest.mark.parametrize("url", [
    "postgresql://usuario:senha_secreta@host/base",
    "postgresql://usuario:senha_secreta@host:5432/base?sslmode=require",
])
def test_senha_nunca_aparece_no_alvo(url):
    """String de conexão completa em log de CI é vazamento de credencial."""
    saida = alvo_legivel(url)
    assert "senha_secreta" not in saida
    assert "usuario" not in saida


def test_alvo_nao_quebra_com_url_incompleta():
    assert "host desconhecido" in alvo_legivel("postgresql:///")


# --- Ordem das migrações ---------------------------------------------------

def test_migracoes_saem_em_ordem_numerica():
    nomes = [m.name for m in migracoes()]
    assert nomes == sorted(nomes), "as reais já estão em ordem alfabética"
    assert nomes[0].startswith("001_")


def test_ordem_e_numerica_e_nao_alfabetica(tmp_path, monkeypatch):
    """Com ordem alfabética, `10_` viria antes de `9_` e a migração seria
    aplicada fora de ordem sem ninguém notar."""
    for nome in ["009_nona.sql", "010_decima.sql", "9_sem_zero.sql"]:
        (tmp_path / nome).write_text("SELECT 1;")
    monkeypatch.setattr(bootstrap, "MIGRATIONS_DIR", tmp_path)

    nomes = [m.name for m in migracoes()]
    assert nomes.index("009_nona.sql") < nomes.index("010_decima.sql")
    assert nomes.index("9_sem_zero.sql") < nomes.index("010_decima.sql")


def test_migracao_fora_da_convencao_falha_alto(tmp_path, monkeypatch):
    (tmp_path / "corrige_coisas.sql").write_text("SELECT 1;")
    monkeypatch.setattr(bootstrap, "MIGRATIONS_DIR", tmp_path)
    with pytest.raises(BootstrapError, match="convenção de nomes"):
        migracoes()


def test_schema_vem_antes_das_migracoes():
    arquivos = arquivos_a_aplicar()
    assert arquivos[0].name == "schema.sql"
    assert all(a.name != "schema.sql" for a in arquivos[1:])


# --- Falhas explícitas -----------------------------------------------------

def test_database_url_ausente_falha_com_codigo_nao_zero(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # "Ausente" significa ausente do shell E do .env — o bootstrap carrega o
    # arquivo desde o conserto do load_dotenv, então o dublê o neutraliza.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    codigo = bootstrap.main([])
    assert codigo != 0
    assert "DATABASE_URL" in capsys.readouterr().err


# --- Endpoint pooled x direto ----------------------------------------------
#
# Os dois passaram a usar o mesmo nome de variável, então a única coisa que
# separa "URL de aplicação" de "URL de migração" é esta checagem.

def test_endpoint_pooled_e_recusado():
    url = ("postgresql://u:s@ep-lively-firefly-actnx4rn-pooler.sa-east-1"
           ".aws.neon.tech/neondb")
    with pytest.raises(BootstrapError) as excinfo:
        bootstrap.recusar_endpoint_pooled(url)
    assert "POOLED" in str(excinfo.value)
    assert "senha" not in str(excinfo.value) and ":s@" not in str(excinfo.value)


def test_endpoint_direto_e_aceito():
    url = "postgresql://u:s@ep-lively-firefly-actnx4rn.sa-east-1.aws.neon.tech/neondb"
    bootstrap.recusar_endpoint_pooled(url)  # não levanta


@pytest.mark.parametrize("host", [
    "localhost",
    "127.0.0.1",
    "db",  # nome do serviço no docker compose
])
def test_banco_descartavel_nao_e_afetado(host):
    """A convenção de rodar contra o banco local não pode ser quebrada."""
    bootstrap.recusar_endpoint_pooled(f"postgresql://u:s@{host}:5433/opcoes_ia")


def test_pooler_no_meio_do_nome_nao_e_falso_positivo():
    """Só o sufixo de host do Neon conta, não a palavra em qualquer lugar."""
    bootstrap.recusar_endpoint_pooled("postgresql://u:s@meu-pooler-db.exemplo/base")


def test_url_pooled_falha_pelo_main(monkeypatch, capsys):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://u:s@ep-abc-pooler.sa-east-1.aws.neon.tech/neondb",
    )
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    assert bootstrap.main([]) != 0
    assert "POOLED" in capsys.readouterr().err


def test_destino_inacessivel_falha_com_codigo_nao_zero(monkeypatch, capsys):
    # Porta fechada de propósito: o erro precisa nomear o alvo, não sumir.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://u:senha_secreta@127.0.0.1:1/base"
    )
    codigo = bootstrap.main([])
    assert codigo != 0
    erro = capsys.readouterr().err
    assert "127.0.0.1:1/base" in erro
    assert "senha_secreta" not in erro, "nem em erro a senha pode vazar"


# --- Dry-run ---------------------------------------------------------------

def test_dry_run_mostra_alvo_e_arquivos_sem_escrever(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/base")
    assert bootstrap.main(["--dry-run"]) == 0
    saida = capsys.readouterr().out
    assert "Alvo: 127.0.0.1:1/base" in saida
    assert "schema.sql" in saida
    assert "nada foi aplicado" in saida


def test_alvo_e_impresso_antes_dos_arquivos(monkeypatch, capsys):
    """Ver o destino a tempo é o que permite abortar quando a variável
    aponta para o banco errado."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/base")
    bootstrap.main(["--dry-run"])
    saida = capsys.readouterr().out
    assert saida.index("Alvo:") < saida.index("schema.sql")


def test_aplicar_serializa_migracao_com_advisory_lock(tmp_path, monkeypatch):
    arquivo = tmp_path / "001_teste.sql"
    arquivo.write_text("SELECT 1;", encoding="utf-8")
    executados = []

    class Cursor:
        def execute(self, query, params=None):
            executados.append((query, params))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Conn:
        def cursor(self):
            return Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(bootstrap.psycopg, "connect", lambda _: Conn())
    bootstrap.aplicar("postgresql://u:p@host/base", [arquivo])

    assert executados[0] == (
        "SELECT pg_advisory_lock(%s)", (bootstrap.MIGRATION_LOCK_ID,),
    )
    assert executados[1] == ("SELECT 1;", None)
    assert executados[-1] == (
        "SELECT pg_advisory_unlock(%s)", (bootstrap.MIGRATION_LOCK_ID,),
    )


# --- Integração (pulada sem Postgres) --------------------------------------

def _banco_disponivel() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _banco_disponivel(),
    reason="Postgres indisponível (docker compose up -d db)",
)
def test_bootstrap_e_idempotente_e_preserva_dado():
    """Roda contra o banco descartável: aplica duas vezes e confirma que a
    estrutura fica de pé e que dado existente sobrevive."""
    url = os.environ["DATABASE_URL"]
    ticker = "ZZBOOT3"

    assert bootstrap.executar() == 0

    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ativos (ticker, nome, tipo) VALUES (%s, %s, %s) "
            "ON CONFLICT (ticker) DO NOTHING",
            (ticker, "Ativo de teste do bootstrap", "acao"),
        )
        conn.commit()

    try:
        # Segunda execução: precisa concluir sem erro e não tocar no dado.
        assert bootstrap.executar() == 0

        with psycopg.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT nome FROM ativos WHERE ticker = %s", (ticker,))
            linha = cur.fetchone()
            assert linha is not None, "bootstrap não pode apagar dado existente"
            assert linha[0] == "Ativo de teste do bootstrap"

            # As tabelas centrais continuam de pé depois de duas aplicações.
            for tabela in ("posicoes", "cotacoes", "opcoes", "sugestoes",
                           "earnings_events"):
                cur.execute("SELECT to_regclass(%s)", (f"public.{tabela}",))
                assert cur.fetchone()[0] is not None, f"{tabela} sumiu"
    finally:
        with psycopg.connect(url) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM ativos WHERE ticker = %s", (ticker,))
            conn.commit()
