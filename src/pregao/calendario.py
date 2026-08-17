"""Calendário de pregão da B3 — responde "posso rodar agora?".

POR QUE ISTO EXISTE
-------------------
A avaliação passa a rodar sozinha, em disparos ao longo do dia. Sem saber
se há pregão, ela rodaria em feriado e fim de semana contra a última
cotação disponível — que estaria dentro da janela de frescor de 72h e,
portanto, **passaria** no teste. O resultado não seria "dado insuficiente",
seria uma sugestão calculada sobre o preço de outro dia, sem nada na tela
indicando isso. Errado em silêncio é pior que bloqueado.

A DECISÃO CENTRAL: O QUE FAZER QUANDO O CALENDÁRIO NÃO SABE
-----------------------------------------------------------
Um calendário de feriados tem validade. Perguntar por uma data fora da
vigência tem três respostas possíveis, e duas são armadilhas:

- Responder `False` ("não é pregão") pula dias úteis de verdade. O pipeline
  emudece e o sintoma é ausência — ninguém investiga o que não aconteceu.
- Responder `True` ("é pregão") é a armadilha do parágrafo anterior: roda em
  feriado sobre cotação velha.
- **Levantar `CalendarioVencido`** é o que este módulo faz. O disparo falha
  alto, o motivo entra no log de execução com a data da vigência, e a
  manutenção do calendário vira tarefa visível em vez de dívida silenciosa.

É a mesma disciplina de `_CAMPOS_MERCADO_OBRIGATORIOS` em `strategy/
covered.py`: dado ausente nunca vira valor assumido.

FERIADO NÃO É DADO DERIVÁVEL
----------------------------
As datas vêm de `src/pregao/feriados_b3.yaml`, com a fonte declarada no
próprio arquivo — não de uma regra calculada aqui. Carnaval e Corpus
Christi são deriváveis da Páscoa, mas a B3 também fecha em datas que
nenhuma regra prevê (24/12 e 31/12, paradas específicas), e uma regra que
acerta 90% das datas é pior que uma lista: erra sem avisar. O arquivo
carrega `conferido.anos` justamente para separar, ANO A ANO, "conferido
contra a fonte" de "derivado das regras e ainda não conferido" — a mesma
distinção que `earnings` faz entre confirmado e estimado.

HORÁRIO É DO ARQUIVO, NÃO DO CÓDIGO
-----------------------------------
A sessão regular da B3 muda (já mudou), e quem opera precisa poder ajustar
a janela sem mexer em Python. `sessao.abertura`/`sessao.fechamento` ficam
no YAML pelo mesmo motivo que `params.yaml` existe.
"""
import datetime as dt
import functools
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ARQUIVO_PADRAO = (
    Path(__file__).resolve().parent / "feriados_b3.yaml"
)


class CalendarioInvalido(RuntimeError):
    """O arquivo de calendário está malformado. Falha alto na carga: um
    calendário meio lido responderia com confiança sobre datas erradas."""


class CalendarioVencido(RuntimeError):
    """Perguntaram por uma data fora da vigência do calendário.

    Não é o mesmo que "não há pregão" — é "não sei", e a diferença é o que
    impede o pipeline de rodar sobre cotação velha num feriado que o arquivo
    não cobre. Quem captura isto deve registrar a falha, não seguir.
    """


@dataclass(frozen=True)
class Calendario:
    fonte: str
    vigencia_de: dt.date
    vigencia_ate: dt.date
    #: `None` enquanto as datas não foram conferidas contra a fonte oficial.
    #: Fica exposto em `/saude-coleta` para "derivado das regras" não passar
    #: por "confirmado".
    conferido_em: dt.date | None
    #: Anos cujas datas foram batidas contra a fonte oficial. Os demais anos
    #: da vigência são DERIVADOS das regras — funcionam, mas não têm o mesmo
    #: peso, e `/saude-coleta` mostra a diferença.
    anos_conferidos: frozenset[int]
    fuso: ZoneInfo
    abertura: dt.time
    fechamento: dt.time
    #: data -> nome do feriado.
    feriados: dict[dt.date, str]

    def cobre(self, data: dt.date) -> bool:
        return self.vigencia_de <= data <= self.vigencia_ate

    def conferido(self, data: dt.date) -> bool:
        """Se as datas do ano de `data` foram conferidas contra a fonte."""
        return data.year in self.anos_conferidos

    def _exigir_cobertura(self, data: dt.date) -> None:
        if not self.cobre(data):
            raise CalendarioVencido(
                f"{data.isoformat()} está fora da vigência do calendário de "
                f"pregão ({self.vigencia_de.isoformat()} a "
                f"{self.vigencia_ate.isoformat()}). Atualize "
                f"{ARQUIVO_PADRAO.name} a partir de {self.fonte} — enquanto "
                "isso, nenhuma execução automática deve rodar: não há como "
                "distinguir dia útil de feriado."
            )


@dataclass(frozen=True)
class Janela:
    """Resposta completa de "posso rodar agora?".

    `esta_em_pregao` devolve só o booleano, que é o que a Fase 1 do plano
    pediu. O log de execução precisa do MOTIVO — "pulou" sem dizer por que
    é exatamente o silêncio que este módulo existe para acabar.
    """

    em_pregao: bool
    motivo: str
    #: Verdadeiro para dia útil com pregão, mesmo fora do horário da sessão.
    #: O ETL pós-fechamento é legítimo; a avaliação intradiária não é.
    dia_de_pregao: bool
    #: Se o ano desta data foi conferido contra a fonte oficial. Falso não
    #: impede a execução — só viaja até o log e a tela, para uma resposta
    #: derivada não ser lida como confirmada.
    ano_conferido: bool = True


