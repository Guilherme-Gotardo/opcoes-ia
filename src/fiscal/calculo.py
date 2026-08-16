"""Resultado de uma operação, líquido de custos e tributo ESTIMADO.

O QUE ESTE MÓDULO NÃO É
-----------------------
Não é apuração fiscal. Ele responde "o que sobra desta operação depois dos
custos", uma pergunta por operação. A apuração de verdade é MENSAL,
consolida ganhos e perdas de todas as operações da mesma categoria no mês,
carrega prejuízo acumulado de meses anteriores e desconta o IRRF retido —
nada disso acontece aqui, e por isso toda saída carrega `estimativa=True`.

Chamar isto de "imposto devido" seria errado de um jeito caro. É o valor de
referência para saber se a operação vale a pena, não o que se recolhe.

DUAS CATEGORIAS QUE NÃO SE SOMAM
--------------------------------
Uma call exercida tem duas pernas com tratamento fiscal DIFERENTE: o prêmio
da opção e a venda da ação ao strike. A isenção mensal de vendas vale para
ação à vista e não vale para opção, então somar as duas antes de tributar
produziria um número que não corresponde a nenhuma regra. Elas são
calculadas separadas e só o total líquido é somado no fim.

MÓDULO PURO
-----------
Sem I/O e sem banco, como `strategy/covered.py` — os parâmetros entram como
dicionário e o chamador decide de onde vêm.
"""
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TRIBUTOS_PATH = Path(__file__).resolve().parent / "tributos.yaml"

#: Desfechos possíveis de uma posição fechada. Espelha o CHECK da migração
#: 005: conjunto fechado, porque texto livre impede somar.
MOTIVOS_FECHAMENTO = ("expirada", "recomprada", "exercida", "encerrada")


class ParametroFiscalInvalido(ValueError):
    """Parâmetro de tributo malformado — falha alto, nunca cai em padrão."""


def carregar_tributos(path: Path | None = None) -> dict:
    path = path or TRIBUTOS_PATH
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _numero(params: dict, chave: str, padrao: float) -> float:
    """Lê um parâmetro numérico não-negativo.

    Valor inválido levanta em vez de cair no padrão: uma alíquota lida
    errado muda silenciosamente o número que o usuário vai usar para
    decidir se a operação valeu.
    """
    if chave not in params:
        return float(padrao)
    valor = params[chave]
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ParametroFiscalInvalido(
            f"{chave} precisa ser um número em tributos.yaml (recebido: {valor!r})."
        )
    if valor < 0:
        raise ParametroFiscalInvalido(
            f"{chave} não pode ser negativo (recebido: {valor!r})."
        )
    return float(valor)


@dataclass
class Perna:
    """Uma perna da operação, com sua própria categoria fiscal."""

    nome: str
    resultado_bruto: float
    custos: float
    aliquota_pct: float
    imposto: float

    @property
    def resultado_liquido(self) -> float:
        return self.resultado_bruto - self.custos - self.imposto


@dataclass
class ResultadoOperacao:
    """Sempre estimativa. O campo existe para a interface não poder omitir."""

    estimativa: bool = True
    pernas: list[Perna] = field(default_factory=list)
    #: Preenchido quando o cálculo depende de algo que não foi informado.
    ressalvas: list[str] = field(default_factory=list)

    @property
    def resultado_bruto(self) -> float:
        return sum(p.resultado_bruto for p in self.pernas)

    @property
    def custos(self) -> float:
        return sum(p.custos for p in self.pernas)

    @property
    def imposto(self) -> float:
        return sum(p.imposto for p in self.pernas)

    @property
    def resultado_liquido(self) -> float:
        return sum(p.resultado_liquido for p in self.pernas)


def _custos_de(volume: float, params: dict) -> float:
    """Corretagem fixa mais emolumentos sobre o volume movimentado."""
    corretagem = _numero(params, "corretagem_por_operacao", 0.0)
    emolumentos_pct = _numero(params, "emolumentos_pct", 0.0)
    return corretagem + abs(volume) * emolumentos_pct / 100


def _imposto(resultado: float, aliquota_pct: float) -> float:
    """Imposto sobre ganho. Prejuízo não gera crédito AQUI — compensação é
    coisa da apuração mensal, que este módulo declaradamente não faz."""
    return max(0.0, resultado) * aliquota_pct / 100


