"""Testes do agente de relatório: prompt, chamada e entrega. Sem rede.

O teste que carrega mais peso é `test_guarda_corpos_continuam_no_prompt`.
As três proibições do plano — não recalcular critério, não sugerir ordem,
não estimar preço-alvo — são a fronteira entre "modelo interpreta" e
"modelo decide". Guarda-corpo que ninguém testa some no primeiro refactor
do prompt, e some em silêncio: o relatório continua saindo, só que dizendo
coisas que não pode dizer.
"""
import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.agente import prompt as mod_prompt
from src.agente import relatorio as mod
from src.agente.dados import InsumoRelatorio
from src.agente.entrega import escrever_arquivo
from src.agente.relatorio import AgenteIndisponivel, Relatorio

DATA = dt.date(2026, 8, 17)


def _insumo(**troca) -> InsumoRelatorio:
    campos = dict(
        data=DATA.isoformat(),
        patrimonio={"total_a_mercado": 4209.0, "parcial": False},
        sugestoes=[{"ticker_objeto": "PETR4", "codigo_opcao": "PETRI420"}],
        desfecho=[{"ticker_objeto": "PETR4", "motivo": "criterio_reprovado",
                   "quantidade": 3}],
        enriquecimento=[],
        criterios_vigentes={"iv_rank_minimo": 50},
        lacunas=[],
    )
    campos.update(troca)
    return InsumoRelatorio(**campos)


class _Bloco(SimpleNamespace):
    pass


def _resposta(*, texto="Relatório.", fontes=(), buscas=0, erro_busca=None,
              stop="end_turn", entrada=100, saida=50, categoria=None):
    content = []
    for _ in range(buscas):
        content.append(_Bloco(
            type="web_search_tool_result",
            content=_Bloco(error_code=erro_busca) if erro_busca else [_Bloco(url="x")],
        ))
    content.append(_Bloco(
        type="text", text=texto,
        citations=[_Bloco(url=f) for f in fontes],
    ))
    return _Bloco(
        content=content, stop_reason=stop,
        stop_details=_Bloco(category=categoria) if categoria else None,
        usage=_Bloco(input_tokens=entrada, output_tokens=saida),
    )


# --- os guarda-corpos --------------------------------------------------------

def test_guarda_corpos_continuam_no_prompt():
    """As três proibições do plano, mais as duas que a busca web criou."""
    assert mod_prompt.guarda_corpos_presentes() == []


@pytest.mark.parametrize("trecho", mod_prompt.GUARDA_CORPOS)
def test_cada_guarda_corpo_e_cobrado_individualmente(trecho):
    assert trecho in mod_prompt.SISTEMA


def test_remover_um_guarda_corpo_e_detectado():
    """Prova que o teste acima tem dente: um prompt sem a proibição falha."""
    mutilado = mod_prompt.SISTEMA.replace("não sugere ordem", "sugere ordem")
    assert "não sugere ordem" in mod_prompt.guarda_corpos_presentes(mutilado)


def test_prompt_proibe_numero_vindo_de_busca():
    """O risco que a Fase 3 criou: com busca web, o agente PODE achar uma
    cotação, e passaria a existir um terceiro preço sem procedência no
    banco."""
    assert "não usa a busca web para número" in mod_prompt.SISTEMA
    assert "Preço, grega, volatilidade e probabilidade vêm do insumo" in mod_prompt.SISTEMA


def test_prompt_nao_grita():
    """Instrução em caixa alta foi escrita para modelos que ignoravam a
    falada; hoje produz hedge e recusa. O único caixa alta permitido é
    VEREDITO, no cabeçalho do insumo, que é ênfase sobre um termo."""
    assert "CRITICAL" not in mod_prompt.SISTEMA
    assert "VOCÊ DEVE" not in mod_prompt.SISTEMA
    assert "IMPORTANTE:" not in mod_prompt.SISTEMA


def test_mensagem_carrega_o_insumo_em_json():
    mensagens = mod_prompt.montar(_insumo())
    assert len(mensagens) == 1
    assert mensagens[0]["role"] == "user"
    conteudo = mensagens[0]["content"]
    assert "```json" in conteudo
    assert "PETRI420" in conteudo
    assert "criterios_vigentes" in conteudo


# --- leitura da resposta -----------------------------------------------------

