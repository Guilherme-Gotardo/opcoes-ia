"""Testes unitários dos providers — sem rede e sem banco.

O CvmProvider é exercitado contra um zip construído em memória com linhas
no formato REAL do dump IPE, incluindo os casos-armadilha encontrados na
investigação de 2026-08-15.
"""
import csv
import datetime as dt
import io
import zipfile

import pytest

from src.earnings.models import EarningsStatus, Session
from src.earnings.providers.base import EarningsProvider, ProviderIndisponivel
from src.earnings.providers.cvm import (
    CvmProvider,
    normalizar_cnpj_raiz,
    periodo_de,
)
from src.earnings.providers.yahoo import (
    YahooProvider,
    _esta_vazio,
    de_simbolo_yahoo,
    para_simbolo_yahoo,
)

UTC = dt.timezone.utc

COLUNAS_IPE = [
    "CNPJ_Companhia", "Nome_Companhia", "Codigo_CVM", "Data_Referencia",
    "Categoria", "Tipo", "Especie", "Assunto", "Data_Entrega",
    "Tipo_Apresentacao", "Protocolo_Entrega", "Versao", "Link_Download",
]


def linha_ipe(cnpj, nome, referencia, entrega, categoria="Dados Econômico-Financeiros",
              assunto=""):
    return {
        "CNPJ_Companhia": cnpj, "Nome_Companhia": nome, "Codigo_CVM": "1",
        "Data_Referencia": referencia, "Categoria": categoria, "Tipo": "",
        "Especie": "", "Assunto": assunto, "Data_Entrega": entrega,
        "Tipo_Apresentacao": "AP", "Protocolo_Entrega": "x", "Versao": "1",
        "Link_Download": "http://exemplo",
    }


def zip_ipe(tmp_path, linhas, nome="ipe_cia_aberta_2026.zip"):
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=COLUNAS_IPE, delimiter=";")
    escritor.writeheader()
    for l in linhas:
        escritor.writerow(l)
    caminho = tmp_path / nome
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("ipe_cia_aberta_2026.csv", buffer.getvalue().encode("latin-1"))
    return caminho


class TestContrato:
    def test_providers_cumprem_o_protocolo(self):
        assert isinstance(CvmProvider(), EarningsProvider)
        assert isinstance(YahooProvider(yf_module=object()), EarningsProvider)


class TestCnpjEPeriodo:
    @pytest.mark.parametrize("entrada,esperado", [
        ("33.000.167/0001-01", "33000167"),
        ("33000167000101", "33000167"),
        ("00.000.000/0001-91", "00000000"),
        ("", None),
        (None, None),
        ("123", None),
    ])
    def test_normalizacao_de_cnpj(self, entrada, esperado):
        assert normalizar_cnpj_raiz(entrada) == esperado

    @pytest.mark.parametrize("referencia,esperado", [
        (dt.date(2026, 3, 31), "2026Q1"),
        (dt.date(2026, 6, 30), "2026Q2"),
        (dt.date(2026, 9, 30), "2026Q3"),
        (dt.date(2026, 12, 31), "2026Q4"),
    ])
    def test_periodo_vem_da_referencia_sem_inferencia(self, referencia, esperado):
        assert periodo_de(referencia) == esperado


