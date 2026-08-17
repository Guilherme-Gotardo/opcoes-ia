#!/usr/bin/env python3
"""Alerta independente para ausência ou falha do pipeline diário.

Este script roda em timer próprio, não depende do agente de IA e envia por
SMTP. Se o banco estiver indisponível, a própria exceção também vira alerta
quando o SMTP estiver disponível.
"""
import argparse
import datetime as dt
import logging
import sys

from src.agente.notificar import ConfigSMTP, NotificacaoErro, enviar
from src.db.connection import get_connection
from src.observability.logging import configure_logging
from src.pregao import execucao
from src.pregao.calendario import (
    CalendarioInvalido,
    CalendarioVencido,
    avaliar,
    carregar,
)

log = logging.getLogger("alerta-pregao")


def _data_operacional(agora: dt.datetime) -> dt.date:
    """Usa Brasília quando o calendário está disponível; UTC é fallback."""
    try:
        fuso = carregar().fuso
    except (CalendarioVencido, CalendarioInvalido):
        fuso = dt.timezone.utc
    return agora.astimezone(fuso).date()


def verificar(agora: dt.datetime | None = None) -> tuple[bool, str]:
    """Retorna `(precisa_alertar, motivo)` sem enviar e-mail."""
    agora = agora or dt.datetime.now(dt.timezone.utc)
    try:
        janela = avaliar(agora)
    except (CalendarioVencido, CalendarioInvalido) as e:
        return True, f"calendário de pregão indisponível: {e}"
    if not janela.dia_de_pregao:
        return False, janela.motivo

    data = _data_operacional(agora)
    try:
        with get_connection() as conn, conn.cursor() as cur:
            if execucao.rodou_em(data, cur=cur):
                orfas = execucao.orfas(minutos=60, cur=cur)
                if orfas:
                    return True, f"há {len(orfas)} execução(ões) órfã(s)"
                ultima = execucao.ultima_conclusao(cur=cur)
                if ultima and ultima["status"] == execucao.FALHOU:
                    return True, "a última execução terminou com falha"
                return False, "houve execução concluída"
            return True, f"nenhuma execução concluída em {data.isoformat()}"
    except Exception as e:  # noqa: BLE001 — banco fora do ar também é alerta
        return True, f"não foi possível consultar o log de execução: {type(e).__name__}: {e}"


def rodar(agora: dt.datetime | None = None) -> int:
    precisa, motivo = verificar(agora)
    if not precisa:
        log.info("Sem alerta: %s", motivo)
        return 0
    try:
        config = ConfigSMTP.from_env()
        if config is None:
            raise NotificacaoErro(
                "alerta necessário, mas SMTP_HOST e SMTP_TO não estão configurados"
            )
        momento = agora or dt.datetime.now(dt.timezone.utc)
        data = _data_operacional(momento)
        enviar(
            f"opcoes-ia — alerta do pipeline ({data.isoformat()})",
            "O pipeline automático de pregão precisa de atenção.\n\n"
            f"Motivo: {motivo}\n"
            "Verifique o journal e a tabela execucao_pipeline.",
            config,
        )
    except NotificacaoErro as e:
        log.error("Alerta não enviado: %s", e)
        return 1
    log.warning("Alerta enviado: %s", motivo)
    return 0


def main(argv: list[str] | None = None) -> int:
    from src.operations.__main__ import main as operations_main

    # O módulo permanece como wrapper porque a unidade systemd já o usa.
    argumentos = sys.argv[1:] if argv is None else argv
    return operations_main(["alert", *argumentos])


if __name__ == "__main__":
    sys.exit(main())