def test_extrai_texto_fontes_e_buscas():
    texto, fontes, buscas, erros = mod._extrair(
        _resposta(texto="Olá.", fontes=["https://a", "https://b"], buscas=2)
    )
    assert texto == "Olá."
    assert fontes == ["https://a", "https://b"]
    assert buscas == 2
    assert erros == []


def test_fonte_repetida_conta_uma_vez():
    """A mesma fonte citada em três parágrafos é uma fonte."""
    _, fontes, _, _ = mod._extrair(
        _resposta(fontes=["https://a", "https://a", "https://b"])
    )
    assert fontes == ["https://a", "https://b"]


def test_erro_de_busca_nao_vira_busca_vazia():
    _, _, buscas, erros = mod._extrair(
        _resposta(buscas=1, erro_busca="max_uses_exceeded")
    )
    assert buscas == 1
    assert erros == ["max_uses_exceeded"]


# --- a chamada ---------------------------------------------------------------

def _cliente_falso(resposta_ou_lista):
    respostas = (
        list(resposta_ou_lista) if isinstance(resposta_ou_lista, list)
        else [resposta_ou_lista]
    )
    chamadas = []

    class _Messages:
        def create(self, **kwargs):
            chamadas.append(kwargs)
            return respostas[min(len(chamadas) - 1, len(respostas) - 1)]

    class _Cliente:
        beta = SimpleNamespace(messages=_Messages())

    return _Cliente, chamadas


def _com_sdk(resposta, chave="sk-ant-teste"):
    Cliente, chamadas = _cliente_falso(resposta)
    sdk = SimpleNamespace(
        Anthropic=Cliente,
        APIStatusError=type("APIStatusError", (Exception,), {}),
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
    )
    return patch.dict("sys.modules", {"anthropic": sdk}), \
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": chave}), chamadas


def test_compor_devolve_texto_com_procedencia():
    p1, p2, chamadas = _com_sdk(
        _resposta(texto="  Dia calmo.  ", fontes=["https://bcb"], buscas=1)
    )
    with p1, p2:
        r = mod.compor(_insumo())

    assert r.texto == "Dia calmo."
    assert r.modelo == mod.MODELO_PADRAO
    assert r.fontes == ["https://bcb"]
    assert r.buscas == 1
    assert r.tokens_entrada == 100
    assert r.insumo_resumo == {
        "sugestoes": 1, "desfecho": 1, "enriquecimento": 0, "lacunas": 0,
    }


def test_chamada_leva_sistema_ferramentas_e_thinking():
    p1, p2, chamadas = _com_sdk(_resposta())
    with p1, p2:
        mod.compor(_insumo())

    kwargs = chamadas[0]
    assert kwargs["system"] is mod_prompt.SISTEMA
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert any(t.get("name") == "web_search" for t in kwargs["tools"])


def test_chave_de_outro_provedor_falha_antes_de_gastar_a_viagem():
    """Chave DeepSeek/OpenAI em ANTHROPIC_API_KEY volta 401 falando de
    autenticação, o que esconde a causa real."""
    p1, p2, chamadas = _com_sdk(_resposta(), chave="sk-" + "x" * 32)
    with p1, p2, pytest.raises(AgenteIndisponivel) as e:
        mod.compor(_insumo())

    assert "não parece ser da Anthropic" in str(e.value)
    assert chamadas == [], "não pode ter chamado a API"


def test_sem_chave_nao_chama():
    p1, _, chamadas = _com_sdk(_resposta())
    with p1, patch.dict("os.environ", {}, clear=True), \
            pytest.raises(AgenteIndisponivel) as e:
        mod.compor(_insumo())
    assert "ANTHROPIC_API_KEY" in str(e.value)
    assert chamadas == []


def test_recusa_do_modelo_vira_erro_declarado():
    """`refusal` chega como HTTP 200 — ler `content` direto quebraria."""
    p1, p2, _ = _com_sdk(_resposta(stop="refusal", categoria="cyber"))
    with p1, p2, pytest.raises(AgenteIndisponivel) as e:
        mod.compor(_insumo())
    assert "recusou" in str(e.value)


def test_resposta_vazia_e_recusada():
    p1, p2, _ = _com_sdk(_resposta(texto="   "))
    with p1, p2, pytest.raises(AgenteIndisponivel) as e:
        mod.compor(_insumo())
    assert "vazia" in str(e.value)


