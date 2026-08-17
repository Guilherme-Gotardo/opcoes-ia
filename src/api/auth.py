"""Validação em profundidade do access token emitido pelo Cognito."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping

import jwt
import requests

from src.config import ApiSettings

JWKS_CACHE_TTL_SECONDS = 300.0
JWKS_TIMEOUT_SECONDS = 3.0


class AccessTokenInvalido(Exception):
    """O token não autoriza acesso a esta API."""


class AccessIndisponivel(Exception):
    """As chaves necessárias para validar o token estão indisponíveis."""


JwksFetcher = Callable[[str], Mapping]
Clock = Callable[[], float]


def _buscar_jwks(url: str) -> Mapping:
    try:
        resposta = requests.get(url, timeout=JWKS_TIMEOUT_SECONDS)
        resposta.raise_for_status()
        corpo = resposta.json()
    except (requests.RequestException, ValueError) as exc:
        raise AccessIndisponivel("não foi possível consultar as chaves Cognito") from exc
    if not isinstance(corpo, Mapping) or not isinstance(corpo.get("keys"), list):
        raise AccessIndisponivel("resposta JWKS inválida")
    return corpo


class JwksCache:
    """Cache curto em memória; um ``kid`` desconhecido força uma renovação."""

    def __init__(
        self,
        url: str,
        *,
        ttl_seconds: float = JWKS_CACHE_TTL_SECONDS,
        fetcher: JwksFetcher = _buscar_jwks,
        clock: Clock = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds deve ser maior que zero")
        self._url = url
        self._ttl_seconds = ttl_seconds
        self._fetcher = fetcher
        self._clock = clock
        self._lock = threading.Lock()
        self._value: Mapping | None = None
        self._expires_at = 0.0

    def obter(self, *, renovar: bool = False) -> Mapping:
        with self._lock:
            agora = self._clock()
            if not renovar and self._value is not None and agora < self._expires_at:
                return self._value
            value = self._fetcher(self._url)
            if not isinstance(value, Mapping) or not isinstance(value.get("keys"), list):
                raise AccessIndisponivel("resposta JWKS inválida")
            self._value = value
            self._expires_at = agora + self._ttl_seconds
            return value


class CognitoAccessValidator:
    """Valida assinatura RS256 e claims próprios do access token Cognito."""

    def __init__(self, settings: ApiSettings, *, jwks: JwksCache | None = None) -> None:
        if not settings.production:
            raise ValueError("validador Cognito só deve ser criado em produção")
        assert settings.cognito_issuer is not None
        assert settings.cognito_client_id is not None
        assert settings.cognito_required_scope is not None
        self._issuer = settings.cognito_issuer
        self._client_id = settings.cognito_client_id
        self._required_scope = settings.cognito_required_scope
        self._jwks = jwks or JwksCache(
            f"{self._issuer}/.well-known/jwks.json"
        )

    def validar(self, token: str) -> None:
        try:
            cabecalho = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AccessTokenInvalido("JWT malformado") from exc

        if cabecalho.get("alg") != "RS256" or not cabecalho.get("kid"):
            raise AccessTokenInvalido("algoritmo ou kid inválido")

        jwk = self._encontrar_chave(cabecalho["kid"])
        try:
            chave = jwt.PyJWK.from_dict(jwk, algorithm="RS256").key
            claims = jwt.decode(
                token,
                key=chave,
                algorithms=["RS256"],
                issuer=self._issuer,
                options={
                    "require": [
                        "exp", "iss", "client_id", "token_use", "scope",
                    ],
                    "verify_aud": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise AccessTokenInvalido("JWT não é válido para esta API") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise AccessIndisponivel("chave pública Cognito inválida") from exc

        if claims.get("client_id") != self._client_id:
            raise AccessTokenInvalido("client_id não pertence a esta API")
        if claims.get("token_use") != "access":
            raise AccessTokenInvalido("token_use deve ser access")
        scopes = claims.get("scope", "")
        if not isinstance(scopes, str) or self._required_scope not in scopes.split():
            raise AccessTokenInvalido("escopo obrigatório ausente")

    def _encontrar_chave(self, kid: str) -> Mapping:
        for renovar in (False, True):
            conjunto = self._jwks.obter(renovar=renovar)
            for chave in conjunto["keys"]:
                if isinstance(chave, Mapping) and chave.get("kid") == kid:
                    return chave
        raise AccessTokenInvalido("kid não reconhecido")
