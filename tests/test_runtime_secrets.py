import json

import pytest

from src import runtime_secrets


class SecretsClient:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def get_secret_value(self, **kwargs):
        self.calls.append(kwargs)
        return self.value


@pytest.fixture(autouse=True)
def limpar_cache():
    runtime_secrets._limpar_cache_para_testes()


def test_carrega_api_uma_vez_e_injeta_somente_contrato_minimo():
    client = SecretsClient({"SecretString": json.dumps({
        "DATABASE_URL": "postgresql://pooled",
        "BRAPI_TOKEN": "brapi-teste",
    })})
    env = {"API_RUNTIME_CONFIG_ARN": "arn:aws:secretsmanager:sa-east-1:123:secret:api"}

    runtime_secrets.carregar_api(env=env, client=client)
    runtime_secrets.carregar_api(env=env, client=client)

    assert client.calls == [{"SecretId": env["API_RUNTIME_CONFIG_ARN"]}]
    assert env["DATABASE_URL"] == "postgresql://pooled"
    assert env["BRAPI_TOKEN"] == "brapi-teste"


@pytest.mark.parametrize("value", [
    {},
    {"SecretBinary": b"binario"},
    {"SecretString": "não-json"},
    {"SecretString": "[]"},
    {"SecretString": '{"DATABASE_URL": 1}'},
])
def test_rejeita_resposta_ausente_ou_malformada(value):
    with pytest.raises(RuntimeError):
        runtime_secrets.carregar_json("arn:teste", client=SecretsClient(value))


@pytest.mark.parametrize("payload", [
    {"DATABASE_URL": "db"},
    {"DATABASE_URL": "db", "BRAPI_TOKEN": "token", "ANTHROPIC_API_KEY": "não"},
    {"DATABASE_URL": "", "BRAPI_TOKEN": "token"},
])
def test_api_rejeita_chave_ausente_extra_ou_vazia(payload):
    client = SecretsClient({"SecretString": json.dumps(payload)})
    env = {"API_RUNTIME_CONFIG_ARN": "arn:teste"}

    with pytest.raises(RuntimeError, match="credencial API"):
        runtime_secrets.carregar_api(env=env, client=client)
