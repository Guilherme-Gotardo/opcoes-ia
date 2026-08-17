"""Entrega determinística por e-mail, depois da composição do agente.

O modelo nunca recebe uma ferramenta de envio. Este módulo é chamado pelo
script somente depois de o texto ser persistido em arquivo e no banco.
Configuração é opcional para permitir `--seco` e uso local sem SMTP; quando
parcialmente configurada, a falha é explícita.
"""
import datetime as dt
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:  # pragma: no cover
    from src.agente.relatorio import Relatorio

log = logging.getLogger(__name__)


class NotificacaoErro(RuntimeError):
    """SMTP configurado, mas a mensagem não pôde ser enviada."""


@dataclass(frozen=True)
class ConfigSMTP:
    host: str
    port: int
    destinatarios: tuple[str, ...]
    remetente: str
    usuario: str | None = None
    senha: str | None = None
    starttls: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ConfigSMTP | None":
        env = os.environ if env is None else env
        host = env.get("SMTP_HOST", "").strip()
        destinatarios = tuple(
            item.strip()
            for item in env.get("SMTP_TO", "").replace(";", ",").split(",")
            if item.strip()
        )
        if not host and not destinatarios:
            return None
        if not host or not destinatarios:
            raise NotificacaoErro(
                "SMTP_HOST e SMTP_TO devem ser configurados juntos"
            )
        try:
            port = int(env.get("SMTP_PORT", "587"))
        except ValueError as e:
            raise NotificacaoErro("SMTP_PORT deve ser um inteiro") from e
        usuario = env.get("SMTP_USER", "").strip() or None
        senha = env.get("SMTP_PASSWORD") or None
        if bool(usuario) != bool(senha):
            raise NotificacaoErro(
                "SMTP_USER e SMTP_PASSWORD devem ser configurados juntos"
            )
        remetente = env.get("SMTP_FROM", "").strip() or usuario or destinatarios[0]
        starttls = env.get("SMTP_STARTTLS", "1").lower() not in {
            "0", "false", "nao", "não", "no"
        }
        return cls(host, port, destinatarios, remetente, usuario, senha, starttls)


def enviar(assunto: str, corpo: str, config: ConfigSMTP) -> None:
    """Envia uma mensagem sem registrar credenciais no log."""
    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = config.remetente
    mensagem["To"] = ", ".join(config.destinatarios)
    mensagem.set_content(corpo)
    try:
        if config.port == 465:
            servidor = smtplib.SMTP_SSL(
                config.host, config.port, timeout=20,
                context=ssl.create_default_context(),
            )
        else:
            servidor = smtplib.SMTP(config.host, config.port, timeout=20)
        with servidor:
            servidor.ehlo()
            if config.starttls and config.port != 465:
                servidor.starttls(context=ssl.create_default_context())
                servidor.ehlo()
            if config.usuario and config.senha:
                servidor.login(config.usuario, config.senha)
            servidor.send_message(mensagem)
    except (OSError, smtplib.SMTPException) as e:
        raise NotificacaoErro(f"falha SMTP em {config.host}:{config.port}: {e}") from e


def notificar_relatorio(
    data: dt.date, relatorio: "Relatorio", *,
    relatorio_id: int | None = None, canal: str = "smtp",
) -> bool:
    """Envia o relatório; com ID persistido, reserva o canal uma única vez."""
    config = ConfigSMTP.from_env()
    if config is None:
        log.warning(
            "Notificação não configurada: defina SMTP_HOST e SMTP_TO; "
            "o relatório continua disponível em reports/ e na interface."
        )
        return False
    reserva = None
    if relatorio_id is not None:
        from src.agente.notification_repository import reservar  # noqa: PLC0415

        reserva = reservar(relatorio_id, canal)
        if reserva.duplicada:
            log.info(
                "Notificação já reservada para relatório %s no canal %s (%s).",
                relatorio_id, canal, reserva.notificacao.status,
            )
            return False
    fontes = ""
    if relatorio.fontes:
        fontes = "\n\nFontes citadas:\n" + "\n".join(relatorio.fontes)
    corpo = (
        f"Relatório do agente — {data.isoformat()}\n"
        f"Modelo: {relatorio.modelo}\n\n"
        f"{relatorio.texto}{fontes}\n"
    )
    try:
        enviar(f"opcoes-ia — relatório {data.isoformat()}", corpo, config)
    except NotificacaoErro as exc:
        if reserva is not None:
            from src.agente.notification_repository import falhar  # noqa: PLC0415

            falhar(reserva.notificacao.id, exc)
        raise
    if reserva is not None:
        from src.agente.notification_repository import concluir  # noqa: PLC0415

        concluir(
            reserva.notificacao.id,
            {"destinatarios": len(config.destinatarios)},
        )
    log.info("Relatório enviado por e-mail para %s", ", ".join(config.destinatarios))
    return True
