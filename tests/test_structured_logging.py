import json
import logging
from io import StringIO

from src.observability.logging import JsonFormatter, log_context, sanitizar


def _registrar(mensagem, *, extra=None, exc_info=None):
    saida = StringIO()
    handler = logging.StreamHandler(saida)
    handler.setFormatter(JsonFormatter("operations", "test"))
    logger = logging.getLogger("teste.logging.estruturado")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info(mensagem, extra=extra or {}, exc_info=exc_info)
    return json.loads(saida.getvalue())


def test_evento_json_carrega_contexto_duracao_e_resultado():
    with log_context(execution_id="exec-123", stage="quotes"):
        evento = _registrar(
            "etapa concluída",
            extra={"result": "success", "duration_ms": 12.5},
        )

    assert evento["component"] == "operations"
    assert evento["environment"] == "test"
    assert evento["execution_id"] == "exec-123"
    assert evento["stage"] == "quotes"
    assert evento["result"] == "success"
    assert evento["duration_ms"] == 12.5


def test_sanitiza_dsn_bearer_chave_e_detalhes():
    evento = _registrar(
        "falhou postgresql://user:senha@host/db Bearer abc sk-ant-segredo",
        extra={"details": {"api_key": "valor", "url": "token=abc"}},
    )
    serializado = json.dumps(evento)

    assert "senha" not in serializado
    assert "Bearer abc" not in serializado
    assert "sk-ant-segredo" not in serializado
    assert '"api_key": "valor"' not in serializado
    assert "token=abc" not in serializado


def test_sanitiza_estruturas_recursivamente():
    assert sanitizar({
        "password": "segredo",
        "nested": ["postgresql://u:p@host/db"],
    }) == {
        "password": "***",
        "nested": ["postgresql://u:***@host/db"],
    }