class TestCvmExtracao:
    def _provider(self, tmp_path, monkeypatch, linhas, mapa):
        p = CvmProvider(cache_dir=tmp_path)
        caminho = zip_ipe(tmp_path, linhas)
        monkeypatch.setattr(p, "_baixar", lambda ano: caminho)
        monkeypatch.setattr(p, "_mapa_cnpj_para_tickers", lambda tickers: mapa)
        return p

    def test_extrai_divulgacao_real_da_petrobras(self, tmp_path, monkeypatch):
        """PETR4: referência 30/06, entrega 06/08 → 2026Q2 (dado real)."""
        p = self._provider(
            tmp_path, monkeypatch,
            [linha_ipe("33.000.167/0001-01", "PETROLEO BRASILEIRO", "2026-06-30",
                       "2026-08-06", assunto="Relatório de Desempenho 2T26")],
            {"33000167": ["PETR4"]},
        )
        fontes = p.coletar_divulgacoes(["PETR4"], dt.date(2026, 1, 1), dt.date(2026, 12, 31))
        assert len(fontes) == 1
        assert fontes[0].date == dt.date(2026, 8, 6)
        assert fontes[0].fiscal_period == "2026Q2"
        assert fontes[0].status == EarningsStatus.RELEASED
        assert fontes[0].ticker == "PETR4"

    def test_ignora_categoria_que_nao_e_de_resultado(self, tmp_path, monkeypatch):
        """A armadilha real: a Petrobras publicou «informa sobre resultado do
        2º trimestre» como Comunicado ao Mercado em 07/07, um mês antes."""
        p = self._provider(
            tmp_path, monkeypatch,
            [linha_ipe("33.000.167/0001-01", "PETROBRAS", "2026-07-07", "2026-07-07",
                       categoria="Comunicado ao Mercado",
                       assunto="Petrobras informa sobre resultado do 2º trimestre")],
            {"33000167": ["PETR4"]},
        )
        assert p.coletar_divulgacoes(["PETR4"], dt.date(2026, 1, 1), dt.date(2026, 12, 31)) == []

    def test_ignora_referencia_fora_de_fim_de_trimestre(self, tmp_path, monkeypatch):
        """A armadilha real: o BBAS3 tinha um relatório da Moody's na mesma
        categoria, com Data_Referencia em 21/10."""
        p = self._provider(
            tmp_path, monkeypatch,
            [linha_ipe("00.000.000/0001-91", "BANCO DO BRASIL", "2025-10-21",
                       "2026-06-24", assunto="Relatório Credit Opinion Moody's")],
            {"00000000": ["BBAS3"]},
        )
        assert p.coletar_divulgacoes(["BBAS3"], dt.date(2026, 1, 1), dt.date(2026, 12, 31)) == []

    def test_varios_documentos_no_mesmo_dia_viram_um_evento(self, tmp_path, monkeypatch):
        """ITUB4 entregou «Demonstrações Contábeis» e «Análise Gerencial»
        no mesmo 04/08 — é uma divulgação, não duas."""
        p = self._provider(
            tmp_path, monkeypatch,
            [
                linha_ipe("60.872.504/0001-23", "ITAU", "2026-06-30", "2026-08-04",
                          assunto="Demonstrações Contábeis Completas"),
                linha_ipe("60.872.504/0001-23", "ITAU", "2026-06-30", "2026-08-04",
                          assunto="Análise Gerencial da Operação"),
            ],
            {"60872504": ["ITUB4"]},
        )
        fontes = p.coletar_divulgacoes(["ITUB4"], dt.date(2026, 1, 1), dt.date(2026, 12, 31))
        assert len(fontes) == 1

    def test_mantem_a_entrega_mais_antiga_do_trimestre(self, tmp_path, monkeypatch):
        """Reapresentações vêm depois; o mercado soube na primeira."""
        p = self._provider(
            tmp_path, monkeypatch,
            [
                linha_ipe("60.872.504/0001-23", "ITAU", "2026-06-30", "2026-08-05"),
                linha_ipe("60.872.504/0001-23", "ITAU", "2026-06-30", "2026-08-04"),
            ],
            {"60872504": ["ITUB4"]},
        )
        fontes = p.coletar_divulgacoes(["ITUB4"], dt.date(2026, 1, 1), dt.date(2026, 12, 31))
        assert fontes[0].date == dt.date(2026, 8, 4)

    def test_nao_emite_sessao_porque_o_csv_nao_tem_hora(self, tmp_path, monkeypatch):
        p = self._provider(
            tmp_path, monkeypatch,
            [linha_ipe("33.000.167/0001-01", "PETROBRAS", "2026-06-30", "2026-08-06")],
            {"33000167": ["PETR4"]},
        )
        fonte = p.coletar_divulgacoes(["PETR4"], dt.date(2026, 1, 1), dt.date(2026, 12, 31))[0]
        assert fonte.session is None

    def test_retrieved_at_vem_de_dentro_do_zip_nao_do_download(self, tmp_path, monkeypatch):
        """A latência do dump precisa virar penalidade de idade.

        Usar o mtime do arquivo baixado faria um dump de 6 dias atrás
        parecer recém-coletado.
        """
        p = self._provider(
            tmp_path, monkeypatch,
            [linha_ipe("33.000.167/0001-01", "PETROBRAS", "2026-06-30", "2026-08-06")],
            {"33000167": ["PETR4"]},
        )
        fonte = p.coletar_divulgacoes(["PETR4"], dt.date(2026, 1, 1), dt.date(2026, 12, 31))[0]
        assert fonte.retrieved_at.tzinfo is not None
        # zip_ipe grava agora; o que importa é a origem do valor, então
        # comparamos com o timestamp da entrada do zip, não com o mtime.
        with zipfile.ZipFile(tmp_path / "ipe_cia_aberta_2026.zip") as z:
            entrada = next(i for i in z.infolist() if i.filename.endswith(".csv"))
        assert fonte.retrieved_at.replace(tzinfo=None) == dt.datetime(*entrada.date_time)

    def test_agenda_futura_e_sempre_vazia(self):
        assert CvmProvider().get_upcoming_earnings(["PETR4"]) == []


