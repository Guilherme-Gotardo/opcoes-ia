"""Testes do calendário de pregão. Puros — não tocam banco nem rede.

O teste que mais importa aqui é `test_data_fora_da_vigencia_levanta`: é ele
que trava a única regressão perigosa deste módulo. Se um dia alguém "gentilmente"
fizer `esta_em_pregao` devolver `False` para data desconhecida, o pipeline
passa a emudecer em dia útil — ou, pior, a versão simétrica devolve `True` e
ele avalia a carteira num feriado sobre a cotação de outro dia.
"""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from src.pregao import calendario as c
from src.pregao.derivar import feriados_do_ano, pascoa

SP = ZoneInfo("America/Sao_Paulo")

_YAML = """
fonte: "teste"
conferido:
  em: 2026-08-16
  anos: [2026]
vigencia:
  de: 2026-01-01
  ate: 2027-12-31
sessao:
  fuso: "America/Sao_Paulo"
  abertura: "10:00"
  fechamento: "17:00"
feriados:
  2026-12-25: "Natal"
"""


@pytest.fixture
def cal(tmp_path):
    """Um calendário mínimo em disco. Limpa o cache de `carregar` nas duas
    pontas — ele é `functools.cache` e vazaria entre testes."""
    c.carregar.cache_clear()
    p = tmp_path / "cal.yaml"
    p.write_text(_YAML, encoding="utf-8")
    yield c.carregar(p)
    c.carregar.cache_clear()


def _em(ano, mes, dia, hora=14, minuto=30):
    return dt.datetime(ano, mes, dia, hora, minuto, tzinfo=SP)


# --- a janela ---------------------------------------------------------------

def test_dia_util_dentro_da_sessao_e_pregao(cal):
    j = c.avaliar(_em(2026, 8, 19), cal)  # quarta-feira
    assert j.em_pregao and j.dia_de_pregao


@pytest.mark.parametrize(
    "hora,minuto,trecho",
    [(9, 59, "antes da abertura"), (17, 1, "após o fechamento")],
)
def test_fora_do_horario_nao_e_pregao_mas_e_dia_de_pregao(cal, hora, minuto, trecho):
    """A distinção existe porque o ETL pós-fechamento é legítimo — quem não
    é legítima fora da sessão é a AVALIAÇÃO."""
    j = c.avaliar(_em(2026, 8, 19, hora, minuto), cal)
    assert not j.em_pregao
    assert j.dia_de_pregao
    assert trecho in j.motivo


@pytest.mark.parametrize("dia,nome", [(22, "sábado"), (23, "domingo")])
def test_fim_de_semana(cal, dia, nome):
    j = c.avaliar(_em(2026, 8, dia), cal)
    assert not j.em_pregao and not j.dia_de_pregao
    assert nome in j.motivo


def test_feriado_nomeia_o_feriado_no_motivo(cal):
    """"pulou: feriado" sem o nome tornaria o log inauditável meses depois."""
    j = c.avaliar(_em(2026, 12, 25), cal)
    assert not j.em_pregao
    assert "Natal" in j.motivo


def test_limites_da_sessao_sao_inclusivos(cal):
    assert c.avaliar(_em(2026, 8, 19, 10, 0), cal).em_pregao
    assert c.avaliar(_em(2026, 8, 19, 17, 0), cal).em_pregao


# --- fuso: o erro de 3 horas --------------------------------------------------

def test_utc_e_convertido_e_nao_lido_como_horario_local(cal):
    """17h BRT é 20h UTC. Ler o UTC como se fosse local acusaria "após o
    fechamento" às 14h de Brasília, e o pipeline nunca rodaria à tarde."""
    utc = dt.datetime(2026, 8, 19, 17, 30, tzinfo=dt.timezone.utc)  # 14:30 BRT
    j = c.avaliar(utc, cal)
    assert j.em_pregao, j.motivo
    assert "14:30" in j.motivo


def test_datetime_sem_fuso_usa_o_local_da_maquina(cal):
    """Aceitar naive é conveniência; interpretá-lo como horário de Brasília
    por suposição seria o bug que o teste acima descreve, ao contrário."""
    naive = dt.datetime(2026, 8, 19, 14, 30)
    esperado = naive.astimezone().astimezone(SP).time()
    assert f"{esperado:%H:%M}" in c.avaliar(naive, cal).motivo


# --- não saber é diferente de saber que não ----------------------------------

