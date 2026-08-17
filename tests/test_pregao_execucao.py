"""Testes de src.pregao.execucao contra o Postgres real.

Pulados sem banco, no padrão de tests/test_outcome_repository.py. Marcam as
linhas com um `gatilho` sintético e limpam o que criaram.
"""
import datetime as dt
import os

import pytest

from src.pregao import execucao

psycopg = pytest.importorskip("psycopg")

#: Cabe em VARCHAR(30) e não colide com 'systemd'/'manual'.
GATILHO = "zz-teste"


def _banco_disponivel() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.execucao_pipeline')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _banco_disponivel(),
    reason="Postgres indisponível ou migração 007 não aplicada "
           "(docker compose up -d db && python -m src.db.bootstrap)",
)


@pytest.fixture(autouse=True)
def limpar():
    yield
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM execucao_pipeline WHERE gatilho = %s", (GATILHO,))
        conn.commit()


def _ler(execucao_id):
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, encerrado_em, gatilho, detalhe FROM execucao_pipeline "
            "WHERE id = %s",
            (execucao_id,),
        )
        return cur.fetchone()


# --- a linha aberta é o rastro do crash --------------------------------------

def test_iniciar_deixa_a_linha_aberta_e_ja_commitada():
    """O ponto inteiro do desenho: a linha precisa estar VISÍVEL de outra
    conexão antes de o trabalho começar. Se `iniciar` não commitasse, um
    processo morto no meio levaria a linha embora no rollback e "crashou"
    ficaria indistinguível de "o timer nunca disparou"."""
    execucao_id = execucao.iniciar(GATILHO)
    status, encerrado, gatilho, _ = _ler(execucao_id)  # conexão NOVA
    assert status == execucao.EXECUTANDO
    assert encerrado is None
    assert gatilho == GATILHO


def test_concluir_fecha_e_guarda_o_detalhe():
    execucao_id = execucao.iniciar(GATILHO)
    execucao.concluir(execucao_id, execucao.EXECUTADO, {"avaliacao": {"sugestoes": 3}})
    status, encerrado, _, detalhe = _ler(execucao_id)
    assert status == execucao.EXECUTADO
    assert encerrado is not None
    assert detalhe["avaliacao"]["sugestoes"] == 3


def test_pulado_fora_de_pregao_cabe_na_coluna():
    """Regressão da migração 007: a coluna nasceu VARCHAR(20) e o status tem
    21 caracteres, então o caminho MAIS PERCORRIDO — a maior parte das horas
    do ano não é pregão — estourava StringDataRightTruncation. O CHECK
    listava um valor que o próprio tipo não comportava."""
    assert len(execucao.PULADO) > 20
    execucao_id = execucao.iniciar(GATILHO)
    execucao.concluir(execucao_id, execucao.PULADO, {"janela": {"motivo": "domingo"}})
    assert _ler(execucao_id)[0] == execucao.PULADO


def test_detalhe_aceita_acento_e_objeto_nao_serializavel():
    """`ensure_ascii=False` + `default=str`: um traceback com data dentro não
    pode derrubar o registro da falha que ele descreve."""
    execucao_id = execucao.iniciar(GATILHO)
    execucao.concluir(
        execucao_id, execucao.FALHOU,
        {"erro": "cotação indisponível", "quando": dt.datetime.now(dt.timezone.utc)},
    )
    detalhe = _ler(execucao_id)[3]
    assert detalhe["erro"] == "cotação indisponível"
    assert isinstance(detalhe["quando"], str)


@pytest.mark.parametrize("status", [execucao.EXECUTANDO, "concluido", ""])
def test_concluir_recusa_status_invalido(status):
    """Falha em Python, com o nome da constante, em vez de virar violação de
    CHECK crua vinda do Postgres."""
    execucao_id = execucao.iniciar(GATILHO)
    with pytest.raises(ValueError):
        execucao.concluir(execucao_id, status)


# --- consultas ---------------------------------------------------------------

def test_orfas_acha_a_execucao_que_morreu_no_meio():
    execucao_id = execucao.iniciar(GATILHO)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE execucao_pipeline SET iniciado_em = now() - interval '3 hours' "
            "WHERE id = %s",
            (execucao_id,),
        )
        conn.commit()
    assert execucao_id in [e["id"] for e in execucao.orfas(minutos=60)]


def test_orfas_ignora_a_execucao_em_curso():
    """Sem o corte por tempo, a rodada que está acontecendo agora seria
    reportada como crash a cada disparo."""
    execucao_id = execucao.iniciar(GATILHO)
    assert execucao_id not in [e["id"] for e in execucao.orfas(minutos=60)]


def test_orfas_ignora_execucao_encerrada():
    execucao_id = execucao.iniciar(GATILHO)
    execucao.concluir(execucao_id, execucao.FALHOU, {})
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE execucao_pipeline SET iniciado_em = now() - interval '3 hours' "
            "WHERE id = %s",
            (execucao_id,),
        )
        conn.commit()
    assert execucao_id not in [e["id"] for e in execucao.orfas(minutos=60)]


def test_ultimas_vem_da_mais_nova_para_a_mais_antiga():
    ids = [execucao.iniciar(GATILHO) for _ in range(3)]
    for i in ids:
        execucao.concluir(i, execucao.EXECUTADO, {})
    recentes = [e["id"] for e in execucao.ultimas(10)]
    posicoes = [recentes.index(i) for i in ids]
    assert posicoes == sorted(posicoes, reverse=True)


def test_duracao_derivada_na_leitura():
    execucao_id = execucao.iniciar(GATILHO)
    assert execucao.ultimas(1)[0]["duracao_s"] is None  # ainda aberta
    execucao.concluir(execucao_id, execucao.EXECUTADO, {})
    duracao = next(e for e in execucao.ultimas(5) if e["id"] == execucao_id)["duracao_s"]
    assert duracao is not None and duracao >= 0


def test_ultima_conclusao_ignora_execucao_aberta():
    fechada = execucao.iniciar(GATILHO)
    execucao.concluir(fechada, execucao.PULADO, {})
    aberta = execucao.iniciar(GATILHO)
    ultima = execucao.ultima_conclusao()
    assert ultima is not None
    assert ultima["id"] != aberta


def test_rodou_em_conta_o_pulo_mas_nao_a_execucao_aberta():
    """Pulou por fora-de-pregão CONTA: o pipeline acordou e decidiu. É a
    diferença entre "não tinha o que fazer" e "não rodou"."""
    hoje = dt.datetime.now(dt.timezone.utc).date()
    aberta = execucao.iniciar(GATILHO)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM execucao_pipeline "
            "WHERE iniciado_em::date = %s AND status <> %s",
            (hoje, execucao.EXECUTANDO),
        )
        ja_havia = cur.fetchone()[0] > 0
    if not ja_havia:
        assert execucao.rodou_em(hoje) is False
    execucao.concluir(aberta, execucao.PULADO, {})
    assert execucao.rodou_em(hoje) is True
