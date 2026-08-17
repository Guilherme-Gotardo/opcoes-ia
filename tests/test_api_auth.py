"""Fronteira hospedada: Cognito, CORS, Lambda e sinais de saúde."""
import datetime as dt
from contextlib import contextmanager
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from src.api import app as api_app
from src.api import escrita
from src.api.app import app
from src.api.auth import CognitoAccessValidator, JwksCache
from src.config import ApiSettings

ISSUER = "https://cognito-idp.sa-east-1.amazonaws.com/sa-east-1_teste"
CLIENT_ID = "client-publico"
REQUIRED_SCOPE = "opcoes-ia/api"
ORIGIN = "https://d123example.cloudfront.net"


def _chave(kid: str = "chave-1"):
    privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    publica = jwt.algorithms.RSAAlgorithm.to_jwk(privada.public_key(), as_dict=True)
    publica.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return privada, publica


def _token(privada, *, kid="chave-1", **claims):
    agora = dt.datetime.now(dt.timezone.utc)
    corpo = {
        "iss": ISSUER,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "scope": f"openid {REQUIRED_SCOPE}",
        "sub": "usuario-teste",
        "exp": agora + dt.timedelta(minutes=5),
    }
    corpo.update(claims)
    return jwt.encode(corpo, privada, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def runtime_prod():
    settings = ApiSettings.load({
        "OPCOES_IA_ENV": "prod",
        "OPCOES_IA_WEB_ORIGIN": ORIGIN,
        "COGNITO_ISSUER": ISSUER,
        "COGNITO_CLIENT_ID": CLIENT_ID,
        "COGNITO_REQUIRED_SCOPE": REQUIRED_SCOPE,
    })
    privada, publica = _chave()
    jwks = JwksCache(
        f"{ISSUER}/.well-known/jwks.json",
        fetcher=lambda _: {"keys": [publica]},
    )
    validator = CognitoAccessValidator(settings, jwks=jwks)
    anteriores = app.state.api_settings, app.state.token_validator
    app.state.api_settings = settings
    app.state.token_validator = validator
    try:
        yield TestClient(app), privada
    finally:
        app.state.api_settings, app.state.token_validator = anteriores


def _headers(token: str, origin: str = ORIGIN) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Origin": origin,
    }


def test_jwt_valido_chega_ao_handler(runtime_prod):
    cliente, privada = runtime_prod
    with patch.object(api_app, "carregar_params", return_value={
        "cotacao_frescor_maximo_horas": 72,
    }) as dominio:
        resposta = cliente.get("/parametros", headers=_headers(_token(privada)))

    assert resposta.status_code == 200
    dominio.assert_called_once()
    assert resposta.headers["access-control-allow-origin"] == ORIGIN


def test_jwt_ausente_e_rejeitado_antes_do_dominio(runtime_prod):
    cliente, _ = runtime_prod
    with patch.object(api_app, "carregar_params") as dominio:
        resposta = cliente.get("/parametros", headers={"Origin": ORIGIN})
    assert resposta.status_code == 401
    dominio.assert_not_called()


def test_jwt_expirado_e_rejeitado(runtime_prod):
    cliente, privada = runtime_prod
    expirado = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    resposta = cliente.get(
        "/parametros", headers=_headers(_token(privada, exp=expirado))
    )
    assert resposta.status_code == 401


@pytest.mark.parametrize("claim,valor", [
    ("client_id", "outra-aplicacao"),
    ("iss", "https://cognito-idp.sa-east-1.amazonaws.com/sa-east-1_outro"),
    ("scope", "openid outro/escopo"),
    ("token_use", "id"),
])
def test_jwt_com_destino_incorreto_e_rejeitado(runtime_prod, claim, valor):
    cliente, privada = runtime_prod
    resposta = cliente.get(
        "/parametros", headers=_headers(_token(privada, **{claim: valor}))
    )
    assert resposta.status_code == 401


def test_jwt_com_assinatura_incorreta_e_rejeitado(runtime_prod):
    cliente, _ = runtime_prod
    outra_privada, _ = _chave()
    resposta = cliente.get(
        "/parametros", headers=_headers(_token(outra_privada))
    )
    assert resposta.status_code == 401


def test_origem_aws_direta_sem_token_nao_contorna_cognito(runtime_prod):
    _, _ = runtime_prod
    cliente_direto = TestClient(
        app, base_url="https://abc.execute-api.sa-east-1.amazonaws.com"
    )
    resposta = cliente_direto.get("/parametros")
    assert resposta.status_code == 401


