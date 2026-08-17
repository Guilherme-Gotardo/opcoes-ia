"""Carregamento de credenciais AWS antes de inicializar runtimes hospedados."""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping, MutableMapping
from typing import Any


API_RUNTIME_KEYS = frozenset({"DATABASE_URL", "BRAPI_TOKEN"})

_cache: dict[str, dict[str, str]] = {}
_cache_lock = threading.Lock()


def carregar_json(
    referencia: str,
    *,
    client: Any | None = None,
) -> dict[str, str]:
    """Busca uma vez uma referência Secrets Manager e devolve cópia do JSON."""
    if not referencia:
        raise RuntimeError("referência do Secrets Manager não configurada")

    with _cache_lock:
        cached = _cache.get(referencia)
        if cached is not None:
            return dict(cached)

        if client is None:
            import boto3

            client = boto3.client("secretsmanager")
        resposta = client.get_secret_value(SecretId=referencia)
        texto = resposta.get("SecretString")
        if not isinstance(texto, str):
            raise RuntimeError("credencial de runtime deve usar SecretString JSON")
        try:
            value = json.loads(texto)
        except json.JSONDecodeError as exc:
            raise RuntimeError("credencial de runtime não contém JSON válido") from exc
        if not isinstance(value, Mapping):
            raise RuntimeError("credencial de runtime deve ser um objeto JSON")
        if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
            raise RuntimeError("chaves e valores da credencial devem ser strings")

        carregado = dict(value)
        _cache[referencia] = carregado
        return dict(carregado)


def carregar_api(
    *,
    env: MutableMapping[str, str] | None = None,
    client: Any | None = None,
) -> None:
    """Injeta o contrato mínimo da API sem aceitar credenciais operacionais."""
    target = os.environ if env is None else env
    value = carregar_json(target.get("API_RUNTIME_CONFIG_ARN", ""), client=client)
    recebidas = frozenset(value)
    if recebidas != API_RUNTIME_KEYS:
        faltantes = sorted(API_RUNTIME_KEYS - recebidas)
        extras = sorted(recebidas - API_RUNTIME_KEYS)
        detalhe = []
        if faltantes:
            detalhe.append(f"ausentes: {', '.join(faltantes)}")
        if extras:
            detalhe.append(f"não permitidas: {', '.join(extras)}")
        raise RuntimeError(f"contrato da credencial API inválido ({'; '.join(detalhe)})")
    vazias = sorted(key for key, item in value.items() if not item)
    if vazias:
        raise RuntimeError(f"valores vazios na credencial API: {', '.join(vazias)}")
    target.update(value)


def _limpar_cache_para_testes() -> None:
    with _cache_lock:
        _cache.clear()
