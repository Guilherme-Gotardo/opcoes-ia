"""Configuração central do projeto. Lê tudo de variáveis de ambiente — nunca
hardcode chave de API ou string de conexão em código."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    oplab_token: str
    brapi_token: str
    news_api_key: str
    brapi_requests_dia_maximo: int

    @classmethod
    def load(cls) -> "Settings":
        missing = [
            k for k in ("DATABASE_URL", "OPLAB_TOKEN", "BRAPI_TOKEN")
            if not os.getenv(k)
        ]
        if missing:
            raise RuntimeError(
                f"Variáveis de ambiente ausentes: {', '.join(missing)}. "
                "Copie .env.example para .env e preencha."
            )
        return cls(
            database_url=os.environ["DATABASE_URL"],
            oplab_token=os.environ["OPLAB_TOKEN"],
            brapi_token=os.environ["BRAPI_TOKEN"],
            news_api_key=os.getenv("NEWS_API_KEY", ""),
            # Plano Free da Brapi: 15.000 requests/mês, meta operacional de
            # ~600/dia (ver design.md, decisão 7 da change
            # build-portfolio-mvp-flow). Configurável para quando o plano
            # mudar (ex.: Pro = 500k/mês).
            brapi_requests_dia_maximo=int(os.getenv("BRAPI_REQUESTS_DIA_MAXIMO", "600")),
        )


settings = None  # carregado sob demanda via get_settings()


def get_settings() -> Settings:
    global settings
    if settings is None:
        settings = Settings.load()
    return settings
