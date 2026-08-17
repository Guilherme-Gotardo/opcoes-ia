"""Reserva idempotente da entrega de um relatório do agente por canal."""
import datetime as dt
import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from src.db.connection import get_connection
from src.observability.logging import sanitizar_texto


@dataclass(frozen=True)
class Notificacao:
    id: int
    execution_id: uuid.UUID
    relatorio_agente_id: int
    canal: str
    status: str
    reservado_em: dt.datetime
    concluido_em: dt.datetime | None
    detalhe: dict[str, Any]
    erro_sanitizado: str | None


@dataclass(frozen=True)
class ReservaNotificacao:
    notificacao: Notificacao
    adquirida: bool

    @property
    def duplicada(self) -> bool:
        return not self.adquirida


_COLUNAS = (
    "id, execution_id, relatorio_agente_id, canal, status, reservado_em, "
    "concluido_em, detalhe, erro_sanitizado"
)


def _notificacao(row) -> Notificacao:
    detalhe = row[7]
    if isinstance(detalhe, str):
        detalhe = json.loads(detalhe)
    return Notificacao(
        id=row[0], execution_id=row[1], relatorio_agente_id=row[2], canal=row[3],
        status=row[4], reservado_em=row[5], concluido_em=row[6],
        detalhe=detalhe or {}, erro_sanitizado=row[8],
    )


def reservar(relatorio_agente_id: int, canal: str) -> ReservaNotificacao:
    if not canal:
        raise ValueError("canal é obrigatório")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO notificacoes_relatorio (
                execution_id, relatorio_agente_id, canal, status
            )
            SELECT execution_id, id, %s, 'reservada'
            FROM relatorios_agente
            WHERE id = %s AND execution_id IS NOT NULL
            ON CONFLICT (relatorio_agente_id, canal) DO NOTHING
            RETURNING {_COLUNAS}
            """,
            (canal, relatorio_agente_id),
        )
        row = cur.fetchone()
        adquirida = row is not None
        if row is None:
            cur.execute(
                f"SELECT {_COLUNAS} FROM notificacoes_relatorio "
                "WHERE relatorio_agente_id = %s AND canal = %s",
                (relatorio_agente_id, canal),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise ValueError("relatório do agente inexistente ou sem execução vinculada")
    return ReservaNotificacao(_notificacao(row), adquirida)


def concluir(
    notificacao_id: int, detalhe: Mapping[str, Any] | None = None,
) -> Notificacao:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE notificacoes_relatorio
            SET status = 'enviada', concluido_em = now(), detalhe = %s,
                erro_sanitizado = NULL
            WHERE id = %s AND status = 'reservada'
            RETURNING {_COLUNAS}
            """,
            (json.dumps(dict(detalhe or {}), ensure_ascii=False, default=str),
             notificacao_id),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                f"SELECT {_COLUNAS} FROM notificacoes_relatorio WHERE id = %s",
                (notificacao_id,),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise ValueError("notificação inexistente")
    registro = _notificacao(row)
    if registro.status != "enviada":
        raise ValueError(f"notificação já encerrada como {registro.status!r}")
    return registro


def falhar(notificacao_id: int, erro: BaseException | str) -> Notificacao:
    erro_limpo = sanitizar_texto(str(erro))
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE notificacoes_relatorio
            SET status = 'falhou', concluido_em = now(), erro_sanitizado = %s
            WHERE id = %s AND status = 'reservada'
            RETURNING {_COLUNAS}
            """,
            (erro_limpo, notificacao_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise ValueError("notificação inexistente ou já encerrada")
    return _notificacao(row)
