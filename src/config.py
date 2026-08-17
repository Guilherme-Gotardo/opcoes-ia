"""Configuração por capacidade, sempre vinda do ambiente.

Cada processo carrega apenas o que usa. Em especial, abrir uma conexão com o
banco não pode exigir token de mercado, agente ou notificação.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

Env = Mapping[str, str]


def _ambiente(env: Env | None) -> Env:
    return os.environ if env is None else env


def _obrigatorias(env: Env, nomes: tuple[str, ...]) -> None:
    ausentes = [nome for nome in nomes if not env.get(nome)]
    if ausentes:
        raise RuntimeError(
            f"Variáveis de ambiente ausentes: {', '.join(ausentes)}. "
            "Copie .env.example para .env e preencha."
        )


@dataclass(frozen=True)
class DatabaseSettings:
    database_url: str = field(repr=False)

    @classmethod
    def load(cls, env: Env | None = None) -> "DatabaseSettings":
        values = _ambiente(env)
        _obrigatorias(values, ("DATABASE_URL",))
        return cls(database_url=values["DATABASE_URL"])


@dataclass(frozen=True)
class BrapiSettings:
    brapi_token: str = field(repr=False)
    brapi_requests_dia_maximo: int = 600

    @classmethod
    def load(cls, env: Env | None = None) -> "BrapiSettings":
        values = _ambiente(env)
        _obrigatorias(values, ("BRAPI_TOKEN",))
        try:
            limite = int(values.get("BRAPI_REQUESTS_DIA_MAXIMO", "600"))
        except ValueError as exc:
            raise RuntimeError("BRAPI_REQUESTS_DIA_MAXIMO deve ser um inteiro") from exc
        if limite <= 0:
            raise RuntimeError("BRAPI_REQUESTS_DIA_MAXIMO deve ser maior que zero")
        return cls(
            brapi_token=values["BRAPI_TOKEN"],
            brapi_requests_dia_maximo=limite,
        )


@dataclass(frozen=True)
class OptionsSettings:
    oplab_token: str | None = field(default=None, repr=False)

    @classmethod
    def load(cls, env: Env | None = None) -> "OptionsSettings":
        values = _ambiente(env)
        return cls(oplab_token=values.get("OPLAB_TOKEN") or None)


@dataclass(frozen=True)
class NewsSettings:
    news_api_key: str | None = field(default=None, repr=False)

    @classmethod
    def load(cls, env: Env | None = None) -> "NewsSettings":
        values = _ambiente(env)
        return cls(news_api_key=values.get("NEWS_API_KEY") or None)


@dataclass(frozen=True)
class ApiSettings:
    environment: str
    web_origin: str
    cognito_issuer: str | None = None
    cognito_client_id: str | None = None
    cognito_required_scope: str | None = None

    @property
    def production(self) -> bool:
        return self.environment == "prod"

    @classmethod
    def load(cls, env: Env | None = None) -> "ApiSettings":
        values = _ambiente(env)
        environment = values.get("OPCOES_IA_ENV", "local").strip().lower()
        if not environment:
            raise RuntimeError("OPCOES_IA_ENV não pode ser vazio")

        if environment == "prod":
            _obrigatorias(values, (
                "OPCOES_IA_WEB_ORIGIN",
                "COGNITO_ISSUER",
                "COGNITO_CLIENT_ID",
                "COGNITO_REQUIRED_SCOPE",
            ))
            web_origin = values["OPCOES_IA_WEB_ORIGIN"].rstrip("/")
            issuer = values["COGNITO_ISSUER"].rstrip("/")
            client_id = values["COGNITO_CLIENT_ID"].strip()
            required_scope = values["COGNITO_REQUIRED_SCOPE"].strip()
        else:
            web_origin = values.get(
                "OPCOES_IA_WEB_ORIGIN", "http://localhost:5173"
            ).rstrip("/")
            issuer = None
            client_id = None
            required_scope = None

        parsed_origin = urlparse(web_origin)
        if (
            web_origin == "*"
            or parsed_origin.scheme not in {"http", "https"}
            or not parsed_origin.netloc
            or parsed_origin.path not in {"", "/"}
        ):
            raise RuntimeError("OPCOES_IA_WEB_ORIGIN deve ser uma origem HTTP(S), sem path")
        if environment == "prod" and parsed_origin.scheme != "https":
            raise RuntimeError("OPCOES_IA_WEB_ORIGIN deve usar HTTPS em produção")
        if environment == "prod" and (
            not parsed_origin.hostname
            or not parsed_origin.hostname.endswith(".cloudfront.net")
            or parsed_origin.port is not None
            or parsed_origin.query
            or parsed_origin.fragment
        ):
            raise RuntimeError(
                "OPCOES_IA_WEB_ORIGIN deve ser um hostname CloudFront HTTPS "
                "sem porta, path ou query em produção"
            )
        if environment == "prod":
            parsed_issuer = urlparse(issuer)
            if (
                parsed_issuer.scheme != "https"
                or not parsed_issuer.netloc
                or not parsed_issuer.path.strip("/")
                or parsed_issuer.params
                or parsed_issuer.query
                or parsed_issuer.fragment
            ):
                raise RuntimeError(
                    "COGNITO_ISSUER deve ser uma URL HTTPS de User Pool, sem query"
                )
            if not client_id:
                raise RuntimeError("COGNITO_CLIENT_ID não pode ser vazio")
            if not required_scope:
                raise RuntimeError("COGNITO_REQUIRED_SCOPE não pode ser vazio")

        return cls(
            environment=environment,
            web_origin=web_origin,
            cognito_issuer=issuer,
            cognito_client_id=client_id,
            cognito_required_scope=required_scope,
        )


@dataclass(frozen=True)
class RuntimeConfig:
    obrigatorias: frozenset[str]
    opcionais: frozenset[str]
    proibidas: frozenset[str]


# Contrato de least privilege usado também pela infraestrutura. SMTP continua
# validado por ConfigSMTP, e Anthropic só é exigida quando a etapa tem insumo.
RUNTIME_CONFIG: dict[str, RuntimeConfig] = {
    "api": RuntimeConfig(
        frozenset({"DATABASE_URL", "BRAPI_TOKEN"}),
        frozenset({
            "BRAPI_REQUESTS_DIA_MAXIMO", "OPCOES_IA_ENV", "OPCOES_IA_WEB_ORIGIN",
            "OPCOES_IA_COMPONENT", "COGNITO_ISSUER", "COGNITO_CLIENT_ID",
            "COGNITO_REQUIRED_SCOPE",
        }),
        frozenset({"OPLAB_TOKEN", "NEWS_API_KEY", "ANTHROPIC_API_KEY", "SMTP_PASSWORD"}),
    ),
    "intraday": RuntimeConfig(
        frozenset({"DATABASE_URL", "BRAPI_TOKEN"}),
        frozenset({"BRAPI_REQUESTS_DIA_MAXIMO", "OPCOES_IA_COMPONENT"}),
        frozenset({"OPLAB_TOKEN", "NEWS_API_KEY", "ANTHROPIC_API_KEY", "SMTP_PASSWORD"}),
    ),
    "daily": RuntimeConfig(
        frozenset({"DATABASE_URL", "BRAPI_TOKEN"}),
        frozenset({
            "BRAPI_REQUESTS_DIA_MAXIMO", "OPLAB_TOKEN", "NEWS_API_KEY",
            "ANTHROPIC_API_KEY", "SMTP_HOST", "SMTP_PORT", "SMTP_USER",
            "SMTP_PASSWORD", "SMTP_FROM", "SMTP_TO", "SMTP_STARTTLS",
            "OPCOES_IA_COMPONENT",
        }),
        frozenset(),
    ),
    "alert": RuntimeConfig(
        frozenset({"DATABASE_URL"}),
        frozenset({
            "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
            "SMTP_FROM", "SMTP_TO", "SMTP_STARTTLS", "OPCOES_IA_COMPONENT",
        }),
        frozenset({"BRAPI_TOKEN", "OPLAB_TOKEN", "NEWS_API_KEY", "ANTHROPIC_API_KEY"}),
    ),
    "migration": RuntimeConfig(
        frozenset({"DATABASE_URL"}),
        frozenset(),
        frozenset({
            "BRAPI_TOKEN", "OPLAB_TOKEN", "NEWS_API_KEY", "ANTHROPIC_API_KEY",
            "SMTP_PASSWORD",
        }),
    ),
    "ci_tests": RuntimeConfig(
        frozenset({"DATABASE_URL"}),
        frozenset(),
        frozenset({"PRODUCTION_DATABASE_URL"}),
    ),
}


def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings.load()


def get_brapi_settings() -> BrapiSettings:
    return BrapiSettings.load()


def get_options_settings() -> OptionsSettings:
    return OptionsSettings.load()


def get_news_settings() -> NewsSettings:
    return NewsSettings.load()


def get_api_settings() -> ApiSettings:
    return ApiSettings.load()
