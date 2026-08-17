"""O agente de relatório: compõe o texto do dia e o entrega.

Rodar:
    python -m src.agente.relatorio            # dia de hoje (UTC)
    python -m src.agente.relatorio --data 2026-08-17
    python -m src.agente.relatorio --seco     # monta o prompt e para

ONDE ESTE MÓDULO SE ENCAIXA
---------------------------
    dados.py    junta o que os módulos determinísticos decidiram   [sem LLM]
    prompt.py   monta a instrução e os guarda-corpos               [sem LLM]
    ESTE        chama o modelo e persiste                          [com LLM]
    entrega.py  escreve em reports/                                [sem LLM]

O texto é a única coisa que vem do modelo. Todo número que ele cita tem que
estar no insumo, e o prompt cobra isso.

O QUE NUNCA ACONTECE AQUI
-------------------------
Falha deste módulo não invalida nada. As sugestões, o desfecho e o
enriquecimento já estão gravados quando ele roda; se a API não responder, se
a chave estiver errada ou se o modelo recusar, o que se perde é o TEXTO — e
o resto do sistema segue igual. Por isso o `main` devolve código de saída
mas o `rodar_pregao` não o encadeia.

ENVIO NÃO É FERRAMENTA DO AGENTE
--------------------------------
O modelo compõe; a entrega é do script, depois. Ver `docs/AGENTE.md` para
por que dar a ele uma ferramenta de envio seria transferir a decisão de
mandar.
"""
import argparse
import datetime as dt
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import src.config  # noqa: F401 — carrega o .env, convenção do projeto
from src.agente import dados as coleta
from src.agente.ferramentas import ConfiguracaoInvalida, do_arquivo
from src.agente.prompt import SISTEMA, montar
from src.agente.verificar import diagnosticar_chave
from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

#: Escolha registrada no plano para a rotina. Escalar para `claude-opus-5`
#: só nos casos em que o próprio agente sinalizar contradição entre fontes —
#: mantém o custo baixo na maioria das execuções.
MODELO_PADRAO = "claude-sonnet-5"

#: Um relatório de carteira pessoal é curto. 8000 dá folga para o raciocínio
#: adaptativo e o texto sem chegar perto do timeout HTTP do SDK.
MAX_TOKENS = 8000

#: Turno com ferramenta de servidor pode pausar (`pause_turn`) e precisar de
#: continuação. O teto existe para um laço de busca infinita não virar conta
#: infinita.
MAX_CONTINUACOES = 3


class AgenteIndisponivel(RuntimeError):
    """Não deu para compor o relatório. Nunca invalida a avaliação."""


@dataclass(frozen=True)
class Relatorio:
    texto: str
    modelo: str
    fontes: list[str] = field(default_factory=list)
    buscas: int = 0
    tokens_entrada: int | None = None
    tokens_saida: int | None = None
    insumo_resumo: dict[str, Any] = field(default_factory=dict)


def _extrair(resposta) -> tuple[str, list[str], int, list[str]]:
    """Texto, fontes citadas, número de buscas e erros de busca."""
    partes: list[str] = []
    fontes: list[str] = []
    buscas = 0
    erros: list[str] = []

    for bloco in resposta.content:
        if bloco.type == "text":
            partes.append(bloco.text)
            for c in (getattr(bloco, "citations", None) or []):
                if (url := getattr(c, "url", None)):
                    fontes.append(url)
        elif bloco.type == "web_search_tool_result":
            buscas += 1
            # Sucesso vem como LISTA; erro vem como OBJETO. Sem distinguir,
            # uma busca que quebrou pareceria uma que não achou nada.
            if not isinstance(bloco.content, list):
                erros.append(getattr(bloco.content, "error_code", "erro desconhecido"))

    # `dict.fromkeys` preserva a ordem e remove repetição: a mesma fonte
    # citada em três parágrafos é uma fonte.
    return "".join(partes), list(dict.fromkeys(fontes)), buscas, erros