def test_turno_pausado_e_retomado_e_os_tokens_somam():
    """Ferramenta de servidor pode pausar o turno. Retomar é reenviar a
    resposta parcial — sem acrescentar "continue", que confundiria o modelo."""
    p1, p2, chamadas = _com_sdk([
        _resposta(stop="pause_turn", texto="Parcial. ", entrada=100, saida=10),
        _resposta(stop="end_turn", texto="Fim.", entrada=120, saida=30),
    ])
    with p1, p2:
        r = mod.compor(_insumo())

    assert len(chamadas) == 2
    assert r.texto == "Fim."
    assert r.tokens_entrada == 220, "o custo das duas viagens soma"
    # A retomada reenvia o turno parcial como assistant, e nada mais.
    assert chamadas[1]["messages"][-1]["role"] == "assistant"


def test_pausa_infinita_para_no_teto():
    p1, p2, chamadas = _com_sdk(_resposta(stop="pause_turn"))
    with p1, p2:
        mod.compor(_insumo())
    assert len(chamadas) == mod.MAX_CONTINUACOES + 1


# --- o dia sem nada a dizer ---------------------------------------------------

def test_dia_sem_avaliacao_nao_gasta_chamada():
    """Sem sugestão e sem desfecho não houve avaliação. Gastar um LLM para
    dizer "nada aconteceu" é custo sem informação."""
    vazio = _insumo(sugestoes=[], desfecho=[])
    assert vazio.vazio is True

    with patch.object(mod.coleta, "coletar", return_value=vazio), \
            patch.object(mod, "compor") as compor:
        assert mod.executar(DATA) == 0
    compor.assert_not_called()


def test_falha_do_agente_nao_derruba_o_processo():
    """Falha aqui perde o TEXTO. Sugestões, desfecho e enriquecimento já
    estão gravados quando este módulo roda."""
    with patch.object(mod.coleta, "coletar", return_value=_insumo()), \
            patch.object(mod, "compor", side_effect=AgenteIndisponivel("sem chave")):
        assert mod.executar(DATA) == 1  # código de saída, não exceção


# --- entrega -----------------------------------------------------------------

def test_arquivo_do_agente_e_separado_do_deterministico(tmp_path):
    """Fundir os dois faria a interpretação herdar a autoridade da apuração,
    e daqui a seis meses ninguém saberia qual parágrafo foi calculado."""
    r = Relatorio(texto="Dia calmo.", modelo="claude-sonnet-5")
    with patch("src.agente.entrega.REPORTS_DIR", tmp_path):
        caminho = escrever_arquivo(DATA, r)

    assert caminho.name == "2026-08-17-agente.md"
    conteudo = caminho.read_text(encoding="utf-8")
    assert "Dia calmo." in conteudo
    assert "claude-sonnet-5" in conteudo
    # Aponta para o relatório apurado, que fica ao lado.
    assert "2026-08-17.md" in conteudo
    assert "modelo de linguagem" in conteudo


def test_cabecalho_lista_as_fontes_consultadas(tmp_path):
    r = Relatorio(texto="Texto.", modelo="m", fontes=["https://a", "https://b"], buscas=2)
    with patch("src.agente.entrega.REPORTS_DIR", tmp_path):
        conteudo = escrever_arquivo(DATA, r).read_text(encoding="utf-8")

    assert "2 busca(s)" in conteudo
    assert "https://a" in conteudo and "https://b" in conteudo


def test_sem_busca_o_cabecalho_nao_inventa_secao_de_fontes(tmp_path):
    r = Relatorio(texto="Texto.", modelo="m")
    with patch("src.agente.entrega.REPORTS_DIR", tmp_path):
        conteudo = escrever_arquivo(DATA, r).read_text(encoding="utf-8")
    assert "Fontes citadas" not in conteudo


def test_diretorio_de_reports_e_criado(tmp_path):
    destino = tmp_path / "reports"
    with patch("src.agente.entrega.REPORTS_DIR", destino):
        escrever_arquivo(DATA, Relatorio(texto="x", modelo="m"))
    assert (destino / "2026-08-17-agente.md").exists()


def test_caminho_do_reports_aponta_para_a_raiz_do_repositorio():
    """Um caminho errado escreveria o relatório num diretório que ninguém
    olha, sem erro nenhum."""
    from src.agente.entrega import REPORTS_DIR
    assert REPORTS_DIR.name == "reports"
    assert (REPORTS_DIR.parent / "src" / "agente").is_dir()
