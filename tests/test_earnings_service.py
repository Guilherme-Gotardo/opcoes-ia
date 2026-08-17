"""Contrato operacional da coleta de earnings, sem banco nem rede."""
import datetime as dt

from src.earnings.models import (
    EarningsEventSource,
    EarningsStatus,
    Session,
)
from src.earnings.providers.base import ProviderIndisponivel
from src.earnings.service import (
    CODIGO_ERRO_PROVIDER,
    CODIGO_PROVIDER_INDISPONIVEL,
    CODIGO_SEM_AFIRMACOES,
    CODIGO_UNIVERSO_VAZIO,
    EarningsEventService,
)
from src.etl.result import EstadoColeta


AGORA = dt.datetime(2026, 8, 17, tzinfo=dt.timezone.utc)


def _fonte(provider: str, ticker: str = "PETR4") -> EarningsEventSource:
    return EarningsEventSource(
        ticker=ticker,
        provider=provider,
        retrieved_at=AGORA,
        confidence=95,
        date=dt.date(2026, 11, 6),
        session=Session.AFTER_CLOSE,
        fiscal_period="2026Q4",
        status=EarningsStatus.CONFIRMED,
    )


class _ProviderFake:
    def __init__(self, name, retorno=None, erro=None):
        self.name = name
        self.retorno = retorno if retorno is not None else []
        self.erro = erro
        self.chamadas = 0

    def get_upcoming_earnings(self, tickers):
        self.chamadas += 1
        if self.erro is not None:
            raise self.erro
        return list(self.retorno)


def test_sucesso_vazio_do_provider_e_preservado():
    provider = _ProviderFake("manual", retorno=[])
    coleta = EarningsEventService(providers=[provider]).coletar_com_resultado(
        ["PETR4"]
    )

    assert coleta.afirmacoes == {"manual": []}
    assert coleta.falhas == {}
    assert coleta.resultados_por_provider[0].estado == EstadoColeta.SUCESSO
    detalhe = coleta.resultados_por_provider[0].detalhes[0]
    assert detalhe.ticker == "fonte:manual"
    assert detalhe.codigo_motivo == CODIGO_SEM_AFIRMACOES
    assert coleta.resultado.estado == EstadoColeta.SUCESSO


def test_falha_retém_excecao_motivo_e_codigo_estavel():
    erro = ProviderIndisponivel("CVM fora do ar")
    coleta = EarningsEventService(
        providers=[_ProviderFake("cvm", erro=erro)]
    ).coletar_com_resultado(["PETR4"])

    assert coleta.falhas["cvm"] is erro
    resultado = coleta.resultados_por_provider[0]
    assert resultado.estado == EstadoColeta.FALHA
    assert resultado.detalhes[0].ticker == "fonte:cvm"
    assert resultado.detalhes[0].codigo_motivo == CODIGO_PROVIDER_INDISPONIVEL
    assert resultado.detalhes[0].detalhe == "CVM fora do ar"


def test_erro_inesperado_tem_codigo_distinto_de_indisponibilidade():
    coleta = EarningsEventService(
        providers=[_ProviderFake("yfinance", erro=ValueError("payload inválido"))]
    ).coletar_com_resultado(["PETR4"])

    assert (
        coleta.resultados_por_provider[0].detalhes[0].codigo_motivo
        == CODIGO_ERRO_PROVIDER
    )


def test_resultado_agregado_e_parcial_quando_so_um_provider_falha():
    manual = _ProviderFake("manual", retorno=[_fonte("manual")])
    cvm = _ProviderFake("cvm", erro=ProviderIndisponivel("timeout"))
    coleta = EarningsEventService(
        providers=[manual, cvm]
    ).coletar_com_resultado(["PETR4", "VALE3"])

    assert coleta.resultado.estado == EstadoColeta.PARCIAL
    assert coleta.afirmacoes == {"manual": [_fonte("manual")]}
    assert set(coleta.falhas) == {"cvm"}
    assert [item.ticker for item in coleta.resultado.detalhes] == [
        "fonte:manual", "fonte:cvm"
    ]


def test_universo_vazio_e_pulado_sem_chamar_providers():
    manual = _ProviderFake("manual", retorno=[_fonte("manual")])
    cvm = _ProviderFake("cvm", retorno=[_fonte("cvm")])
    coleta = EarningsEventService(
        providers=[manual, cvm]
    ).coletar_com_resultado([])

    assert manual.chamadas == cvm.chamadas == 0
    assert coleta.afirmacoes == {}
    assert coleta.falhas == {}
    assert coleta.resultado.estado == EstadoColeta.PULADO
    assert coleta.resultado.motivo == CODIGO_UNIVERSO_VAZIO
    assert all(
        resultado.estado == EstadoColeta.PULADO
        and resultado.motivo == CODIGO_UNIVERSO_VAZIO
        for resultado in coleta.resultados_por_provider
    )


def test_ingerir_aceita_contrato_sem_consultar_provider_de_novo():
    provider = _ProviderFake("manual", retorno=[])
    servico = EarningsEventService(providers=[provider])
    coleta = servico.coletar_com_resultado(["PETR4"])

    assert servico.ingerir(["PETR4"], coletado=coleta) == []
    assert provider.chamadas == 1
