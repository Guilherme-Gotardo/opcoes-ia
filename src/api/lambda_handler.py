"""Entrypoint da Lambda; reutiliza exatamente a aplicação servida por Uvicorn."""
import os

from mangum import Mangum

from src.observability.logging import configure_logging
from src.runtime_secrets import carregar_api

configure_logging("api")

if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    carregar_api()

# A credencial precisa estar no ambiente antes de Settings e rotas serem importados.
from src.api.app import app  # noqa: E402

if not app.state.api_settings.production:
    raise RuntimeError("handler Lambda exige OPCOES_IA_ENV=prod")

handler = Mangum(app, lifespan="off")