def resultado_da_opcao(
    quantidade: int,
    premio_unitario: float,
    preco_fechamento: float | None,
    params: dict,
    day_trade: bool = False,
) -> Perna:
    """Perna da opção.

    UNIDADE — `quantidade` está em OPÇÕES, cada uma sobre 1 ação, que é a
    mesma unidade de `premio_unitario` (preço por ação). Uma venda coberta
    de um lote de 100 ações é `quantidade = -100`, e não `-1`. Confundir as
    duas leituras erra o dinheiro por 100×, então nada aqui multiplica por
    `ACOES_POR_CONTRATO` — essa constante existe para converter CONTRATO em
    ações, e aqui não se lida com contratos.

    `quantidade` negativa é posição LANÇADA: o prêmio entra como receita na
    abertura e o custo de saída é o que se paga para recomprar.

    `preco_fechamento is None` significa que NÃO houve negócio de saída
    (a opção virou pó ou foi exercida) — e então não há custo de corretagem
    de saída para cobrar.
    """
    opcoes = abs(quantidade)
    premio_recebido = opcoes * premio_unitario
    saida = opcoes * (preco_fechamento or 0.0)

    # Vendida: recebe o prêmio e paga para sair. Comprada: o inverso.
    bruto = premio_recebido - saida if quantidade < 0 else saida - premio_recebido

    custos = _custos_de(premio_recebido, params) + (
        _custos_de(saida, params) if preco_fechamento is not None else 0.0
    )
    aliquota = _numero(
        params,
        "aliquota_day_trade_pct" if day_trade else "aliquota_opcoes_pct",
        20.0 if day_trade else 15.0,
    )
    return Perna(
        nome="opção (day trade)" if day_trade else "opção",
        resultado_bruto=bruto,
        custos=custos,
        aliquota_pct=aliquota,
        imposto=_imposto(bruto - custos, aliquota),
    )


def resultado_da_acao_entregue(
    quantidade_acoes: int,
    strike: float,
    preco_medio_acao: float,
    params: dict,
) -> Perna:
    """Perna da ação, quando a call é exercida e as ações são entregues ao
    strike. Categoria fiscal própria — ver o cabeçalho do módulo.

    `quantidade_acoes` é o número de AÇÕES entregues, que numa call coberta
    é igual ao número de opções lançadas (cada opção é sobre 1 ação). Não
    se multiplica por `ACOES_POR_CONTRATO` aqui: a quantidade já está na
    unidade certa, e multiplicar de novo erraria por 100×.
    """
    quantidade = abs(quantidade_acoes)
    bruto = (strike - preco_medio_acao) * quantidade
    custos = _custos_de(strike * quantidade, params)
    aliquota = _numero(params, "aliquota_acoes_pct", 15.0)
    return Perna(
        nome="ação entregue ao strike",
        resultado_bruto=bruto,
        custos=custos,
        aliquota_pct=aliquota,
        imposto=_imposto(bruto - custos, aliquota),
    )


def avaliar_operacao(
    *,
    quantidade: int,
    premio_unitario: float,
    motivo_fechamento: str | None,
    preco_fechamento: float | None,
    strike: float | None,
    preco_medio_acao: float | None,
    params: dict,
    day_trade: bool = False,
) -> ResultadoOperacao:
    """Resultado de uma operação de opção, conforme como ela foi fechada.

    Operação ABERTA (`motivo_fechamento is None`) não tem resultado
    realizado, e este módulo não inventa um: quem quiser projetar cenários
    chama as funções de perna com os valores hipotéticos.
    """
    resultado = ResultadoOperacao()

    if motivo_fechamento is None:
        resultado.ressalvas.append(
            "operação em aberto: não há resultado realizado a apurar"
        )
        return resultado

    if motivo_fechamento not in MOTIVOS_FECHAMENTO:
        raise ParametroFiscalInvalido(
            f"motivo_fechamento inválido: {motivo_fechamento!r}. "
            f"Use um de: {', '.join(MOTIVOS_FECHAMENTO)}."
        )

    # Expirada ou exercida: não houve negócio de saída. `None` (e não 0,0)
    # é o que diz isso — com 0,0 o cálculo cobraria corretagem de uma
    # operação de saída que nunca existiu.
    saida = None if motivo_fechamento in ("expirada", "exercida") else preco_fechamento
    if motivo_fechamento == "recomprada" and preco_fechamento is None:
        resultado.ressalvas.append(
            "recompra sem preço informado: o custo de saída foi tratado como "
            "zero, então o resultado está SUPERESTIMADO"
        )
        saida = 0.0

    resultado.pernas.append(
        resultado_da_opcao(quantidade, premio_unitario, saida, params, day_trade)
    )

    if motivo_fechamento == "exercida":
        if strike is None or preco_medio_acao is None:
            resultado.ressalvas.append(
                "exercício sem strike ou sem preço médio da ação: a perna da "
                "ação ficou de fora, e o resultado cobre só o prêmio"
            )
        else:
            resultado.pernas.append(
                resultado_da_acao_entregue(
                    quantidade, strike, preco_medio_acao, params
                )
            )

    return resultado


def dias_ate(vencimento: dt.date | None, hoje: dt.date | None = None) -> int | None:
    if vencimento is None:
        return None
    return (vencimento - (hoje or dt.date.today())).days
