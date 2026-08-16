"""Testes do entrypoint de consolidação (`src.earnings.ingest`), com
serviço e providers dublês — sem banco e sem rede."""
import datetime as dt

import pytest

from src.earnings import ingest
from src.earnings.models import (
    EarningsEvent,
    EarningsEventSource,
    EarningsStatus,
    Session,
)
from src.earnings.providers import FonteDesconhecida


AGORA = dt.datetime(2026, 8, 16, tzinfo=dt.timezone.utc)


def _fonte(ticker="PETR4", data=dt.date(2026, 11, 6)):
    return EarningsEventSource(
        ticker=ticker, provider="manual", retrieved_at=AGORA, confidence=95,
        date=data, session=Session.AFTER_CLOSE, fiscal_period="2026Q4",
        status=EarningsStatus.CONFIRMED,
    )


def _evento(ticker="PETR4"):
    return EarningsEvent(
        ticker=ticker, fiscal_period="2026Q4",
        status=EarningsStatus.CONFIRMED, confidence=95,
        first_seen_at=AGORA, updated_at=AGORA,
        confirmed_date=dt.date(2026, 11, 6), session=Session.AFTER_CLOSE,
    )


class _ServicoFake:
    """Dublê de `EarningsEventService` com o mesmo contrato que o entrypoint
    usa: `coletar()` e `ingerir(tickers, coletado=...)`."""

    def __init__(self, coletado, eventos=None):
        self._coletado = coletado
        self._eventos = eventos if eventos is not None else [_evento()]
        self.coletar_chamadas = 0
        self.ingerir_chamadas = 0
        self.coletado_recebido = None

    def coletar(self, tickers):
        self.coletar_chamadas += 1
        return dict(self._coletado)

    def ingerir(self, tickers, coletado=None):
        self.ingerir_chamadas += 1
        self.coletado_recebido = coletado
        return list(self._eventos)


# --- Escopo de tickers -----------------------------------------------------

def test_escopo_padrao_vem_da_carteira(monkeypatch, capsys):
    monkeypatch.setattr(ingest, "tickers_da_carteira", lambda: ["PETR4", "VALE3"])
    servico = _ServicoFake({"manual": [_fonte()]})

    assert ingest.executar(servico=servico) == 0
    saida = capsys.readouterr().out
    assert "2 ticker(s) (posições em aberto)" in saida


def test_tickers_explicitos_substituem_a_carteira(monkeypatch, capsys):
    def _nao_deveria_consultar():
        raise AssertionError("não deve ler a carteira quando --tickers foi dado")

    monkeypatch.setattr(ingest, "tickers_da_carteira", _nao_deveria_consultar)
    servico = _ServicoFake({"manual": [_fonte()]})

    assert ingest.executar(tickers=["PETR4"], servico=servico) == 0
    assert "1 ticker(s) (lista informada)" in capsys.readouterr().out


def test_carteira_vazia_encerra_sem_consultar_fonte(monkeypatch, capsys):
    monkeypatch.setattr(ingest, "tickers_da_carteira", lambda: [])
    servico = _ServicoFake({"manual": [_fonte()]})

    assert ingest.executar(servico=servico) == 0
    assert servico.coletar_chamadas == 0, "não pode gastar chamada de provider"
    assert servico.ingerir_chamadas == 0
    assert "Nenhum ticker a consolidar" in capsys.readouterr().out


# --- Seleção de fontes -----------------------------------------------------

def test_fonte_desconhecida_falha_antes_de_qualquer_consulta():
    servico = _ServicoFake({"manual": [_fonte()]})
    with pytest.raises(FonteDesconhecida, match="bloomberg"):
        ingest.executar(tickers=["PETR4"], fontes=["bloomberg"], servico=servico)
    assert servico.coletar_chamadas == 0


def test_lista_de_fontes_vazia_falha():
    with pytest.raises(FonteDesconhecida, match="nenhuma fonte"):
        ingest.executar(tickers=["PETR4"], fontes=[], servico=_ServicoFake({}))


