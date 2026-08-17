#!/usr/bin/env python3
"""Um disparo do pipeline de pregão: coleta a cotação e reavalia a carteira.

Rodar:
    python -m scripts.rodar_pregao                    # respeita a janela de pregão
    python -m scripts.rodar_pregao --gatilho systemd  # como o timer chama
    python -m scripts.rodar_pregao --forcar           # ignora a janela (teste)

POR QUE O ETL VEM JUNTO, E NÃO SÓ A AVALIAÇÃO
---------------------------------------------
O plano previa o timer chamando `executar_avaliacao_carteira()` direto. Isso
teria um modo de falha ruim: hoje a única coleta agendada é o
`daily-etl.yml`, às 18h10 (depois do fechamento). Uma avaliação disparada às
14h leria a cotação do fechamento ANTERIOR — que tem menos de 72h e portanto
**passa** na janela de frescor de `params.yaml`. O resultado não seria "dado
insuficiente": seria uma sugestão calculada sobre o preço de ontem, sem nada
na tela dizendo isso.

Coletar antes de avaliar é o que faz a janela de frescor significar o que ela
promete. As duas etapas ficam no mesmo disparo, nesta ordem, sempre.

ORÇAMENTO — O QUE MULTIPLICA
----------------------------
Cada disparo gasta 1 request por ticker do universo (carteira ∪ vigiados). A
cadência multiplica: 14 disparos de 30 em 30 minutos × 20 tickers = 280
requests/dia só de cotação, contra os 600/dia do plano Free. `fetch_quotes`
já corta no orçamento, mas o corte é um `log.warning` que ninguém lê depois —
por isso o gasto entra em `detalhe.orcamento`, onde `/saude-coleta` enxerga.
Cadência e tamanho da watchlist são o MESMO botão; ver `docs/PREGAO.md`.

CÓDIGO DE SAÍDA
---------------
0 = rodou, ou pulou legitimamente (fora de pregão).
1 = falhou. O systemd marca a unidade como falha e a linha em
    `execucao_pipeline` fica com `status='falhou'` e o traceback no detalhe.
"""
import argparse
import datetime as dt
import logging
import sys
import traceback

from src.config import get_settings
from src.db.connection import get_connection
from src.etl import fetch_quotes
from src.etl.budget import requests_gastos_hoje
from src.pregao import execucao
from src.pregao.calendario import CalendarioInvalido, CalendarioVencido, avaliar
from src.strategy.covered import executar_avaliacao_carteira

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("pregao")


def _gasto_hoje() -> int:
    """Requests já gastos hoje contra a Brapi, pelo proxy de `etl.budget`."""
    with get_connection() as conn, conn.cursor() as cur:
        return requests_gastos_hoje(cur)


def _resumo_avaliacao(resultados) -> dict:
    """Resumo do que a avaliação produziu, para o detalhe da execução.

    `pares_avaliados = 0` com `opcoes` vazia é o estado esperado enquanto o
    plano da Brapi não permitir coletar cadeia — e é justamente por isso que
    ele precisa ficar escrito: sem esta linha, "nenhuma sugestão" e "nenhuma
    opção para avaliar" seriam o mesmo silêncio.
    """
    return {
        "pares_avaliados": len(resultados),
        "sugestoes": sum(1 for r in resultados if r.elegivel),
        "bloqueadas_por_resultado": sum(1 for r in resultados if r.bloqueado_por_resultado),
    }


def rodar(gatilho: str = "manual", forcar: bool = False) -> int:
    agora = dt.datetime.now(dt.timezone.utc)

    # A linha abre ANTES de qualquer verificação: se o processo morrer aqui,
    # o rastro fica. Ver o cabeçalho de `src/pregao/execucao.py`.
    execucao_id = execucao.iniciar(gatilho)
    detalhe: dict = {"momento": agora.isoformat()}

    try:
        try:
            janela = avaliar(agora)
        except (CalendarioVencido, CalendarioInvalido) as e:
            # Não é "não é pregão": é "não sei se é". Falhar aqui é o que
            # impede o pipeline de rodar em feriado sobre cotação velha.
            log.error("Calendário de pregão indisponível: %s", e)
            detalhe["calendario"] = {"erro": str(e)}
            execucao.concluir(execucao_id, execucao.FALHOU, detalhe)
            return 1

        detalhe["janela"] = {
            "em_pregao": janela.em_pregao,
            "motivo": janela.motivo,
            "dia_de_pregao": janela.dia_de_pregao,
            "ano_conferido": janela.ano_conferido,
        }
        if not janela.ano_conferido:
            log.warning(
                "As datas de %d no calendário de pregão são DERIVADAS das "
                "regras e ainda não foram conferidas contra a fonte oficial.",
                agora.year,
            )

        if not janela.em_pregao and not forcar:
            log.info("Fora de pregão (%s) — nada a fazer.", janela.motivo)
            execucao.concluir(execucao_id, execucao.PULADO, detalhe)
            return 0

        if forcar and not janela.em_pregao:
            # Registrado no detalhe de propósito: uma execução forçada não
            # pode ser lida depois como se o mercado estivesse aberto.
            log.warning("Fora de pregão (%s), mas --forcar foi pedido.", janela.motivo)
            detalhe["forcado"] = True

        gasto_antes = _gasto_hoje()

        log.info("Etapa 1/2: coletando cotações.")
        fetch_quotes.main()

        gasto_depois = _gasto_hoje()
        limite = get_settings().brapi_requests_dia_maximo
        detalhe["orcamento"] = {
            "gasto_neste_disparo": gasto_depois - gasto_antes,
            "gasto_hoje": gasto_depois,
            "limite_diario": limite,
            "restante_hoje": max(0, limite - gasto_depois),
        }

        log.info("Etapa 2/2: reavaliando a carteira.")
        resultados = executar_avaliacao_carteira()
        detalhe["avaliacao"] = _resumo_avaliacao(resultados)

        execucao.concluir(execucao_id, execucao.EXECUTADO, detalhe)
        log.info("Disparo concluído: %s", detalhe["avaliacao"])
        return 0

    except Exception as e:  # noqa: BLE001 — a falha precisa VIRAR REGISTRO
        # Sem este except, o traceback iria para o journald e o banco ficaria
        # com uma linha 'executando' órfã — perderíamos o motivo, que é a
        # única coisa acionável.
        log.exception("Disparo do pregão falhou.")
        detalhe["erro"] = {
            "tipo": type(e).__name__,
            "mensagem": str(e),
            "traceback": traceback.format_exc(limit=12),
        }
        execucao.concluir(execucao_id, execucao.FALHOU, detalhe)
        return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Um disparo do pipeline de pregão.")
    p.add_argument(
        "--gatilho", default="manual",
        help="quem disparou ('systemd' | 'manual'); vai para o log de execução",
    )
    p.add_argument(
        "--forcar", action="store_true",
        help="roda mesmo fora da janela de pregão (fica marcado no detalhe)",
    )
    args = p.parse_args(argv)
    return rodar(gatilho=args.gatilho, forcar=args.forcar)


if __name__ == "__main__":
    sys.exit(main())
