"""Integração do estado operacional contra o Postgres descartável."""
import datetime as dt
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agente.notificar import ConfigSMTP, notificar_relatorio
from src.pregao import execucao
from src.report import daily
from src.report.repository import por_execucao

psycopg = pytest.importorskip("psycopg")

AMBIENTE = "zz-teste-duravel"


def _banco_disponivel() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.execucao_etapa_tentativa')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _banco_disponivel(),
    reason="Postgres descartável indisponível ou migração 010 não aplicada",
)


def _limpar() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM notificacoes_relatorio WHERE execution_id IN ("
            "SELECT execution_id FROM execucao_pipeline WHERE ambiente = %s)",
            (AMBIENTE,),
        )
        cur.execute(
            "DELETE FROM relatorios_agente WHERE execution_id IN ("
            "SELECT execution_id FROM execucao_pipeline WHERE ambiente = %s)",
            (AMBIENTE,),
        )
        cur.execute("DELETE FROM execucao_pipeline WHERE ambiente = %s", (AMBIENTE,))
        conn.commit()


@pytest.fixture(autouse=True)
def limpar_estado():
    _limpar()
    yield
    _limpar()


def _adquirir(janela: str):
    return execucao.RepositorioExecucao().adquirir(
        AMBIENTE, "daily", janela, "pytest",
    )


def test_aquisicao_concorrente_tem_um_dono_e_id_estavel():
    janela = f"concorrencia:{uuid.uuid4()}"
    with ThreadPoolExecutor(max_workers=8) as pool:
        resultados = list(pool.map(lambda _: _adquirir(janela), range(8)))

    assert sum(resultado.adquirida for resultado in resultados) == 1
    assert len({resultado.execucao.execution_id for resultado in resultados}) == 1
    assert all(resultado.execucao.janela_logica == janela for resultado in resultados)

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM execucao_pipeline "
            "WHERE ambiente = %s AND tipo_fluxo = 'daily' AND janela_logica = %s",
            (AMBIENTE, janela),
        )
        assert cur.fetchone()[0] == 1


def test_finalizacao_e_idempotente_e_guarda_apenas_erro_sanitizado():
    repo = execucao.RepositorioExecucao()
    execution_id = _adquirir(f"finalizar:{uuid.uuid4()}").execucao.execution_id
    finalizada = repo.finalizar(
        execution_id, execucao.FALHOU, {"etapa": "coleta"},
        "postgresql://usuario:senha@db/teste Bearer token-secreto",
    )

    assert finalizada.status == execucao.FALHOU
    assert finalizada.encerrado_em is not None
    assert finalizada.detalhe == {"etapa": "coleta"}
    assert "senha" not in finalizada.erro_sanitizado
    assert "token-secreto" not in finalizada.erro_sanitizado
    assert "***" in finalizada.erro_sanitizado
    assert repo.finalizar(execution_id, execucao.FALHOU).id == finalizada.id


def test_heartbeat_etapas_erro_sanitizado_e_classificacao_orfa():
    repo = execucao.RepositorioExecucao()
    aquisicao = _adquirir(f"etapas:{uuid.uuid4()}")
    execution_id = aquisicao.execucao.execution_id

    heartbeat = repo.heartbeat(execution_id)
    assert heartbeat.heartbeat_em >= aquisicao.execucao.heartbeat_em

    primeira = repo.iniciar_etapa(execution_id, "coleta", {"fonte": "brapi"})
    concluida = repo.concluir_etapa(
        execution_id, "coleta", primeira.tentativa,
        status=execucao.ETAPA_PARCIAL,
        alvos_tentados=3, alvos_persistidos=2, alvos_falhos=1,
        detalhe={"falhos": ["ZZFAIL"]},
    )
    assert concluida.status == execucao.ETAPA_PARCIAL
    assert concluida.alvos_persistidos == 2
    assert concluida.detalhe == {"falhos": ["ZZFAIL"]}

    segunda = repo.iniciar_etapa(execution_id, "coleta")
    assert segunda.tentativa == 2
    falha = repo.falhar_etapa(
        execution_id, "coleta", segunda.tentativa,
        "postgresql://usuario:senha@db/teste token=segredo",
        alvos_tentados=1, alvos_falhos=1,
    )
    assert "senha" not in falha.erro_sanitizado
    assert "segredo" not in falha.erro_sanitizado
    assert "***" in falha.erro_sanitizado

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE execucao_pipeline SET heartbeat_em = now() - interval '2 hours' "
            "WHERE execution_id = %s",
            (execution_id,),
        )
        conn.commit()
    orfas = repo.classificar_orfas(minutos=60)
    assert [item.execution_id for item in orfas] == [execution_id]
    assert repo.obter(execution_id).status == execucao.ORFA


