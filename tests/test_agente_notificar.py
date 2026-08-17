import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.agente.notificar import ConfigSMTP, NotificacaoErro, notificar_relatorio


def test_smtp_nao_configurado_eh_ausencia_explicita():
    assert ConfigSMTP.from_env({}) is None


@pytest.mark.parametrize("env", [
    {"SMTP_HOST": "smtp.exemplo.com"},
    {"SMTP_TO": "voce@exemplo.com"},
    {"SMTP_HOST": "smtp.exemplo.com", "SMTP_TO": "voce@exemplo.com",
     "SMTP_USER": "usuario"},
])
def test_smtp_parcial_nao_finge_configuracao(env):
    with pytest.raises(NotificacaoErro):
        ConfigSMTP.from_env(env)


def test_relatorio_sem_smtp_continua_disponivel():
    relatorio = SimpleNamespace(
        texto="Dia calmo.", modelo="claude-sonnet-5", fontes=[]
    )
    with patch.dict("os.environ", {}, clear=True):
        assert notificar_relatorio(dt.date(2026, 8, 17), relatorio) is False


def test_relatorio_configurado_chama_smtp_sem_expor_senha():
    config = ConfigSMTP(
        host="smtp.exemplo.com", port=587,
        destinatarios=("voce@exemplo.com",), remetente="bot@exemplo.com",
        usuario="usuario", senha="segredo",
    )
    relatorio = SimpleNamespace(
        texto="Dia calmo.", modelo="claude-sonnet-5", fontes=["https://fonte"]
    )
    with patch("src.agente.notificar.ConfigSMTP.from_env", return_value=config), \
         patch("src.agente.notificar.enviar") as enviar:
        assert notificar_relatorio(dt.date(2026, 8, 17), relatorio) is True

    enviar.assert_called_once()
    assunto, corpo, recebido = enviar.call_args.args
    assert assunto == "opcoes-ia — relatório 2026-08-17"
    assert "Dia calmo." in corpo and "https://fonte" in corpo
    assert recebido is config
    assert "segredo" not in corpo
