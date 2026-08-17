"""Gera um RASCUNHO do calendário de pregão a partir das regras publicadas.

Rodar:
    python -m src.pregao.derivar 2026 2028 > src/pregao/feriados_b3.yaml

O QUE ISTO É, E O QUE NÃO É
---------------------------
As datas saem daqui **derivadas de regra**: feriados nacionais de data fixa
(lei), os móveis ancorados na Páscoa (computus gregoriano) e os dois dias em
que a B3 não opera por decisão própria (24/12 e 31/12). Isso cobre o caso
normal e é auditável — a regra está escrita, não é uma lista que alguém
digitou de memória.

Não é fonte de autoridade. A B3 já parou em datas que nenhuma regra prevê, e
a lista oficial vem do calendário da própria bolsa. Por isso a saída sai com
`conferido.anos: []`: o calendário FUNCIONA derivado, mas `/saude-coleta`
mostra ano a ano que ele ainda não foi batido contra a fonte. Acrescentar um
ano a `conferido.anos` é ato humano deliberado, igual a `earnings.manage` só
ter autoridade para `CONFIRMED` quando a pessoa leu no site de RI.

Evidência de que a regra está certa: rodada sobre 2026, a derivação reproduz
exatamente as 14 datas conferidas contra a fonte, sem sobra nem falta — é o
que `tests/test_pregao_calendario.py` trava contra regressão.

Feriado que cai em fim de semana não entra: `calendario.avaliar` já barra
sábado e domingo antes de olhar a lista, e repetir a informação só faria o
arquivo divergir da lista oficial sem ganho nenhum.
"""
import argparse
import datetime as dt
import sys

#: Feriados nacionais de data fixa em que a B3 não opera.
_FIXOS = {
    (1, 1): "Confraternização Universal",
    (4, 21): "Tiradentes",
    (5, 1): "Dia do Trabalho",
    (9, 7): "Independência do Brasil",
    (10, 12): "Nossa Senhora Aparecida",
    (11, 2): "Finados",
    (11, 15): "Proclamação da República",
    # Nacional desde a Lei 14.759/2023 — antes disso era feriado apenas
    # municipal/estadual em parte do país, e a B3 operava normalmente.
    (11, 20): "Consciência Negra",
    (12, 25): "Natal",
    # Não são feriado civil: são dias em que a B3 não realiza pregão.
    # Derivar só dos feriados nacionais deixaria estes dois de fora, e o
    # pipeline rodaria em 24/12 sobre a cotação do dia 23.
    (12, 24): "Véspera de Natal (B3 sem pregão)",
    (12, 31): "Véspera de Ano-Novo (B3 sem pregão)",
}

#: Feriados móveis, em dias de deslocamento a partir do domingo de Páscoa.
_MOVEIS = {
    -48: "Carnaval (segunda-feira)",
    -47: "Carnaval (terça-feira)",
    -2: "Sexta-feira Santa",
    60: "Corpus Christi",
}


def pascoa(ano: int) -> dt.date:
    """Domingo de Páscoa pelo computus gregoriano (algoritmo anônimo).

    Determinístico e verificável — é a mesma regra que a Igreja e os
    calendários civis usam, não uma aproximação.
    """
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mes, dia = divmod(h + m - 7 * n + 114, 31)
    return dt.date(ano, mes, dia + 1)


def feriados_do_ano(ano: int) -> dict[dt.date, str]:
    """Feriados de pregão do ano, sem os que caem em fim de semana."""
    datas: dict[dt.date, str] = {}
    for (mes, dia), nome in _FIXOS.items():
        datas[dt.date(ano, mes, dia)] = nome
    domingo = pascoa(ano)
    for deslocamento, nome in _MOVEIS.items():
        datas[domingo + dt.timedelta(days=deslocamento)] = nome
    return {d: n for d, n in sorted(datas.items()) if d.weekday() < 5}


def render(de: int, ate: int) -> str:
    linhas = [
        "# Calendário de pregão da B3 — feriados e horário da sessão.",
        "#",
        "# GERADO por `python -m src.pregao.derivar` a partir das regras",
        "# publicadas (feriados nacionais + os dois dias sem pregão da B3).",
        "# Ano que NÃO estiver em `conferido.anos` é DERIVADO e não conferido",
        "# contra a fonte oficial — o estado aparece em /saude-coleta de",
        "# propósito, para derivado não passar por confirmado.",
        "#",
        "# Para conferir: abra a fonte abaixo, compare data a data, acrescente",
        "# o ano a `conferido.anos` e atualize `conferido.em`.",
        "",
        'fonte: "https://brasilapi.com.br/api/feriados/v1 (calendário oficial da B3)"',
        "",
        "conferido:",
        "  em: null",
        "  anos: []",
        "",
        "vigencia:",
        f"  de: {de}-01-01",
        f"  ate: {ate}-12-31",
        "",
        "# Sessão regular do mercado à vista. Fica aqui, e não em código,",
        "# porque o horário da B3 já mudou e mudará de novo — e quem opera",
        "# precisa ajustar a janela sem editar Python.",
        "sessao:",
        '  fuso: "America/Sao_Paulo"',
        '  abertura: "10:00"',
        '  fechamento: "17:00"',
        "",
        "feriados:",
    ]
    for ano in range(de, ate + 1):
        linhas.append(f"  # {ano}")
        for data, nome in feriados_do_ano(ano).items():
            linhas.append(f'  {data.isoformat()}: "{nome}"')
    return "\n".join(linhas) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("de", type=int, help="primeiro ano da vigência")
    p.add_argument("ate", type=int, help="último ano da vigência")
    args = p.parse_args(argv)
    if args.ate < args.de:
        p.error("o último ano não pode ser anterior ao primeiro")
    sys.stdout.write(render(args.de, args.ate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