def test_data_fora_da_vigencia_levanta(cal):
    """NÃO devolve False. Ver o cabeçalho deste arquivo."""
    with pytest.raises(c.CalendarioVencido) as e:
        c.avaliar(_em(2030, 3, 5), cal)
    # a mensagem precisa dizer o que fazer, não só que deu errado
    assert "2028" not in str(e.value)
    assert "2027-12-31" in str(e.value)


def test_esta_em_pregao_propaga_o_erro(tmp_path):
    c.carregar.cache_clear()
    p = tmp_path / "cal.yaml"
    p.write_text(_YAML, encoding="utf-8")
    cal = c.carregar(p)
    with pytest.raises(c.CalendarioVencido):
        c.avaliar(_em(2030, 3, 5), cal)
    c.carregar.cache_clear()


def test_ano_derivado_e_marcado_como_nao_conferido(cal):
    assert c.avaliar(_em(2026, 8, 19), cal).ano_conferido is True
    assert c.avaliar(_em(2027, 8, 18), cal).ano_conferido is False


# --- arquivo malformado falha na carga, não na consulta ----------------------

@pytest.mark.parametrize(
    "troca,trecho",
    [
        (("ate: 2027-12-31", "ate: 2025-12-31"), "vigência invertida"),
        (('abertura: "10:00"', 'abertura: "18:00"'), "não é anterior"),
        (('2026-12-25: "Natal"', '2030-12-25: "Natal"'), "fora da vigência"),
        (("fonte: \"teste\"", ""), "fonte"),
    ],
)
def test_arquivo_invalido_falha_alto(tmp_path, troca, trecho):
    c.carregar.cache_clear()
    p = tmp_path / "cal.yaml"
    p.write_text(_YAML.replace(*troca), encoding="utf-8")
    with pytest.raises(c.CalendarioInvalido) as e:
        c.carregar(p)
    assert trecho in str(e.value)
    c.carregar.cache_clear()


def test_arquivo_ausente_falha_alto(tmp_path):
    c.carregar.cache_clear()
    with pytest.raises(c.CalendarioInvalido):
        c.carregar(tmp_path / "nao-existe.yaml")
    c.carregar.cache_clear()


# --- a derivação ------------------------------------------------------------

@pytest.mark.parametrize(
    "ano,esperado",
    [
        (2024, dt.date(2024, 3, 31)), (2025, dt.date(2025, 4, 20)),
        (2026, dt.date(2026, 4, 5)), (2027, dt.date(2027, 3, 28)),
        (2028, dt.date(2028, 4, 16)),
    ],
)
def test_pascoa_bate_com_as_datas_conhecidas(ano, esperado):
    assert pascoa(ano) == esperado
    assert pascoa(ano).weekday() == 6  # sempre domingo, por definição


#: As 14 datas de 2026 conferidas contra o calendário oficial da B3 (via
#: BrasilAPI) em 2026-08-16. É a âncora da derivação: se `derivar.py` deixar
#: de reproduzi-las, a regra mudou e 2027+ deixaram de ser confiáveis.
_2026_CONFERIDO = {
    dt.date(2026, 1, 1), dt.date(2026, 2, 16), dt.date(2026, 2, 17),
    dt.date(2026, 4, 3), dt.date(2026, 4, 21), dt.date(2026, 5, 1),
    dt.date(2026, 6, 4), dt.date(2026, 9, 7), dt.date(2026, 10, 12),
    dt.date(2026, 11, 2), dt.date(2026, 11, 20), dt.date(2026, 12, 24),
    dt.date(2026, 12, 25), dt.date(2026, 12, 31),
}


def test_derivacao_reproduz_o_ano_conferido():
    assert set(feriados_do_ano(2026)) == _2026_CONFERIDO


def test_derivacao_omite_feriado_em_fim_de_semana():
    """15/11/2026 (Proclamação da República) cai num domingo. Repetir a
    informação faria o arquivo divergir da lista oficial sem ganho — sábado
    e domingo já são barrados antes de a lista ser consultada."""
    assert dt.date(2026, 11, 15).weekday() == 6
    assert dt.date(2026, 11, 15) not in feriados_do_ano(2026)


def test_calendario_do_repositorio_carrega():
    """O arquivo real, não um sintético: um YAML quebrado em produção só
    apareceria no primeiro disparo do timer."""
    c.carregar.cache_clear()
    cal = c.carregar()
    assert cal.feriados
    assert cal.vigencia_de <= dt.date(2026, 8, 16) <= cal.vigencia_ate
    assert 2026 in cal.anos_conferidos
    c.carregar.cache_clear()
