"""Desfecho de uma execução da avaliação: classificação e agregação.

A avaliação sempre soube por que não sugeriu — e jogava fora. Só as
elegíveis iam para `sugestoes`; o resto vivia em memória dentro de
`executar_avaliacao_carteira()` e morria com o processo. O relatório só
enxergava porque recebia por argumento, no mesmo processo.

Este módulo traduz a lista de `ResultadoAvaliacao` em linhas gravaveis, sem
tocar em nenhuma regra de decisão: tudo aqui é leitura do que `avaliar()`
já concluiu.

DUAS ESCOLHAS QUE ATRAVESSAM O MÓDULO
-------------------------------------
1. **Motivo é código, não a frase.** `motivo_nao_elegivel` é texto montado
   para leitura humana ("critério(s) não atendido(s): iv_rank, delta").
   Agrupar por ele seria agrupar por redação, e quebraria no primeiro
   ajuste de texto.

2. **Agregado por (ativo, motivo), não por opção.** O bloqueio por data de
   resultado é por ATIVO: falta a data da PETR4, todas as opções dela caem
   no mesmo motivo. Com cadeia real de 100+ séries, uma linha por opção
   gravaria ~100 registros idênticos exceto pelo código, para expressar um
   fato só.
"""
from collections import Counter
from dataclasses import dataclass, field

from src.strategy.covered import EstadoCriterio, ResultadoAvaliacao


class Motivo:
    """Conjunto fechado de desfechos possíveis de uma avaliação."""

    SUGERIDA = "sugerida"
    BLOQUEIO_DATA_RESULTADO = "bloqueio_data_resultado"
    CRITERIO_REPROVADO = "criterio_reprovado"
    DADO_INSUFICIENTE = "dado_insuficiente"
    PRE_REQUISITO = "pre_requisito"
    #: Ativo em carteira sem nenhuma opção coletada. Distingue "nada a
    #: avaliar" de "avaliado e nada passou" — as duas coisas pedem ações
    #: diferentes (destravar a coleta vs. esperar o mercado).
    SEM_OPCOES = "sem_opcoes"


def classificar(resultado: ResultadoAvaliacao) -> str:
    """Motivo de um resultado. Cai em exatamente um código.

    A ordem reproduz a precedência de `avaliar()`: reprovação no mérito vence
    bloqueio por dado faltante, porque um delta fora da faixa continua fora da
    faixa independentemente de haver ou não data de resultado.
    """
    if resultado.elegivel:
        return Motivo.SUGERIDA

    reprovou = any(
        c.estado == EstadoCriterio.REPROVADO for c in resultado.criterios
    )
    if reprovou:
        return Motivo.CRITERIO_REPROVADO

    if resultado.bloqueado_por_resultado:
        return Motivo.BLOQUEIO_DATA_RESULTADO

    motivo = resultado.motivo_nao_elegivel or ""
    if motivo.startswith("dado insuficiente"):
        return Motivo.DADO_INSUFICIENTE

    # Sobra o pré-requisito estrutural (lote ou caixa). Sem critérios
    # avaliados e sem "dado insuficiente", é o único caminho que `avaliar()`
    # tem para recusar antes dos critérios de mercado.
    return Motivo.PRE_REQUISITO


def criterios_reprovados(resultado: ResultadoAvaliacao) -> list[str]:
    return [
        c.nome for c in resultado.criterios
        if c.estado == EstadoCriterio.REPROVADO
    ]


@dataclass
class LinhaDesfecho:
    """Uma linha do desfecho: (ativo, motivo) numa execução."""

    ticker_objeto: str
    motivo: str
    quantidade: int
    #: {"iv_rank": 8, "delta": 5}. A soma PODE EXCEDER `quantidade`: uma
    #: opção reprovada em dois critérios conta nos dois. A pergunta que isto
    #: responde é "quantas foram barradas por este critério", não "como as
    #: opções se dividem" — particionar exigiria eleger um critério
    #: principal, e `avaliar()` trata todos como igualmente obrigatórios.
    criterios_contagem: dict[str, int] = field(default_factory=dict)
    #: Opção representativa, para o registro ser legível sem consultar a
    #: cadeia inteira. AMOSTRA PARA LEITURA, não referência para operar.
    amostra: dict | None = None


def _amostra(resultado: ResultadoAvaliacao) -> dict:
    return {
        "codigo_opcao": resultado.codigo_opcao,
        "strike": resultado.strike,
        "vencimento": resultado.vencimento,
        "premio_estimado": resultado.premio_estimado,
        "motivo_nao_elegivel": resultado.motivo_nao_elegivel,
        "criterios": [
            {"nome": c.nome, "detalhe": c.detalhe, "estado": c.estado.value}
            for c in resultado.criterios
        ],
        "base_valorizacao": {
            "preco_mercado": resultado.preco_mercado,
            "cotacao_em": resultado.cotacao_em,
        },
    }


def agregar(
    resultados: list[ResultadoAvaliacao],
    tickers_sem_opcoes: list[str] | None = None,
) -> list[LinhaDesfecho]:
    """Agrega os resultados de uma execução em linhas por (ativo, motivo).

    `tickers_sem_opcoes` registra os ativos que nem chegaram a ser avaliados
    por não haver opção coletada — caso contrário eles sumiriam do desfecho e
    "nada a avaliar" viraria indistinguível de "ativo fora da carteira".

    A amostra escolhida é a do PRIMEIRO resultado de cada grupo, e a ordem de
    entrada é a da avaliação (posição por posição, opção por opção) — o que
    torna a escolha determinística para a mesma entrada.
    """
    grupos: dict[tuple[str, str], LinhaDesfecho] = {}

    for resultado in resultados:
        chave = (resultado.ticker_objeto, classificar(resultado))
        linha = grupos.get(chave)
        if linha is None:
            linha = LinhaDesfecho(
                ticker_objeto=chave[0], motivo=chave[1], quantidade=0,
                amostra=_amostra(resultado),
            )
            grupos[chave] = linha
        linha.quantidade += 1
        for nome in criterios_reprovados(resultado):
            linha.criterios_contagem[nome] = linha.criterios_contagem.get(nome, 0) + 1

    # Um ativo que produziu QUALQUER resultado foi avaliado — não pode
    # ganhar também uma linha de "nada a avaliar", ainda que o chamador o
    # informe por engano.
    avaliados = {chave[0] for chave in grupos}
    for ticker in tickers_sem_opcoes or []:
        if ticker not in avaliados:
            grupos[(ticker, Motivo.SEM_OPCOES)] = LinhaDesfecho(
                ticker_objeto=ticker, motivo=Motivo.SEM_OPCOES, quantidade=0,
            )

    return [grupos[c] for c in sorted(grupos)]


def resumo_por_motivo(linhas: list[LinhaDesfecho]) -> Counter:
    """Quantas opções em cada motivo, somando os ativos. Para log e relatório."""
    contagem: Counter = Counter()
    for linha in linhas:
        contagem[linha.motivo] += linha.quantidade
    return contagem