class TestYahooSimbolos:
    @pytest.mark.parametrize("entrada,esperado", [
        ("PETR4", "PETR4.SA"),
        ("petr4", "PETR4.SA"),
        ("PETR4.SA", "PETR4.SA"),
    ])
    def test_para_simbolo(self, entrada, esperado):
        assert para_simbolo_yahoo(entrada) == esperado

    def test_de_simbolo(self):
        assert de_simbolo_yahoo("PETR4.SA") == "PETR4"
        assert de_simbolo_yahoo("PETR4") == "PETR4"


class TestYahooVazio:
    def test_nan_e_none_sao_vazios(self):
        assert _esta_vazio(None) is True
        assert _esta_vazio(float("nan")) is True
        assert _esta_vazio(4.13) is False


class _FakeTicker:
    def __init__(self, calendar=None, earnings=None):
        self.calendar = calendar or {}
        self.earnings_dates = earnings


class _FakeTabela:
    """Imita o suficiente de um DataFrame do yfinance."""

    def __init__(self, linhas):
        self._linhas = linhas

    def __len__(self):
        return len(self._linhas)

    def iterrows(self):
        return iter(self._linhas)


class _FakeYf:
    def __init__(self, por_simbolo):
        self._por_simbolo = por_simbolo

    def Ticker(self, simbolo):  # noqa: N802 — imita a API do yfinance
        return self._por_simbolo[simbolo]


class TestYahooProvider:
    def test_dependencia_ausente_vira_provider_indisponivel(self, monkeypatch):
        import src.earnings.providers.yahoo as mod
        monkeypatch.setattr(
            mod, "_importar_yfinance",
            lambda: (_ for _ in ()).throw(ProviderIndisponivel("sem yfinance")),
        )
        with pytest.raises(ProviderIndisponivel):
            YahooProvider().get_upcoming_earnings(["PETR4"])

    def test_extrai_data_futura_do_calendar(self):
        yf = _FakeYf({"VALE3.SA": _FakeTicker(
            calendar={"Earnings Date": [dt.date(2099, 10, 29)]}
        )})
        fontes = YahooProvider(yf_module=yf).get_upcoming_earnings(["VALE3"])
        assert len(fontes) == 1
        assert fontes[0].date == dt.date(2099, 10, 29)
        assert fontes[0].status == EarningsStatus.ESTIMATED
        assert fontes[0].ticker == "VALE3"

    def test_ticker_sem_data_futura_nao_gera_fonte(self):
        """PETR4 e ITUB4 reais: calendar vazio. Não é erro."""
        yf = _FakeYf({"PETR4.SA": _FakeTicker(calendar={"Earnings Date": []})})
        assert YahooProvider(yf_module=yf).get_upcoming_earnings(["PETR4"]) == []

    def test_nunca_emite_horario_nem_sessao(self):
        yf = _FakeYf({"VALE3.SA": _FakeTicker(
            calendar={"Earnings Date": [dt.date(2099, 10, 29)]}
        )})
        fonte = YahooProvider(yf_module=yf).get_upcoming_earnings(["VALE3"])[0]
        assert fonte.time is None
        assert fonte.session is None

    def test_evento_ja_reportado_nao_entra_como_futuro(self):
        tabela = _FakeTabela([
            (dt.datetime(2099, 10, 29, tzinfo=UTC), {"Reported EPS": 0.54}),
        ])
        yf = _FakeYf({"VALE3.SA": _FakeTicker(calendar={}, earnings=tabela)})
        assert YahooProvider(yf_module=yf).get_upcoming_earnings(["VALE3"]) == []

    def test_evento_futuro_sem_eps_reportado_entra(self):
        tabela = _FakeTabela([
            (dt.datetime(2099, 10, 29, tzinfo=UTC), {"Reported EPS": float("nan")}),
        ])
        yf = _FakeYf({"VALE3.SA": _FakeTicker(calendar={}, earnings=tabela)})
        fontes = YahooProvider(yf_module=yf).get_upcoming_earnings(["VALE3"])
        assert len(fontes) == 1

    def test_falha_em_um_ticker_nao_derruba_os_outros(self):
        class Explode:
            @property
            def calendar(self):
                raise RuntimeError("boom")

        yf = _FakeYf({
            "PETR4.SA": Explode(),
            "VALE3.SA": _FakeTicker(calendar={"Earnings Date": [dt.date(2099, 10, 29)]}),
        })
        fontes = YahooProvider(yf_module=yf).get_upcoming_earnings(["PETR4", "VALE3"])
        assert [f.ticker for f in fontes] == ["VALE3"]

    def test_confianca_baixa_por_ser_fonte_secundaria(self):
        yf = _FakeYf({"VALE3.SA": _FakeTicker(
            calendar={"Earnings Date": [dt.date(2099, 10, 29)]}
        )})
        assert YahooProvider(yf_module=yf).get_upcoming_earnings(["VALE3"])[0].confidence == 45
