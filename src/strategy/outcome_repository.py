"""Persistência e consulta do desfecho de execução da avaliação.

Grava e lê `desfecho_avaliacao` (migração 003). Não classifica nem agrega —
isso é de `src/strategy/outcome.py`; aqui só entra e sai do banco.

As funções recebem um cursor em vez de abrirem conexão porque a gravação
acontece DENTRO da mesma transação que persiste as sugestões: uma execução
que gravasse sugestões e falhasse ao gravar o desfecho deixaria a interface
mostrando sugestões sem saber o que mais aconteceu.
"""
import datetime as dt
import json
import logging

from src.db.connection import get_connection
from src.strategy.outcome import LinhaDesfecho

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def gravar(cur, executado_em: dt.datetime, linhas: list[LinhaDesfecho]) -> int:
    """Grava as linhas do desfecho de uma execução. Retorna quantas gravou.

    Todas compartilham o mesmo `executado_em` — é ele que agrupa a execução e
    o que distingue duas rodadas no mesmo dia.
    """
    if not linhas:
        return 0
    cur.executemany(
        """
        INSERT INTO desfecho_avaliacao (
            executado_em, ticker_objeto, motivo, quantidade,
            criterios_contagem, amostra
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        [
            (
                executado_em, linha.ticker_objeto, linha.motivo, linha.quantidade,
                json.dumps(linha.criterios_contagem or {}),
                json.dumps(linha.amostra) if linha.amostra else None,
            )
            for linha in linhas
        ],
    )
    return len(linhas)


def _linha(row) -> LinhaDesfecho:
    ticker, motivo, quantidade, contagem, amostra = row
    if isinstance(contagem, str):
        contagem = json.loads(contagem)
    if isinstance(amostra, str):
        amostra = json.loads(amostra)
    return LinhaDesfecho(
        ticker_objeto=ticker, motivo=motivo, quantidade=quantidade,
        criterios_contagem=contagem or {}, amostra=amostra,
    )


def ultima_execucao_do_dia(data: dt.date) -> list[LinhaDesfecho]:
    """Desfecho da execução mais recente da data pedida.

    A execução mais recente, não a união do dia: rodar de novo substitui a
    leitura, senão o relatório somaria contagens de rodadas diferentes e
    mostraria "18 opções reprovadas" onde foram 9, duas vezes.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(executado_em) FROM desfecho_avaliacao "
            "WHERE executado_em::date = %s",
            (data,),
        )
        linha = cur.fetchone()
        momento = linha[0] if linha else None
        if momento is None:
            return []

        cur.execute(
            "SELECT ticker_objeto, motivo, quantidade, criterios_contagem, amostra "
            "FROM desfecho_avaliacao WHERE executado_em = %s "
            "ORDER BY ticker_objeto, motivo",
            (momento,),
        )
        return [_linha(row) for row in cur.fetchall()]
