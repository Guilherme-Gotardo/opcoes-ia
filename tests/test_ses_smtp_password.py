"""Cobre a derivação da senha SMTP do SES.

Uma nota sobre o que estes testes provam e o que não provam: o valor esperado
abaixo foi gerado por esta mesma implementação, então ele é uma trava de
REGRESSÃO — pega alteração acidental no algoritmo —, não uma prova de que o
algoritmo está certo. A prova de correção é a autenticação real contra
`email-smtp.<região>.amazonaws.com`, exercitada no provisionamento; uma
derivação errada aparece lá como `535 Authentication Credentials Invalid`.
Os demais testes cobrem propriedades que não dependem dessa circularidade.
"""

import base64

import pytest

from scripts.ses_smtp_password import VERSAO, derivar, main

# Chave de exemplo da própria documentação da AWS, nunca válida em conta real.
CHAVE_EXEMPLO = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def test_regressao_do_algoritmo():
    assert derivar(CHAVE_EXEMPLO, "sa-east-1") == (
        "BMaY55NZ29oKHOmwPeGZOue+QPW4b9Vwt4rVGhRfAK+4"
    )


def test_senha_carrega_o_byte_de_versao_e_o_hmac_completo():
    bruto = base64.b64decode(derivar(CHAVE_EXEMPLO, "sa-east-1"))
    assert bruto[0] == VERSAO
    assert len(bruto) == 33  # byte de versão + HMAC-SHA256 de 32 bytes


def test_regiao_muda_a_senha():
    """A mesma chave em região diferente não vale: falha como credencial inválida."""
    assert derivar(CHAVE_EXEMPLO, "sa-east-1") != derivar(CHAVE_EXEMPLO, "us-east-1")


def test_derivacao_e_deterministica():
    assert derivar(CHAVE_EXEMPLO, "sa-east-1") == derivar(CHAVE_EXEMPLO, "sa-east-1")


def test_chave_diferente_muda_a_senha():
    assert derivar(CHAVE_EXEMPLO, "sa-east-1") != derivar(
        CHAVE_EXEMPLO.replace("EXAMPLEKEY", "EXAMPLEKE0"), "sa-east-1"
    )


@pytest.mark.parametrize("entrada", ["", None])
def test_chave_vazia_e_recusada(entrada):
    with pytest.raises(ValueError):
        derivar(entrada or "", "sa-east-1")


def test_regiao_vazia_e_recusada():
    with pytest.raises(ValueError):
        derivar(CHAVE_EXEMPLO, "")


def test_chave_por_argumento_e_recusada():
    """Argumento fica no histórico do shell e na tabela de processos."""
    with pytest.raises(SystemExit) as excinfo:
        main([CHAVE_EXEMPLO])
    assert "região" in str(excinfo.value)


def test_ausencia_de_chave_nao_produz_senha(monkeypatch):
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    with pytest.raises(SystemExit):
        main(["sa-east-1"])
