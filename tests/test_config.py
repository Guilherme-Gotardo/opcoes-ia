import pytest

from src.config import (
    ApiSettings,
    BrapiSettings,
    DatabaseSettings,
    NewsSettings,
    OptionsSettings,
    RUNTIME_CONFIG,
)


def test_banco_exige_somente_database_url():
    settings = DatabaseSettings.load({"DATABASE_URL": "postgresql://teste"})

    assert settings.database_url == "postgresql://teste"


def test_banco_nao_exige_tokens_de_outros_runtimes():
    settings = DatabaseSettings.load({"DATABASE_URL": "postgresql://teste"})

    assert settings.database_url


def test_banco_sem_url_falha_com_variavel_nomeada():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        DatabaseSettings.load({})


def test_brapi_exige_token_e_aplica_limite_padrao():
    settings = BrapiSettings.load({"BRAPI_TOKEN": "brapi"})

    assert settings.brapi_token == "brapi"
    assert settings.brapi_requests_dia_maximo == 600


@pytest.mark.parametrize("valor", ["zero", "0", "-1"])
def test_limite_brapi_invalido_falha_explicito(valor):
    with pytest.raises(RuntimeError, match="BRAPI_REQUESTS_DIA_MAXIMO"):
        BrapiSettings.load({
            "BRAPI_TOKEN": "brapi",
            "BRAPI_REQUESTS_DIA_MAXIMO": valor,
        })


def test_tokens_opcionais_nao_viram_placeholder():
    assert OptionsSettings.load({}).oplab_token is None
    assert NewsSettings.load({}).news_api_key is None


def test_settings_nao_expoem_segredos_no_repr():
    assert "senha" not in repr(DatabaseSettings.load({
        "DATABASE_URL": "postgresql://u:senha@host/db",
    }))
    assert "brapi-segredo" not in repr(BrapiSettings.load({
        "BRAPI_TOKEN": "brapi-segredo",
    }))


def test_matriz_de_runtime_aplica_least_privilege():
    assert RUNTIME_CONFIG["api"].obrigatorias == {
        "DATABASE_URL", "BRAPI_TOKEN",
    }
    assert "ANTHROPIC_API_KEY" in RUNTIME_CONFIG["api"].proibidas
    assert RUNTIME_CONFIG["alert"].obrigatorias == {"DATABASE_URL"}
    assert "BRAPI_TOKEN" in RUNTIME_CONFIG["alert"].proibidas
    assert RUNTIME_CONFIG["migration"].obrigatorias == {"DATABASE_URL"}
    assert {
        "COGNITO_ISSUER", "COGNITO_CLIENT_ID", "COGNITO_REQUIRED_SCOPE",
    } <= RUNTIME_CONFIG["api"].opcionais
    assert not any(
        nome.startswith("CLOUDFLARE")
        for runtime in RUNTIME_CONFIG.values()
        for nomes in (runtime.obrigatorias, runtime.opcionais, runtime.proibidas)
        for nome in nomes
    )


def test_api_local_tem_origem_local_sem_configuracao_cognito():
    settings = ApiSettings.load({})
    assert settings.environment == "local"
    assert settings.web_origin == "http://localhost:5173"
    assert settings.production is False
    assert settings.cognito_issuer is None


def test_api_prod_exige_origem_issuer_client_e_escopo():
    with pytest.raises(RuntimeError, match="OPCOES_IA_WEB_ORIGIN"):
        ApiSettings.load({"OPCOES_IA_ENV": "prod"})


def test_api_prod_nao_aceita_origem_local_ou_coringa():
    base = {
        "OPCOES_IA_ENV": "prod",
        "COGNITO_ISSUER": (
            "https://cognito-idp.sa-east-1.amazonaws.com/sa-east-1_teste"
        ),
        "COGNITO_CLIENT_ID": "client-id",
        "COGNITO_REQUIRED_SCOPE": "opcoes-ia/api",
    }
    with pytest.raises(RuntimeError, match="HTTPS"):
        ApiSettings.load({**base, "OPCOES_IA_WEB_ORIGIN": "http://localhost:5173"})
    with pytest.raises(RuntimeError, match="origem HTTP"):
        ApiSettings.load({**base, "OPCOES_IA_WEB_ORIGIN": "*"})
    with pytest.raises(RuntimeError, match="CloudFront"):
        ApiSettings.load({**base, "OPCOES_IA_WEB_ORIGIN": "https://site.example"})


def test_api_prod_exige_issuer_https_bem_formado():
    env = {
        "OPCOES_IA_ENV": "prod",
        "OPCOES_IA_WEB_ORIGIN": "https://d123example.cloudfront.net",
        "COGNITO_ISSUER": "cognito-idp.sa-east-1.amazonaws.com/sa-east-1_teste",
        "COGNITO_CLIENT_ID": "client-id",
        "COGNITO_REQUIRED_SCOPE": "opcoes-ia/api",
    }
    with pytest.raises(RuntimeError, match="COGNITO_ISSUER"):
        ApiSettings.load(env)