@contextmanager
def _conexao_relatorio_fake():
    conn = MagicMock()
    yield conn


def test_relatorio_permanece_no_banco_apos_diretorio_ser_descartado(tmp_path):
    execution_id = _adquirir(f"relatorio:{uuid.uuid4()}").execucao.execution_id
    resumo = {
        "posicoes": [], "total_patrimonio": 0,
        "exposicao_pct_por_ativo": {},
    }
    data = dt.date(2026, 8, 17)
    with patch("src.report.daily.get_connection", _conexao_relatorio_fake), \
         patch("src.report.daily.carregar_params", return_value={}), \
         patch("src.report.daily._resumo_carteira", return_value=resumo), \
         patch("src.report.daily._alertas", return_value=[]), \
         patch("src.report.daily._sugestoes_do_dia", return_value=[]), \
         patch.object(daily, "REPORTS_DIR", tmp_path):
        caminho = daily.gerar_relatorio(
            data, avaliacoes=[], execution_id=execution_id,
        )

    assert caminho is not None and caminho.exists()
    shutil.rmtree(tmp_path)
    persistido = por_execucao(execution_id)
    assert persistido is not None
    assert persistido.data == data
    assert "# Relatório diário" in persistido.conteudo

    with patch("src.report.daily.get_connection", _conexao_relatorio_fake), \
         patch("src.report.daily.carregar_params", return_value={}), \
         patch("src.report.daily._resumo_carteira", return_value=resumo), \
         patch("src.report.daily._alertas", return_value=[]), \
         patch("src.report.daily._sugestoes_do_dia", return_value=[]), \
         patch.object(daily, "REPORTS_DIR", tmp_path):
        resultado = daily.gerar_relatorio(
            data, avaliacoes=[], execution_id=execution_id,
            exportar_arquivo=False,
        )
    assert resultado is None
    assert not tmp_path.exists()
    assert por_execucao(execution_id).conteudo == persistido.conteudo


def test_notificacao_do_mesmo_relatorio_e_canal_so_envia_uma_vez():
    execution_id = _adquirir(f"notificacao:{uuid.uuid4()}").execucao.execution_id
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO relatorios_agente ("
            "execution_id, data, texto, modelo"
            ") VALUES (%s, %s, %s, %s) RETURNING id",
            (execution_id, dt.date(2026, 8, 17), "Dia calmo.", "teste"),
        )
        relatorio_id = cur.fetchone()[0]
        conn.commit()

    config = ConfigSMTP(
        host="smtp.exemplo.com", port=587,
        destinatarios=("voce@exemplo.com",), remetente="bot@exemplo.com",
    )
    relatorio = SimpleNamespace(
        texto="Dia calmo.", modelo="teste", fontes=[],
    )
    with patch("src.agente.notificar.ConfigSMTP.from_env", return_value=config), \
         patch("src.agente.notificar.enviar") as enviar:
        assert notificar_relatorio(
            dt.date(2026, 8, 17), relatorio, relatorio_id=relatorio_id,
        ) is True
        assert notificar_relatorio(
            dt.date(2026, 8, 17), relatorio, relatorio_id=relatorio_id,
        ) is False

    enviar.assert_called_once()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) FROM notificacoes_relatorio "
            "WHERE relatorio_agente_id = %s GROUP BY status",
            (relatorio_id,),
        )
        assert cur.fetchone() == ("enviada", 1)
