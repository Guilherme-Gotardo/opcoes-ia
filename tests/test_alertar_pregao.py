import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch

from src.pregao import execucao
from scripts import alertar_pregao as mod


MOMENTO = dt.datetime(2026, 8, 17, 21, 0, tzinfo=dt.timezone.utc)


def test_feriado_nao_gera_alerta():
    janela = SimpleNamespace(dia_de_pregao=False, motivo="feriado: teste")
    with patch.object(mod, "avaliar", return_value=janela):
        assert mod.verificar(MOMENTO) == (False, "feriado: teste")


def test_dia_de_pregao_sem_execucao_alerta():
    janela = SimpleNamespace(dia_de_pregao=True, motivo="após o fechamento")

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return Cursor()

    conn = Connection()
    with patch.object(mod, "avaliar", return_value=janela), \
         patch.object(mod, "carregar", return_value=SimpleNamespace(
             fuso=dt.timezone.utc
         )), \
         patch.object(mod, "get_connection", return_value=conn), \
         patch.object(mod.execucao, "rodou_em", return_value=False):
        assert mod.verificar(MOMENTO) == (
            True, "nenhuma execução concluída em 2026-08-17"
        )


def test_execucao_com_falha_dispara_envio():
    config = SimpleNamespace()
    with patch.object(mod, "verificar", return_value=(True, "pipeline falhou")), \
         patch.object(mod.ConfigSMTP, "from_env", return_value=config), \
         patch.object(mod, "enviar") as enviar:
        assert mod.rodar(MOMENTO) == 0
    enviar.assert_called_once()
    assert "pipeline falhou" in enviar.call_args.args[1]


def test_alerta_sem_smtp_falha_explicitamente():
    with patch.object(mod, "verificar", return_value=(True, "sem execução")), \
         patch.object(mod.ConfigSMTP, "from_env", return_value=None):
        assert mod.rodar(MOMENTO) == 1


def test_alerta_de_calendario_invalido_ainda_tenta_enviar():
    with patch.object(mod, "verificar", return_value=(
        True, "calendário indisponível"
    )), patch.object(mod, "ConfigSMTP") as smtp, \
         patch.object(mod, "enviar") as enviar:
        smtp.from_env.return_value = SimpleNamespace()
        assert mod.rodar(MOMENTO) == 0
    enviar.assert_called_once()


def test_status_finais_do_log_sao_os_usados_pelo_alerta():
    assert execucao.FALHOU == "falhou"
