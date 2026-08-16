"""Testes da superfície de escrita (src.api.escrita).

As funções de domínio são dubladas: o que se prova aqui é o CONTRATO HTTP
(status, corpo, tradução de erro), não a regra de negócio — essa já tem
teste próprio em `test_assets_manage.py` e `test_portfolio_manage.py`.
Revalidar a regra aqui criaria uma segunda verdade sobre o que é uma posição
válida, que é exatamente o que o módulo evita ao reusar as funções da CLI.
"""
import datetime as dt
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import escrita
from src.api.app import app
from src.assets.manage import AtivoInvalido
from src.portfolio.manage import PosicaoInvalida

AGORA = dt.datetime(2026, 8, 16, 12, 0, tzinfo=dt.timezone.utc)
cliente = TestClient(app)

ATIVO = {
    "ticker": "PETR4", "nome": "Petrobras PN", "tipo": "acao",
    "cnpj_raiz": "33000167", "criado_em": AGORA,
}


# --- /ativos ----------------------------------------------------------------

def test_cadastrar_ativo_devolve_o_registro_gravado():
    with patch.object(escrita, "add_ativo", return_value="PETR4") as add, \
         patch.object(escrita, "list_ativos", return_value=[ATIVO]):
        r = cliente.post("/ativos", json={
            "ticker": "petr4", "nome": "Petrobras PN", "tipo": "acao",
            "cnpj_raiz": "33000167",
        })

    assert r.status_code == 201
    assert r.json()["ticker"] == "PETR4"
    add.assert_called_once_with("petr4", "Petrobras PN", "acao", "33000167")


def test_cadastrar_ativo_sem_nome_devolve_a_mensagem_do_dominio():
    """O erro do domínio já é escrito para o usuário e diz o que corrigir —
    traduzir para algo genérico perderia a instrução."""
    erro = AtivoInvalido(
        "nome é obrigatório para PETR4 — o sistema não deriva nome do ticker."
    )
    with patch.object(escrita, "add_ativo", side_effect=erro):
        r = cliente.post("/ativos", json={"ticker": "PETR4", "nome": ""})

    assert r.status_code == 422
    assert "não deriva nome" in r.json()["detail"]


def test_listar_ativos():
    with patch.object(escrita, "list_ativos", return_value=[ATIVO]):
        r = cliente.get("/ativos")
    assert r.status_code == 200
    assert r.json()[0]["cnpj_raiz"] == "33000167"


# --- /posicoes --------------------------------------------------------------

def test_registrar_posicao_nao_representa_ordem():
    """A garantia que atravessa o projeto, virando campo do contrato."""
    with patch.object(escrita, "add_posicao", return_value=7):
        r = cliente.post("/posicoes", json={
            "ticker": "PETR4", "tipo_ativo": "ACAO",
            "quantidade": 100, "preco_medio": 32.5,
        })

    assert r.status_code == 201
    assert r.json() == {"id": 7, "executou_ordem": False}


def test_quantidade_negativa_registra_posicao_lancada():
    """Venda coberta entra como quantidade negativa — é o caso de uso
    central do projeto, não uma exceção."""
    with patch.object(escrita, "add_posicao", return_value=8) as add:
        r = cliente.post("/posicoes", json={
            "ticker": "PETRI450", "tipo_ativo": "OPCAO",
            "quantidade": -100, "preco_medio": 1.15,
        })

    assert r.status_code == 201
    add.assert_called_once_with("PETRI450", "OPCAO", -100, 1.15)


def test_posicao_em_ativo_nao_cadastrado_devolve_o_comando_que_resolve():
    erro = PosicaoInvalida(
        "ativo não cadastrado: XPTO3. Cadastre antes de registrar a posição:\n"
        '  python -m src.assets.manage add XPTO3 "<nome do ativo>" acao'
    )
    with patch.object(escrita, "add_posicao", side_effect=erro):
        r = cliente.post("/posicoes", json={
            "ticker": "XPTO3", "tipo_ativo": "ACAO",
            "quantidade": 10, "preco_medio": 5.0,
        })

    assert r.status_code == 422
    assert "assets.manage add" in r.json()["detail"]


def test_quantidade_zero_e_recusada_pelo_dominio():
    erro = PosicaoInvalida("quantidade não pode ser zero — isso não representa uma posição.")
    with patch.object(escrita, "add_posicao", side_effect=erro):
        r = cliente.post("/posicoes", json={
            "ticker": "PETR4", "tipo_ativo": "ACAO",
            "quantidade": 0, "preco_medio": 32.5,
        })
    assert r.status_code == 422


def test_listar_posicoes_abertas():
    with patch.object(escrita, "list_posicoes_abertas", return_value=[{
        "id": 1, "ticker": "PETR4", "tipo_ativo": "ACAO", "quantidade": 100,
        "preco_medio": 32.5, "aberta_em": AGORA, "origem": "manual",
    }]):
        r = cliente.get("/posicoes")
    assert r.status_code == 200
    assert r.json()[0]["quantidade"] == 100


def test_encerrar_posicao_preserva_a_linha():
    with patch.object(escrita, "close_posicao") as fechar:
        r = cliente.post("/posicoes/7/encerrar")
    assert r.status_code == 204
    fechar.assert_called_once_with(7)


def test_encerrar_posicao_inexistente_e_404():
    with patch.object(escrita, "close_posicao",
                      side_effect=PosicaoInvalida("Nenhuma posição aberta com id=99")):
        r = cliente.post("/posicoes/99/encerrar")
    assert r.status_code == 404


# --- Contrato ---------------------------------------------------------------

def test_escrita_nao_expoe_delete():
    """Encerrar posição é UPDATE em `fechada_em`: o histórico é o que
    permite explicar uma decisão passada meses depois."""
    caminhos = app.openapi()["paths"]
    for rota in ("/ativos", "/posicoes", "/posicoes/{posicao_id}/encerrar"):
        assert "delete" not in caminhos[rota], f"{rota} não pode expor DELETE"


def test_contrato_declara_que_registrar_nao_e_ordem():
    schema = app.openapi()["components"]["schemas"]["PosicaoCriada"]
    assert "executou_ordem" in schema["properties"]
    assert "corretora" in str(schema).lower() or "ordem" in str(schema).lower()
