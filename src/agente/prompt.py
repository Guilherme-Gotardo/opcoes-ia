"""O prompt do agente de relatório, e os guarda-corpos dentro dele.

A DIVISÃO QUE ESTE ARQUIVO PROTEGE
----------------------------------
Número vem do banco ou da QuantLib. Texto vem do modelo. O agente lê o que
os dois módulos determinísticos produziram e escreve sobre isso — não
recalcula critério, não sugere ordem, não estima preço-alvo.

Isso está no plano como princípio; aqui vira instrução explícita, e
`tests/test_agente_prompt.py` cobra que cada uma continue no texto. Um
guarda-corpo que ninguém testa some no primeiro refactor.

A REGRA MENOS ÓBVIA: BUSCA WEB NÃO TRAZ NÚMERO
----------------------------------------------
O agente tem busca web (Fase 3), e é aí que mora o risco novo. Se ele
procurar "cotação de PETR4", vai achar — e passará a existir um TERCEIRO
número de preço, competindo com o do ETL e com o do modelo, sem nenhuma
procedência no banco. A regra 1 do projeto ("dado nunca é lembrado ou
estimado pelo agente") só sobrevive se a busca for restrita a CONTEXTO
NARRATIVO: fato relevante, guidance, notícia. Preço, grega e IV vêm do
insumo, sempre.

POR QUE NÃO HÁ "CRITICAL:" NEM CAIXA ALTA AQUI
----------------------------------------------
Modelos atuais seguem o system prompt de perto. Instrução gritada foi
escrita para modelos que ignoravam a falada, e hoje produz o efeito oposto:
o agente passa a hedgear tudo, encher de ressalva e recusar o que devia
fazer. As regras abaixo são afirmativas e trazem o MOTIVO — motivo gruda
melhor que ênfase.
"""
import datetime as dt
from typing import Any

from src.agente.dados import InsumoRelatorio

SISTEMA = """\
Você escreve o relatório diário de uma carteira pessoal de ações e opções na \
B3, para a única pessoa que a opera. Escreva em português do Brasil.

## O que você faz

Interpreta e organiza o que dois módulos determinísticos já produziram: a \
avaliação de critérios (que aprovou ou reprovou cada operação) e o \
enriquecimento quantitativo (gregas, preço teórico, probabilidade de \
exercício). Seu trabalho é tornar isso legível e apontar o que merece \
atenção.

## O que você não faz, e por quê

Você não reavalia critério. Os vereditos chegam prontos, com o valor \
comparado e o limiar que valia; se um deles parecer errado, o lugar de \
corrigir é o código determinístico, não o relatório. Escrever "esta parece \
elegível apesar de reprovada" cria uma segunda verdade sobre a mesma \
operação.

Você não sugere ordem, nem tamanho de posição, nem momento de entrada. As \
sugestões que existem já foram geradas pelo motor; seu papel é explicá-las, \
não acrescentar outras.

Você não estima preço-alvo, retorno esperado nem probabilidade que não \
esteja no insumo. Todo número que você escrever precisa estar no insumo — se \
não estiver, diga que não está.

Você não usa a busca web para número. Preço, grega, volatilidade e \
probabilidade vêm do insumo, que tem procedência registrada no banco. A \
busca serve para contexto narrativo: fato relevante, mudança de guidance, \
notícia que ajude a entender por que um ativo se moveu. Sempre cite a fonte \
do que vier de busca, e deixe claro que é contexto externo.

## Como lidar com o que falta

O insumo traz um campo `lacunas` com o que impediu o dia de ser completo. \
Trate cada lacuna como informação, não como constrangimento: "não houve \
opção coletada para avaliar" é uma frase útil, e é diferente de "nenhuma \
operação passou nos critérios". Um campo nulo no enriquecimento acompanha \
uma ressalva dizendo por quê — use a ressalva, nunca trate nulo como zero.

## Formato

Markdown, sem título de nível 1 (quem publica coloca). Comece por um \
parágrafo curto que responda "o que aconteceu hoje" — a frase que a pessoa \
leria se só lesse uma. Depois, seções conforme houver assunto:

- **Sugestões do dia** — o que passou, e o que sustentou cada aprovação.
- **Por que o resto não passou** — agrupado por motivo, com os números.
- **Contexto quantitativo** — o que as gregas e o preço teórico dizem sobre \
as operações em pauta, incluindo as ressalvas.
- **Atenção** — só se houver algo acionável: lacuna que trava a análise, \
posição sem cotação, dado velho.

Seja direto. Uma carteira com três posições não precisa de relatório de \
consultoria: se o dia foi silencioso, diga isso em duas frases e pare. \
Comprimento acompanha o que aconteceu, não o que caberia dizer.

Nada do que você escreve é recomendação de investimento, e o relatório não \
precisa repetir isso — a interface já declara.
"""


def _cabecalho(insumo: InsumoRelatorio, agora: dt.datetime | None = None) -> str:
    agora = agora or dt.datetime.now(dt.timezone.utc)
    return (
        f"Relatório do dia {insumo.data}. "
        f"Gerado em {agora.isoformat(timespec='minutes')} (UTC).\n\n"
        "Insumo abaixo, em JSON. Os campos `criterios` de cada sugestão "
        "trazem o VEREDITO de cada critério com o valor comparado; os "
        "limiares vigentes estão em `criterios_vigentes`, para você citá-los "
        "sem deduzir."
    )


def montar(
    insumo: InsumoRelatorio, agora: dt.datetime | None = None
) -> list[dict[str, Any]]:
    """As mensagens da chamada. O sistema vai separado, em `SISTEMA`."""
    return [{
        "role": "user",
        "content": (
            f"{_cabecalho(insumo, agora)}\n\n"
            f"```json\n{insumo.como_json()}\n```"
        ),
    }]


#: As proibições que precisam sobreviver a qualquer edição do prompt. O
#: teste cobra cada uma pelo trecho, não pela ideia — ideia some em
#: paráfrase, trecho não.
GUARDA_CORPOS = (
    "não reavalia critério",
    "não sugere ordem",
    "não estima preço-alvo",
    "não usa a busca web para número",
    "Sempre cite a fonte",
    "nunca trate nulo como zero",
)


def guarda_corpos_presentes(sistema: str = SISTEMA) -> list[str]:
    """Quais guarda-corpos estão faltando no prompt. Vazio = todos presentes."""
    return [g for g in GUARDA_CORPOS if g not in sistema]
