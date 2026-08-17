"""Entrega do relatório do agente: arquivo em `reports/`.

POR QUE A ENTREGA É DO SCRIPT, E NÃO DO AGENTE
-----------------------------------------------
O plano previa um MCP de notificação para o agente entregar o relatório
sozinho. Dar ao modelo uma ferramenta de ENVIO transfere a ele a decisão de
mandar, para quem e quantas vezes — e essa é a mesma fronteira que mantém
"nada aqui é ordem executada" verdadeira no resto do projeto. Vale igual
para uma mensagem e para uma ordem: quem decide enviar é código.

DOIS ARQUIVOS POR DIA, DE PROPÓSITO
-----------------------------------
`reports/AAAA-MM-DD.md` é o relatório DETERMINÍSTICO, que `report/daily.py`
escreve sem nenhum LLM envolvido. `reports/AAAA-MM-DD-agente.md` é o texto
composto pelo modelo. Ficam separados porque têm autoridades diferentes: o
primeiro é o que o sistema apurou, o segundo é uma leitura sobre aquilo.
Fundi-los faria a interpretação herdar a autoridade da apuração, e daqui a
seis meses ninguém saberia qual parágrafo foi calculado e qual foi escrito.

O cabeçalho do arquivo do agente diz isso em texto, para quem abrir o
arquivo solto — fora da interface, sem o contexto da tela.
"""
import datetime as dt
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from src.agente.relatorio import Relatorio

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


def _cabecalho(data: dt.date, r: "Relatorio") -> str:
    linhas = [
        f"# Relatório do agente — {data.isoformat()}",
        "",
        "> Texto composto por modelo de linguagem a partir do que os módulos",
        f"> determinísticos apuraram. Modelo: `{r.modelo}`.",
        ">",
        "> Os números vêm da avaliação de critérios e do enriquecimento",
        "> quantitativo, ambos no banco. O relatório apurado, sem LLM",
        f"> nenhum, está em `{data.isoformat()}.md`, ao lado deste.",
    ]
    if r.fontes:
        linhas += [
            ">",
            f"> Consultou {r.buscas} busca(s) na web. Fontes citadas:",
            *[f"> - {f}" for f in r.fontes],
        ]
    return "\n".join(linhas)


def escrever_arquivo(data: dt.date, r: "Relatorio") -> Path:
    """Escreve `reports/AAAA-MM-DD-agente.md` e devolve o caminho."""
    REPORTS_DIR.mkdir(exist_ok=True)
    caminho = REPORTS_DIR / f"{data.isoformat()}-agente.md"
    caminho.write_text(f"{_cabecalho(data, r)}\n\n{r.texto}\n", encoding="utf-8")
    log.info("Relatório do agente escrito: %s", caminho)
    return caminho
