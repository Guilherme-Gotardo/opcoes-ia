"""Testes de src.etl.budget — orçamento diário de requests da Brapi (não
depende de Postgres real, usa um cursor fake)."""
from src.etl.budget import orcamento_restante_hoje, requests_gastos_hoje


class _FakeCursor:
    def __init__(self, gastos_hoje: int):
        self._gastos_hoje = gastos_hoje
        self.queries = []

    def execute(self, query, params=()):
        self.queries.append((query, params))

    def fetchone(self):
        return (self._gastos_hoje,)


def test_requests_gastos_hoje_retorna_contagem_do_cursor():
    cursor = _FakeCursor(gastos_hoje=42)
    assert requests_gastos_hoje(cursor) == 42
    assert "cotacoes" in cursor.queries[0][0]
    assert "opcoes" in cursor.queries[0][0]


def test_orcamento_restante_hoje_subtrai_gasto():
    cursor = _FakeCursor(gastos_hoje=100)
    assert orcamento_restante_hoje(cursor, limite_diario=600) == 500


def test_orcamento_restante_hoje_nunca_negativo():
    cursor = _FakeCursor(gastos_hoje=700)
    assert orcamento_restante_hoje(cursor, limite_diario=600) == 0