def _hora(valor, campo: str) -> dt.time:
    """Aceita `"10:00"` e o `datetime.time` que o PyYAML às vezes já
    devolve, porque a diferença depende do quoting no arquivo e um erro de
    aspas não deveria derrubar o agendador."""
    if isinstance(valor, dt.time):
        return valor
    try:
        return dt.time.fromisoformat(str(valor))
    except ValueError as e:
        raise CalendarioInvalido(f"sessao.{campo} inválido: {valor!r}") from e


def _data(valor, campo: str) -> dt.date:
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    try:
        return dt.date.fromisoformat(str(valor))
    except ValueError as e:
        raise CalendarioInvalido(f"{campo} inválido: {valor!r}") from e


@functools.cache
def carregar(caminho: Path | None = None) -> Calendario:
    """Lê o calendário do disco. Em cache: o agendador dispara muitas vezes
    ao dia e o arquivo só muda quando alguém o edita — nesse caso, o
    processo seguinte já lê a versão nova."""
    caminho = caminho or ARQUIVO_PADRAO
    if not caminho.exists():
        raise CalendarioInvalido(
            f"calendário de pregão não encontrado em {caminho}. Sem ele não "
            "há como distinguir dia útil de feriado, e rodar assim mesmo "
            "produziria sugestão sobre cotação de outro dia."
        )
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}

    for chave in ("fonte", "vigencia", "sessao", "feriados"):
        if chave not in dados:
            raise CalendarioInvalido(f"{caminho.name}: chave obrigatória ausente: {chave!r}")

    vigencia, sessao = dados["vigencia"], dados["sessao"]
    feriados_brutos = dados["feriados"] or {}
    if not isinstance(feriados_brutos, dict):
        raise CalendarioInvalido(
            f"{caminho.name}: `feriados` deve ser um mapa data -> nome. Uma "
            "lista de datas sem nome tornaria o log ilegível ('pulou: "
            "feriado' não diz qual)."
        )

    # `conferido` ausente é estado legítimo — significa "nada conferido
    # ainda", que é o que `derivar.py` produz. Ausente e vazio dão no mesmo.
    conferido = dados.get("conferido") or {}
    if not isinstance(conferido, dict):
        raise CalendarioInvalido(
            f"{caminho.name}: `conferido` deve ser um mapa com `em` e `anos`."
        )

    cal = Calendario(
        fonte=str(dados["fonte"]),
        vigencia_de=_data(vigencia.get("de"), "vigencia.de"),
        vigencia_ate=_data(vigencia.get("ate"), "vigencia.ate"),
        conferido_em=(
            _data(conferido["em"], "conferido.em") if conferido.get("em") else None
        ),
        anos_conferidos=frozenset(int(a) for a in (conferido.get("anos") or [])),
        fuso=ZoneInfo(str(sessao.get("fuso", "America/Sao_Paulo"))),
        abertura=_hora(sessao.get("abertura"), "abertura"),
        fechamento=_hora(sessao.get("fechamento"), "fechamento"),
        feriados={_data(d, "feriados"): str(n) for d, n in feriados_brutos.items()},
    )

    if cal.vigencia_de > cal.vigencia_ate:
        raise CalendarioInvalido(
            f"{caminho.name}: vigência invertida ({cal.vigencia_de} > {cal.vigencia_ate})."
        )
    if cal.abertura >= cal.fechamento:
        raise CalendarioInvalido(
            f"{caminho.name}: sessao.abertura ({cal.abertura}) não é anterior "
            f"a sessao.fechamento ({cal.fechamento}) — nenhum instante seria "
            "pregão e o pipeline nunca rodaria."
        )
    fora = sorted(d for d in cal.feriados if not cal.cobre(d))
    if fora:
        raise CalendarioInvalido(
            f"{caminho.name}: feriados fora da vigência declarada: "
            f"{', '.join(d.isoformat() for d in fora)}. Ou a vigência está "
            "curta demais, ou esses feriados não deveriam estar aqui."
        )
    return cal


def avaliar(momento: dt.datetime, cal: Calendario | None = None) -> Janela:
    """Diz se `momento` está em pregão, e por quê não quando não está.

    `momento` pode vir com ou sem fuso. Sem fuso é interpretado como horário
    local da máquina e convertido — nunca como horário de Brasília por
    suposição, porque um servidor em UTC daria 3h de diferença e a janela
    inteira sairia errada sem nenhum erro aparecer.
    """
    cal = cal or carregar()
    if momento.tzinfo is None:
        momento = momento.astimezone()
    local = momento.astimezone(cal.fuso)
    data = local.date()

    cal._exigir_cobertura(data)  # noqa: SLF001 — método do próprio dataclass
    conferido = cal.conferido(data)

    if data.weekday() >= 5:  # 5 = sábado, 6 = domingo
        dia = "sábado" if data.weekday() == 5 else "domingo"
        return Janela(False, f"fim de semana ({dia})", False, conferido)

    if data in cal.feriados:
        return Janela(False, f"feriado: {cal.feriados[data]}", False, conferido)

    hora = local.time()
    sessao = f"sessão {cal.abertura:%H:%M}–{cal.fechamento:%H:%M}"
    if hora < cal.abertura:
        return Janela(False, f"antes da abertura ({hora:%H:%M}, {sessao})", True, conferido)
    if hora > cal.fechamento:
        return Janela(False, f"após o fechamento ({hora:%H:%M}, {sessao})", True, conferido)

    return Janela(True, f"pregão aberto ({hora:%H:%M})", True, conferido)


def esta_em_pregao(momento: dt.datetime) -> bool:
    """A assinatura pedida pelo plano. Levanta `CalendarioVencido` para data
    fora da vigência — ver o cabeçalho do módulo para por que não é `False`."""
    return avaliar(momento).em_pregao
