"""Testes do catálogo de ativos.

A rede é dublada: o que se prova é a CLASSIFICAÇÃO — quais candidatos
podem virar cadastro e por que os outros não podem. É aí que mora o risco,
porque aceitar um candidato ruim grava dado errado no lugar de recusá-lo.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.assets import catalogo
from src.assets.catalogo import CatalogoIndisponivel, buscar, cnpj_raiz_de


def _resposta(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def _item(stock, name=None, tipo="stock", subtipo="stock", setor="Energy"):
    return {
        "stock": stock, "name": name if name is not None else stock,
        "type": tipo, "subType": subtipo, "sector": setor,
    }


def _buscar(itens):
    with patch.object(catalogo, "requests") as req, \
         patch.object(catalogo, "get_settings") as cfg:
        cfg.return_value.brapi_token = "t"
        req.RequestException = requests.RequestException
        req.get.return_value = _resposta({"stocks": itens})
        return buscar("QUALQUER")


# --- o que pode ser cadastrado ---------------------------------------------

def test_acao_com_nome_real_e_cadastravel():
    c = _buscar([_item("PETR4", "PETROLEO BRASILEIRO S.A. PETROBRAS")])[0]
    assert c.cadastravel
    assert c.tipo == "acao"
    assert c.nome == "PETROLEO BRASILEIRO S.A. PETROBRAS"


def test_unit_tambem_e_acao():
    c = _buscar([_item("TAEE11", "TAESA", subtipo="unit")])[0]
    assert c.tipo == "acao" and c.cadastravel


def test_fii_e_reconhecido():
    c = _buscar([_item("HGLG11", "CSHG LOGISTICA FII", tipo="fund", subtipo="fii")])[0]
    assert c.tipo == "fii" and c.cadastravel


# --- as três armadilhas -----------------------------------------------------

def test_nome_igual_ao_ticker_nao_vira_nome():
    """Aceitar seria derivar o nome do ticker pela porta dos fundos —
    exatamente o que a regra 1 do projeto proíbe."""
    c = _buscar([_item("OXYP34", "OXYP34", tipo="bdr", subtipo="bdr")])[0]
    assert c.nome is None
    assert not c.cadastravel
    assert any("não publica o nome" in i for i in c.impedimentos)


def test_fracionario_aponta_o_papel_inteiro():
    """Cadastrar o fracionário criaria uma segunda entidade para a mesma
    empresa, e as posições ficariam divididas entre duas linhas."""
    c = _buscar([_item("PETR4F", "PETROLEO BRASILEIRO S.A. PETROBRAS")])[0]
    assert not c.cadastravel
    assert any("PETR4" in i and "fracionário" in i for i in c.impedimentos)


def test_etf_nao_vira_fii():
    """`fund` não é sinônimo de FII. Mapear ETF para a caixa mais parecida
    classificaria errado em silêncio."""
    c = _buscar([_item("BOVA11", "BOVA11", tipo="fund", subtipo="etf")])[0]
    assert c.tipo is None
    assert not c.cadastravel
    assert any("não suportado" in i for i in c.impedimentos)


@pytest.mark.parametrize("subtipo", ["etf", "fi-infra", "fi-agro", "fip", "fidc"])
def test_outros_fundos_tambem_sao_recusados(subtipo):
    c = _buscar([_item("XPTO11", "Fundo Qualquer", tipo="fund", subtipo=subtipo)])[0]
    assert not c.cadastravel


# --- ordenação e falhas -----------------------------------------------------

def test_cadastraveis_vem_primeiro_mas_o_resto_nao_some():
    """Quem tem impedimento continua visível com o motivo — sumir sem
    explicação faria o usuário procurar de novo pelo mesmo ticker."""
    candidatos = _buscar([
        _item("PETR4F", "PETROLEO BRASILEIRO S.A. PETROBRAS"),
        _item("PETR4", "PETROLEO BRASILEIRO S.A. PETROBRAS"),
    ])
    assert [c.ticker for c in candidatos] == ["PETR4", "PETR4F"]
    assert len(candidatos) == 2


def test_busca_vazia_nao_gasta_request():
    with patch.object(catalogo, "requests") as req:
        assert buscar("   ") == []
        assert not req.get.called


def test_falha_de_rede_nao_vira_lista_vazia():
    """Quem chama precisa distinguir 'nada encontrado' de 'não consegui
    procurar' — as duas exigem ações opostas do usuário."""
    with patch.object(catalogo, "requests") as req, \
         patch.object(catalogo, "get_settings") as cfg:
        cfg.return_value.brapi_token = "t"
        req.RequestException = requests.RequestException
        req.get.side_effect = requests.RequestException("timeout")
        with pytest.raises(CatalogoIndisponivel):
            buscar("PETR")


def test_formato_inesperado_falha_alto():
    with patch.object(catalogo, "requests") as req, \
         patch.object(catalogo, "get_settings") as cfg:
        cfg.return_value.brapi_token = "t"
        req.RequestException = requests.RequestException
        req.get.return_value = _resposta({"algo": "diferente"})
        with pytest.raises(CatalogoIndisponivel, match="formato"):
            buscar("PETR")


# --- CNPJ -------------------------------------------------------------------

def _perfil(cnpj):
    with patch.object(catalogo, "requests") as req, \
         patch.object(catalogo, "get_settings") as cfg:
        cfg.return_value.brapi_token = "t"
        req.RequestException = requests.RequestException
        req.get.return_value = _resposta(
            {"results": [{"summaryProfile": {"cnpj": cnpj} if cnpj else {}}]}
        )
        return cnpj_raiz_de("PETR4")


def test_cnpj_raiz_sao_os_oito_primeiros_digitos():
    """Digitado à mão, um dígito trocado quebra o vínculo com a CVM em
    silêncio — o calendário fica vazio e nada aponta a causa."""
    assert _perfil("33000167000101") == "33000167"


def test_cnpj_formatado_tambem_funciona():
    assert _perfil("33.000.167/0001-01") == "33000167"


def test_sem_cnpj_devolve_none_em_vez_de_inventar():
    assert _perfil(None) is None


def test_cnpj_curto_demais_nao_e_completado():
    assert _perfil("330") is None
