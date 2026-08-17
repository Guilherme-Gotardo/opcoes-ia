"""Taxa livre de risco, com procedência — insumo do modelo de precificação.

POR QUE ISTO NÃO É UM PARÂMETRO EM YAML
---------------------------------------
O plano previa a taxa como parâmetro configurável, e a Fase 5 já listava
"taxa livre de risco desatualizada nos parâmetros do CRR" como risco de
deriva. Um número chumbado em arquivo é exatamente o tipo de dado que a
regra 1 do projeto proíbe: alguém escreve 10,75% num dia, a Selic vai a
14%, e meses depois todo `prob_exercicio` está errado sem nada avisar.

O BCB publica a série no SGS, aberta e sem chave. Então a taxa vira DADO
COLETADO, como cotação — com valor, data de observação e fonte viajando
juntos até o registro do enriquecimento.

QUAL SÉRIE, E POR QUÊ
---------------------
1178 — "Taxa de juros - Selic anualizada base 252". É a taxa efetivamente
praticada, anualizada, que é a forma que o modelo consome.

Não usamos a 432 ("Meta Selic definida pelo Copom"): ela carrega a data de
VIGÊNCIA da meta, que pode ser futura (uma consulta em 16/08/2026 devolve
16/09/2026), e um "observada_em" no futuro tornaria a auditoria da idade
sem sentido. A 11 (Selic diária, % ao dia) mediria a mesma coisa noutra
unidade e exigiria anualizar aqui — conta a mais, sem ganho.

QUANDO A REDE FALHA
-------------------
`buscar()` devolve `None`. Não inventa, não usa "a última que eu lembro" —
quem chama decide, e o caminho previsto é reusar a última taxa já gravada
em `enriquecimento_quant`, com a idade declarada numa ressalva. Uma taxa de
três dias atrás muda o preço teórico na quarta casa decimal; uma taxa
inventada muda a confiança em tudo.
"""
import datetime as dt
import logging
from dataclasses import dataclass

import requests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados/ultimos/1"
SERIE_SELIC_ANUALIZADA = 1178
FONTE = f"BCB/SGS série {SERIE_SELIC_ANUALIZADA} (Selic anualizada base 252)"


@dataclass(frozen=True)
class TaxaLivreRisco:
    #: Fração ao ano, já dividida por 100 — 13.90% vira 0.1390. O modelo
    #: consome fração; guardar em percentual aqui só adiaria a divisão para
    #: um ponto onde ela pode ser esquecida.
    valor_aa: float
    observada_em: dt.date
    fonte: str

    def idade_em_dias(self, hoje: dt.date | None = None) -> int:
        return ((hoje or dt.date.today()) - self.observada_em).days


def buscar(timeout: int = 15) -> TaxaLivreRisco | None:
    """Última Selic anualizada publicada, ou `None` se a fonte não responder."""
    try:
        resp = requests.get(
            SGS_URL.format(serie=SERIE_SELIC_ANUALIZADA),
            params={"formato": "json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        dados = resp.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("Taxa livre de risco indisponível no BCB: %s", e)
        return None

    if not dados:
        log.warning("BCB devolveu série vazia para %s.", SERIE_SELIC_ANUALIZADA)
        return None

    registro = dados[-1]
    try:
        # O SGS devolve dd/MM/yyyy e o valor como STRING ("13.90"). Converter
        # explícito em vez de confiar no json: um float que virasse string
        # noutro formato passaria despercebido até o modelo receber lixo.
        observada_em = dt.datetime.strptime(registro["data"], "%d/%m/%Y").date()
        percentual = float(registro["valor"])
    except (KeyError, ValueError, TypeError) as e:
        log.warning("Formato inesperado na resposta do BCB (%r): %s", registro, e)
        return None

    if not 0 < percentual < 100:
        # Selic fora desta faixa é erro de unidade (fração no lugar de
        # percentual, ou vice-versa), não um regime monetário exótico.
        log.warning("Selic fora da faixa plausível: %r%% a.a.", percentual)
        return None

    return TaxaLivreRisco(
        valor_aa=percentual / 100.0, observada_em=observada_em, fonte=FONTE
    )


def main() -> int:
    taxa = buscar()
    if taxa is None:
        print("Taxa livre de risco indisponível (ver log).")
        return 1
    print(
        f"Selic anualizada: {taxa.valor_aa * 100:.2f}% a.a. "
        f"(observada em {taxa.observada_em.isoformat()}, "
        f"há {taxa.idade_em_dias()} dia(s))\nFonte: {taxa.fonte}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