def test_post_tambem_e_protegido_antes_da_escrita(runtime_prod):
    cliente, privada = runtime_prod
    corpo = {
        "ticker": "PETR4", "tipo_ativo": "ACAO",
        "quantidade": 100, "preco_medio": 32.5,
    }
    with patch.object(escrita, "add_posicao", return_value=7) as gravar:
        sem_token = cliente.post("/posicoes", json=corpo, headers={"Origin": ORIGIN})
        com_token = cliente.post(
            "/posicoes", json=corpo, headers=_headers(_token(privada))
        )

    assert sem_token.status_code == 401
    assert com_token.status_code == 201
    gravar.assert_called_once()


def test_preflight_nao_exige_jwt_nem_executa_dominio(runtime_prod):
    cliente, _ = runtime_prod
    with patch.object(escrita, "add_posicao") as dominio:
        resposta = cliente.options("/posicoes", headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
    assert resposta.status_code == 200
    assert resposta.headers["access-control-allow-origin"] == ORIGIN
    dominio.assert_not_called()


def test_options_que_nao_e_preflight_continua_protegido(runtime_prod):
    cliente, _ = runtime_prod
    resposta = cliente.options("/posicoes")
    assert resposta.status_code == 401


def test_origem_nao_autorizada_e_recusada_antes_do_dominio(runtime_prod):
    cliente, privada = runtime_prod
    with patch.object(api_app, "carregar_params") as dominio:
        resposta = cliente.get(
            "/parametros",
            headers=_headers(_token(privada), origin="https://malicioso.example"),
        )
    assert resposta.status_code == 403
    assert "access-control-allow-origin" not in resposta.headers
    dominio.assert_not_called()


def test_cache_jwks_expira_em_janela_curta():
    settings = ApiSettings.load({
        "OPCOES_IA_ENV": "prod",
        "OPCOES_IA_WEB_ORIGIN": ORIGIN,
        "COGNITO_ISSUER": ISSUER,
        "COGNITO_CLIENT_ID": CLIENT_ID,
        "COGNITO_REQUIRED_SCOPE": REQUIRED_SCOPE,
    })
    privada, publica = _chave()
    agora = [10.0]
    chamadas = []

    def fetcher(url):
        chamadas.append(url)
        return {"keys": [publica]}

    cache = JwksCache("https://jwks", ttl_seconds=300, fetcher=fetcher,
                      clock=lambda: agora[0])
    validator = CognitoAccessValidator(settings, jwks=cache)
    token = _token(privada)
    validator.validar(token)
    validator.validar(token)
    agora[0] += 301
    validator.validar(token)

    assert chamadas == ["https://jwks", "https://jwks"]


def test_liveness_e_publico_e_nao_toca_no_banco(runtime_prod):
    cliente, _ = runtime_prod
    with patch.object(api_app, "get_connection") as conectar:
        resposta = cliente.get("/health/live")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "disponivel", "componente": "api"}
    conectar.assert_not_called()


def test_readiness_faz_somente_select_1(runtime_prod):
    cliente, _ = runtime_prod
    queries = []

    class Cursor:
        def execute(self, query):
            queries.append(query)

        def fetchone(self):
            return (1,)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Conn:
        def cursor(self):
            return Cursor()

    @contextmanager
    def conexao():
        yield Conn()

    with patch.object(api_app, "get_connection", conexao):
        resposta = cliente.get("/health/ready")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "disponivel", "componente": "neon"}
    assert queries == ["SELECT 1"]


def test_readiness_distingue_neon_indisponivel(runtime_prod):
    cliente, _ = runtime_prod
    with patch.object(api_app, "get_connection", side_effect=RuntimeError("Neon fora")):
        resposta = cliente.get("/health/ready")
    assert resposta.status_code == 503
    assert resposta.json() == {"status": "indisponivel", "componente": "neon"}


def test_handler_lambda_reutiliza_o_mesmo_app(runtime_prod):
    from src.api import lambda_handler

    assert lambda_handler.app is app
    assert callable(lambda_handler.handler)


def test_openapi_expoe_saude_e_nenhum_trigger_operacional():
    schema = app.openapi()
    paths = set(schema["paths"])
    assert {"/health/live", "/health/ready"} <= paths
    assert not paths & {"/intraday", "/daily", "/alert", "/resume"}
    assert not any(
        trecho in path
        for path in paths
        for trecho in ("executar", "avaliar", "etl", "pipeline")
    )
    assert schema["paths"]["/health/live"]["get"]["security"] == []
    assert schema["paths"]["/carteira"]["get"]["security"] == [
        {"CognitoAccessToken": []}
    ]
