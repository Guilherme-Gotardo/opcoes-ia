"""Logging JSON correlacionável, sem credenciais em texto claro."""
import contextvars
import datetime as dt
import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from typing import Any, Iterator

_CONTEXTO = {
    nome: contextvars.ContextVar(f"log_{nome}", default=None)
    for nome in ("request_id", "execution_id", "stage")
}

_CHAVES_SECRETAS = re.compile(
    r"(?:password|passwd|senha|secret|token|api[_-]?key|authorization|database_url|dsn)",
    re.IGNORECASE,
)
_DSN = re.compile(
    r"(?P<scheme>postgres(?:ql)?://)(?P<user>[^:/@\s]+):(?P<password>[^@\s]+)@",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE)
_ATRIBUTO_SECRETO = re.compile(
    r"(?P<key>(?:password|passwd|senha|secret|token|api[_-]?key))=(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)
_CHAVE_ANTHROPIC = re.compile(r"\bsk-ant-[A-Za-z0-9_-]+")


def sanitizar_texto(valor: str) -> str:
    valor = _DSN.sub(r"\g<scheme>\g<user>:***@", valor)
    valor = _BEARER.sub("Bearer ***", valor)
    valor = _ATRIBUTO_SECRETO.sub(r"\g<key>=***", valor)
    return _CHAVE_ANTHROPIC.sub("sk-ant-***", valor)


def sanitizar(valor: Any) -> Any:
    if isinstance(valor, str):
        return sanitizar_texto(valor)
    if isinstance(valor, dict):
        return {
            str(chave): "***" if _CHAVES_SECRETAS.search(str(chave)) else sanitizar(item)
            for chave, item in valor.items()
        }
    if isinstance(valor, (list, tuple, set, frozenset)):
        return [sanitizar(item) for item in valor]
    if valor is None or isinstance(valor, (bool, int, float)):
        return valor
    return sanitizar_texto(str(valor))


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por evento, pronta para CloudWatch Logs Insights."""

    def __init__(self, component: str, environment: str) -> None:
        super().__init__()
        self.component = component
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        evento: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(
                record.created, tz=dt.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "component": getattr(record, "component", self.component),
            "environment": getattr(record, "environment", self.environment),
            "message": sanitizar_texto(record.getMessage()),
        }
        for nome, var in _CONTEXTO.items():
            valor = getattr(record, nome, None) or var.get()
            if valor is not None:
                evento[nome] = sanitizar(valor)
        for nome in (
            "result", "duration_ms", "attempt", "source", "ticker",
            "http_method", "http_path", "status_code", "details",
        ):
            valor = getattr(record, nome, None)
            if valor is not None:
                evento[nome] = sanitizar(valor)
        if record.exc_info:
            evento["exception"] = sanitizar_texto(self.formatException(record.exc_info))
        return json.dumps(evento, ensure_ascii=False, separators=(",", ":"))


@contextmanager
def log_context(**valores: str | None) -> Iterator[None]:
    tokens = []
    try:
        for nome, valor in valores.items():
            if nome in _CONTEXTO:
                tokens.append((_CONTEXTO[nome], _CONTEXTO[nome].set(valor)))
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def set_log_context(**valores: str | None) -> None:
    """Associa contexto ao processo de lote, que executa uma única rodada."""
    for nome, valor in valores.items():
        if nome in _CONTEXTO:
            _CONTEXTO[nome].set(valor)


def configure_logging(
    component: str,
    *,
    environment: str | None = None,
    level: str | None = None,
) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(
        component=component,
        environment=environment or os.getenv("OPCOES_IA_ENV", "local"),
    ))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel((level or os.getenv("LOG_LEVEL", "INFO")).upper())
