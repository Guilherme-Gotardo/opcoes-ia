"""Consolidação das datas de resultado: coleta → resolução → persistência.

É a manivela que faltava. `EarningsEventService.ingerir()` existia e era
testado, mas nenhuma CLI, ETL ou workflow o chamava — então
`python -m src.earnings.manage add` gravava em `earnings_manual_entries` e
nada promovia aquilo para `earnings_events`. Resultado: `proximo_evento()`
devolvia `None`, o critério de resultado ficava `INDISPONIVEL` e nenhuma
sugestão de covered call podia ser emitida, com todos os critérios de
mercado aprovados.

REGISTRAR NÃO É CONSOLIDAR
--------------------------
`manage add` afirma o que você leu no site de RI. `ingest` faz essa
afirmação (e a das demais fontes pedidas) virar o evento que o motor de
opções consulta, passando pelo portão de precedência de
`resolution.aplicar` — estimativa nunca derruba confirmação.

Uso:
    python -m src.earnings.ingest
    python -m src.earnings.ingest --tickers PETR4,VALE3
    python -m src.earnings.ingest --fontes manual,cvm

Nenhuma regra de negócio mora aqui: coleta, agrupamento e resolução são de
`service.py`. Este módulo escolhe fontes, escolhe tickers, chama e reporta.
"""
import argparse
import logging
import sys

from src.db.connection import get_connection
from src.earnings.providers import (
    FONTES_PADRAO,
    FonteDesconhecida,
    construir_providers,
    nomes_aceitos,
)
from src.earnings.service import EarningsEventService

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

#: Código de saída quando TODA fonte pedida falhou. Diferente de "consolidei
#: zero eventos": as duas situações pedem ações opostas, e no workflow
#: diário a diferença entre passo verde e vermelho é a única coisa visível.
EXIT_TODAS_AS_FONTES_FALHARAM = 1


def tickers_da_carteira() -> list[str]:
    """Tickers com posição em ação em aberto.

    É o mesmo conjunto que `executar_avaliacao_carteira` percorre. Mantê-los
    alinhados por construção evita consolidar a agenda de um ativo que
    ninguém avalia — ou pior, não consolidar a de um que é avaliado.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ticker FROM posicoes "
            "WHERE tipo_ativo = 'ACAO' AND fechada_em IS NULL ORDER BY ticker"
        )
        return [linha[0] for linha in cur.fetchall()]


def _parse_lista(texto: str | None) -> list[str] | None:
    if texto is None:
        return None
    return [parte.strip() for parte in texto.split(",") if parte.strip()]


def executar(
    tickers: list[str] | None = None,
    fontes: list[str] | None = None,
    servico: EarningsEventService | None = None,
) -> int:
    """Consolida e devolve o código de saída.

    `servico` existe para os testes injetarem um dublê sem banco nem rede.
    """
    providers = construir_providers(fontes)
    pedidas = [p.name for p in providers]

    if tickers is None:
        tickers = tickers_da_carteira()
        origem_escopo = "posições em aberto"
    else:
        origem_escopo = "lista informada"

    if not tickers:
        # Encerra ANTES de consultar qualquer fonte: sem carteira e sem
        # lista explícita, varrer todos os ativos cadastrados gastaria
        # chamada de provider em ativo que ninguém avalia.
        print(
            "Nenhum ticker a consolidar: não há posição em ação aberta e "
            "nenhuma lista foi informada com --tickers."
        )
        return 0

    print(
        f"Consolidando {len(tickers)} ticker(s) ({origem_escopo}) "
        f"em {len(pedidas)} fonte(s): {', '.join(pedidas)}."
    )

    servico = servico or EarningsEventService(providers=providers)
    coletado = servico.coletar(tickers)

    responderam = [nome for nome in pedidas if nome in coletado]
    falharam = [nome for nome in pedidas if nome not in coletado]

    for nome in responderam:
        print(f"  {nome}: {len(coletado[nome])} afirmação(ões).")
    for nome in falharam:
        # O motivo detalhado já foi para o log por `service.coletar`, que
        # isola a falha. Aqui o ponto é o operador ver QUE falhou: silêncio
        # de fonte não pode ser lido como ausência de evento.
        print(f"  {nome}: FALHOU — não foi possível consultar (ver log acima).")

    if not responderam:
        print(
            "Nenhuma fonte pôde ser consultada — isto NÃO significa que não "
            "há resultado próximo. Nada foi consolidado."
        )
        return EXIT_TODAS_AS_FONTES_FALHARAM

    # Reaproveita a coleta já feita: consultar de novo custaria outro
    # download do dump da CVM. A orquestração continua sendo do serviço.
    eventos = servico.ingerir(tickers, coletado=coletado)

    print(f"Eventos consolidados: {len(eventos)}.")
    for evento in eventos:
        data = evento.effective_date
        print(
            f"  {evento.ticker} {evento.fiscal_period}: "
            f"{data.isoformat() if data else 'sem data'} "
            f"({evento.status.value}, confiança {evento.confidence})"
        )
    if falharam:
        print(
            f"Atenção: {len(falharam)} fonte(s) não responderam "
            f"({', '.join(falharam)}); a consolidação usou as demais."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Consolida datas de resultado das fontes configuradas para a "
            "tabela que o motor de opções consulta."
        ),
    )
    parser.add_argument(
        "--tickers", default=None,
        help=(
            "Lista separada por vírgula (ex.: PETR4,VALE3). Sem esta opção, "
            "usa os tickers com posição em ação aberta."
        ),
    )
    parser.add_argument(
        "--fontes", default=None,
        help=(
            "Lista separada por vírgula. Padrão: "
            f"{','.join(FONTES_PADRAO)}. Aceita: {', '.join(nomes_aceitos())}."
        ),
    )
    args = parser.parse_args(argv)

    try:
        return executar(
            tickers=_parse_lista(args.tickers),
            fontes=_parse_lista(args.fontes),
        )
    except FonteDesconhecida as exc:
        parser.exit(2, f"erro: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