def compor(insumo: coleta.InsumoRelatorio, modelo: str = MODELO_PADRAO) -> Relatorio:
    """Chama o modelo e devolve o relatório. Levanta `AgenteIndisponivel`."""
    if (problema := diagnosticar_chave(os.getenv("ANTHROPIC_API_KEY"))):
        raise AgenteIndisponivel(problema)
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise AgenteIndisponivel(
            "ANTHROPIC_API_KEY não está no ambiente — ver docs/AGENTE.md."
        )
    try:
        import anthropic
    except ImportError as e:
        raise AgenteIndisponivel(
            "SDK ausente: pip install -r requirements-optional.txt"
        ) from e

    try:
        ferramentas = do_arquivo()
    except ConfiguracaoInvalida as e:
        raise AgenteIndisponivel(f"configuração de ferramentas inválida: {e}") from e

    cliente = anthropic.Anthropic()
    mensagens = montar(insumo)
    entrada = saida = 0
    resposta = None

    for tentativa in range(MAX_CONTINUACOES + 1):
        try:
            resposta = cliente.beta.messages.create(
                model=modelo,
                max_tokens=MAX_TOKENS,
                system=SISTEMA,
                thinking={"type": "adaptive"},
                messages=mensagens,
                **ferramentas.como_kwargs(),
            )
        except anthropic.APIStatusError as e:
            raise AgenteIndisponivel(f"a API recusou ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise AgenteIndisponivel(f"não foi possível alcançar a API: {e}") from e

        entrada += resposta.usage.input_tokens
        saida += resposta.usage.output_tokens

        # `refusal` chega como HTTP 200 — ler `content` direto quebraria.
        if resposta.stop_reason == "refusal":
            raise AgenteIndisponivel(
                "o modelo recusou a composição do relatório "
                f"({getattr(resposta.stop_details, 'category', 'sem categoria')})"
            )
        if resposta.stop_reason != "pause_turn":
            break

        # Ferramenta de servidor atingiu o limite de iterações do turno.
        # Reenviar a resposta parcial faz o servidor retomar de onde parou —
        # NÃO se acrescenta "continue", que confundiria o modelo.
        log.info("Turno pausado (%d/%d), retomando.", tentativa + 1, MAX_CONTINUACOES)
        mensagens = [*mensagens, {"role": "assistant", "content": resposta.content}]
    else:
        log.warning(
            "Turno seguiu pausado após %d continuações; usando o que houver.",
            MAX_CONTINUACOES,
        )

    texto, fontes, buscas, erros = _extrair(resposta)
    if erros:
        log.warning("Buscas com erro: %s", ", ".join(erros))
    if not texto.strip():
        raise AgenteIndisponivel("o modelo devolveu resposta vazia")

    return Relatorio(
        texto=texto.strip(), modelo=modelo, fontes=fontes, buscas=buscas,
        tokens_entrada=entrada, tokens_saida=saida,
        insumo_resumo={
            "sugestoes": len(insumo.sugestoes),
            "desfecho": len(insumo.desfecho),
            "enriquecimento": len(insumo.enriquecimento),
            "lacunas": len(insumo.lacunas),
        },
    )


def gravar(data: dt.date, r: Relatorio) -> int | None:
    """Persiste o relatório. Devolve o id, ou `None` se a migração 009 não
    foi aplicada — caso em que o arquivo em reports/ segue sendo escrito."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.relatorios_agente')")
        if cur.fetchone()[0] is None:
            log.warning(
                "Tabela `relatorios_agente` não existe (migração 009 não "
                "aplicada): o relatório não vai aparecer na interface."
            )
            return None
        cur.execute(
            """
            INSERT INTO relatorios_agente (
                data, texto, modelo, fontes, buscas,
                tokens_entrada, tokens_saida, insumo_resumo
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """,
            (
                data, r.texto, r.modelo,
                json.dumps(r.fontes, ensure_ascii=False), r.buscas,
                r.tokens_entrada, r.tokens_saida,
                json.dumps(r.insumo_resumo, ensure_ascii=False),
            ),
        )
        id_ = cur.fetchone()[0]
        conn.commit()
    return id_


def executar(data: dt.date | None = None, modelo: str = MODELO_PADRAO,
             seco: bool = False) -> int:
    from src.agente.entrega import escrever_arquivo  # noqa: PLC0415

    data = data or dt.datetime.now(dt.timezone.utc).date()
    insumo = coleta.coletar(data)

    if insumo.vazio:
        # Sem avaliação nenhuma não há o que interpretar, e uma chamada de
        # LLM para dizer "nada aconteceu" é gasto sem informação.
        log.info("Nada avaliado em %s — sem relatório a compor.", data.isoformat())
        return 0

    if seco:
        print(SISTEMA)
        print("\n" + "=" * 70 + "\n")
        print(montar(insumo)[0]["content"])
        return 0

    try:
        relatorio = compor(insumo, modelo)
    except AgenteIndisponivel as e:
        log.error("Relatório do agente não foi composto: %s", e)
        return 1

    id_ = gravar(data, relatorio)
    caminho = escrever_arquivo(data, relatorio)
    log.info(
        "Relatório composto: %s (id=%s, %d fonte(s), %d busca(s), "
        "%s tokens de entrada e %s de saída)",
        caminho, id_, len(relatorio.fontes), relatorio.buscas,
        relatorio.tokens_entrada, relatorio.tokens_saida,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compõe o relatório do dia.")
    p.add_argument("--data", type=dt.date.fromisoformat, default=None)
    p.add_argument("--modelo", default=MODELO_PADRAO)
    p.add_argument(
        "--seco", action="store_true",
        help="mostra o prompt que seria enviado e sai, sem chamar a API",
    )
    args = p.parse_args(argv)
    return executar(args.data, args.modelo, args.seco)


if __name__ == "__main__":
    sys.exit(main())
