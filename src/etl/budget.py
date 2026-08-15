"""Orçamento de requests para os ETLs de mercado que usam a Brapi (plano
Free: 15.000 requests/mês, meta operacional de ~600/dia — ver design.md,
decisão 7 da change `build-portfolio-mvp-flow`).

Não existe tabela dedicada para contar requests: o gasto do dia é estimado
pelo número de linhas já gravadas hoje em `cotacoes`/`opcoes` com
`fonte = 'brapi'` (cada linha bem-sucedida representa 1 request feito nesse
dia, já que o plano Free permite 1 ativo por requisição). Isso subestima
levemente o gasto real quando um request falha antes de gravar uma linha
(ex.: ticker não encontrado) — aceito como aproximação razoável em vez de
manter uma tabela de contagem exata só para isso (ver design.md, decisão 7).

O "dia" usado aqui é UTC, pela mesma convenção do resto do projeto (ver
cabeçalho de `schema.sql` e `report/daily.py`).
"""
import datetime as dt


def requests_gastos_hoje(cur, fonte: str = "brapi") -> int:
    """Conta quantas linhas de `cotacoes`/`opcoes` já foram gravadas hoje
    (UTC) com a `fonte` informada — proxy do número de requests já gastos
    hoje contra o provedor."""
    hoje = dt.datetime.now(dt.timezone.utc).date()
    cur.execute(
        "SELECT "
        "(SELECT COUNT(*) FROM cotacoes WHERE fonte = %s AND coletado_em::date = %s) + "
        "(SELECT COUNT(*) FROM opcoes WHERE fonte = %s AND coletado_em::date = %s)",
        (fonte, hoje, fonte, hoje),
    )
    return cur.fetchone()[0]


def orcamento_restante_hoje(cur, limite_diario: int, fonte: str = "brapi") -> int:
    """Quantos requests ainda cabem no orçamento diário configurado, dado o
    que já foi gasto hoje. Nunca retorna negativo."""
    gastos = requests_gastos_hoje(cur, fonte)
    return max(0, limite_diario - gastos)