# --- Relatório por fonte e código de saída ---------------------------------

def test_falha_parcial_conclui_com_sucesso_e_nomeia_a_fonte(capsys):
    """Uma fonte fora do ar não derruba a consolidação das demais, mas
    precisa aparecer para o operador."""
    servico = _ServicoFake({"manual": [_fonte()]})  # `cvm` pedido e ausente
    codigo = ingest.executar(
        tickers=["PETR4"], fontes=["manual", "cvm"], servico=servico
    )
    saida = capsys.readouterr().out

    assert codigo == 0
    assert "manual: 1 afirmação(ões)." in saida
    assert "cvm: FALHOU" in saida
    assert servico.ingerir_chamadas == 1, "as demais fontes foram consolidadas"


def test_falha_total_devolve_codigo_nao_zero(capsys):
    servico = _ServicoFake({})  # nenhuma fonte respondeu
    codigo = ingest.executar(tickers=["PETR4"], servico=servico)
    saida = capsys.readouterr().out

    assert codigo == ingest.EXIT_TODAS_AS_FONTES_FALHARAM
    assert codigo != 0
    assert "NÃO significa que não há resultado próximo" in saida, (
        "silêncio de fonte não pode ser lido como ausência de evento"
    )
    assert servico.ingerir_chamadas == 0, "nada deve ser gravado"


def test_zero_eventos_com_fonte_respondendo_e_sucesso(capsys):
    """"A fonte respondeu e não conhece o ticker" é sucesso — diferente de
    "não conseguimos consultar"."""
    servico = _ServicoFake({"manual": []}, eventos=[])
    codigo = ingest.executar(tickers=["PETR4"], servico=servico)

    assert codigo == 0
    assert "Eventos consolidados: 0." in capsys.readouterr().out


def test_coleta_e_reaproveitada_em_vez_de_repetida(capsys):
    """O provider da CVM baixa o dump IPE a cada chamada: consultar duas
    vezes por execução é inaceitável."""
    coletado = {"manual": [_fonte()]}
    servico = _ServicoFake(coletado)
    ingest.executar(tickers=["PETR4"], servico=servico)

    assert servico.coletar_chamadas == 1
    assert servico.coletado_recebido == coletado, (
        "ingerir precisa receber a coleta já feita"
    )


def test_evento_consolidado_aparece_na_saida(capsys):
    servico = _ServicoFake({"manual": [_fonte()]})
    ingest.executar(tickers=["PETR4"], servico=servico)
    saida = capsys.readouterr().out

    assert "PETR4 2026Q4: 2026-11-06" in saida
    assert "confiança 95" in saida


# --- CLI -------------------------------------------------------------------

def test_cli_converte_listas_separadas_por_virgula(monkeypatch):
    chamadas = {}

    def _fake_executar(tickers=None, fontes=None, servico=None):
        chamadas["tickers"] = tickers
        chamadas["fontes"] = fontes
        return 0

    monkeypatch.setattr(ingest, "executar", _fake_executar)
    assert ingest.main(["--tickers", "PETR4, VALE3", "--fontes", "manual,cvm"]) == 0
    assert chamadas["tickers"] == ["PETR4", "VALE3"]
    assert chamadas["fontes"] == ["manual", "cvm"]


def test_cli_sem_argumentos_deixa_os_padroes(monkeypatch):
    chamadas = {}

    def _fake_executar(tickers=None, fontes=None, servico=None):
        chamadas.update(tickers=tickers, fontes=fontes)
        return 0

    monkeypatch.setattr(ingest, "executar", _fake_executar)
    ingest.main([])
    assert chamadas["tickers"] is None, "None = derivar da carteira"
    assert chamadas["fontes"] is None, "None = usar o padrão manual"


def test_cli_fonte_invalida_sai_com_codigo_2(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        ingest.main(["--tickers", "PETR4", "--fontes", "bloomberg"])
    assert exc.value.code == 2
    assert "bloomberg" in capsys.readouterr().err
