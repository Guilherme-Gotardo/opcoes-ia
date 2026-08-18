"""Orquestrador operacional contra Postgres descartável e providers dublês."""
import datetime as dt
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.agente.notificar import NotificacaoErro
from src.agente.relatorio import Relatorio
from src.etl.result import DetalheAlvo, EstadoAlvo, ResultadoColeta
from src.operations import orchestrator as mod
from src.pregao import execucao
from src.report.repository import por_execucao

psycopg = pytest.importorskip("psycopg")

AMBIENTE = "zz-operations"
AGORA = dt.datetime(2026, 8, 17, 15, 5, tzinfo=dt.timezone.utc)
DATA = AGORA.date()


def _banco_disponivel() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.execucao_etapa_tentativa')")
            return cur.fetchone()[0] is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _banco_disponivel(),
    reason="Postgres descartável indisponível ou migração 010 não aplicada",
)


def _limpar() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM notificacoes_relatorio WHERE execution_id IN ("
            "SELECT execution_id FROM execucao_pipeline WHERE ambiente = %s)",
            (AMBIENTE,),
        )
        cur.execute(
            "DELETE FROM relatorios_agente WHERE execution_id IN ("
            "SELECT execution_id FROM execucao_pipeline WHERE ambiente = %s)",
            (AMBIENTE,),
        )
        cur.execute(
            "DELETE FROM relatorios_deterministicos WHERE execution_id IN ("
            "SELECT execution_id FROM execucao_pipeline WHERE ambiente = %s)",
            (AMBIENTE,),
        )
        cur.execute("DELETE FROM execucao_pipeline WHERE ambiente = %s", (AMBIENTE,))
        cur.execute("DELETE FROM sugestoes WHERE ticker_objeto = 'ZZOPS'")
        cur.execute("DELETE FROM desfecho_avaliacao WHERE ticker_objeto = 'ZZOPS'")
        cur.execute("DELETE FROM ativos WHERE ticker = 'ZZOPS'")
        conn.commit()


@pytest.fixture(autouse=True)
def ambiente_descartavel(monkeypatch):
    monkeypatch.setenv("OPCOES_IA_ENV", AMBIENTE)
    _limpar()
    yield
    _limpar()


def _coleta(nome: str) -> ResultadoColeta:
    return ResultadoColeta.de_detalhes(
        nome, "fake", [DetalheAlvo("ZZOPS", EstadoAlvo.SUCESSO, 1)]
    )


def _calendario():
    return SimpleNamespace(
        em_pregao=True, motivo="pregão aberto", dia_de_pregao=True,
        ano_conferido=True,
    )


class Avaliacao:
    ticker_objeto = "ZZOPS"
    codigo_opcao = "ZZOPSA1"
    tipo_operacao = "covered_call"
    elegivel = False
    strike = 10.0
    vencimento = "2026-09-18"
    premio_estimado = 0.5
    preco_mercado = 10.0
    cotacao_em = AGORA.isoformat()

    def criterios_json(self):
        return {
            "criterios": [{
                "nome": "delta", "valor": 0.2, "detalhe": "0.2 (faixa)",
                "estado": "aprovado", "aprovado": True,
            }],
            "motivo_nao_elegivel": "critério(s) não atendido(s): iv_rank",
        }


def _avaliar_persistindo(executado_em):
    vereditos = Avaliacao().criterios_json()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ativos (ticker, nome, tipo) VALUES "
            "('ZZOPS', 'Teste Operations', 'acao') ON CONFLICT (ticker) DO NOTHING"
        )
        cur.execute(
            "INSERT INTO desfecho_avaliacao ("
            "executado_em, ticker_objeto, motivo, quantidade, criterios_contagem, amostra"
            ") VALUES (%s, 'ZZOPS', 'criterio_reprovado', 1, %s, %s)",
            (executado_em, json.dumps({"iv_rank": 1}), json.dumps({
                "codigo_opcao": "ZZOPSA1", "criterios": vereditos["criterios"],
            })),
        )
        cur.execute(
            "INSERT INTO sugestoes ("
            "ticker_objeto, tipo_operacao, codigo_opcao, strike, vencimento, "
            "premio_estimado, criterios_json, gerado_em, status"
            ") VALUES ('ZZOPS', 'covered_call', 'ZZOPSA1', 10, %s, 0.5, %s, %s, "
            "'pendente')",
            (dt.date(2026, 9, 18), json.dumps(vereditos), executado_em),
        )
        conn.commit()
    return [Avaliacao()]


def _patches_daily(*, quant=None, compor=None, notificar=None):
    quant = quant or (lambda *args, **kwargs: 1)
    compor = compor or (lambda insumo: Relatorio("Leitura.", "teste"))
    notificar = notificar or (lambda *args, **kwargs: True)
    return (
        patch("src.etl.fetch_quotes.main", return_value=_coleta("cotacoes")),
        patch("src.etl.fetch_candles.main", side_effect=lambda intervalo: _coleta(
            f"candles_{intervalo}"
        )),
        patch("src.etl.fetch_options.main", return_value=_coleta("opcoes")),
        patch("src.etl.fetch_news.main", return_value=_coleta("noticias")),
        patch.object(mod, "_executar_earnings", return_value=_coleta("earnings")),
        patch(
            "src.strategy.covered.executar_avaliacao_carteira",
            side_effect=lambda executado_em: _avaliar_persistindo(executado_em),
        ),
        patch("src.quant.pipeline.enriquecer_execucao", side_effect=quant),
        patch("src.agente.relatorio.compor", side_effect=compor),
        patch("src.agente.notificar.notificar_relatorio", side_effect=notificar),
    )


def test_entrega_repetida_da_mesma_janela_sai_antes_do_provider():
    janela_scheduler = "2026-08-17T10:00:00-03:00"
    with patch("src.pregao.calendario.avaliar", return_value=_calendario()), \
         patch("src.etl.fetch_quotes.main", return_value=_coleta("cotacoes")) as quotes, \
         patch("src.strategy.covered.executar_avaliacao_carteira", return_value=[]), \
         patch("src.quant.pipeline.enriquecer_execucao", return_value=0):
        primeira = mod.executar_intraday(
            agora=AGORA, janela=janela_scheduler, gatilho="eventbridge",
        )
        segunda = mod.executar_intraday(
            agora=AGORA, janela=janela_scheduler, gatilho="eventbridge",
        )

    assert primeira.codigo_saida == 0
    assert segunda.status == "duplicada" and segunda.codigo_saida == 0
    quotes.assert_called_once()
    assert primeira.execution_id == segunda.execution_id
    assert primeira.janela_logica == segunda.janela_logica == janela_scheduler


def test_intraday_pula_fora_do_pregao_e_forcar_mantem_ordem():
    fechado = SimpleNamespace(
        em_pregao=False, motivo="após fechamento", dia_de_pregao=True,
        ano_conferido=True,
    )
    with patch("src.pregao.calendario.avaliar", return_value=fechado), \
         patch("src.etl.fetch_quotes.main") as quotes:
        pulada = mod.executar_intraday(agora=AGORA, janela="fora-pregao")

    assert pulada.status == execucao.PULADO and pulada.codigo_saida == 0
    quotes.assert_not_called()

    with patch("src.pregao.calendario.avaliar", return_value=fechado), \
         patch("src.etl.fetch_quotes.main", return_value=_coleta("cotacoes")) as quotes, \
         patch("src.strategy.covered.executar_avaliacao_carteira", return_value=[]), \
         patch("src.quant.pipeline.enriquecer_execucao", return_value=0):
        forcada = mod.executar_intraday(
            agora=AGORA, janela="fora-pregao-forcada", forcar=True,
        )

    assert forcada.codigo_saida == 0
    quotes.assert_called_once()
    tentativa = execucao.RepositorioExecucao().tentativas(forcada.execution_id)[0]
    assert tentativa.etapa == mod.ETAPA_CALENDARIO
    assert tentativa.detalhe["forcado"] is True


def test_intraday_calendario_desconhecido_falha_alto_sem_cotacao():
    from src.pregao.calendario import CalendarioVencido

    with patch(
        "src.pregao.calendario.avaliar",
        side_effect=CalendarioVencido("fora da vigência"),
    ), patch("src.etl.fetch_quotes.main") as quotes:
        resultado = mod.executar_intraday(
            agora=AGORA, janela="calendario-vencido",
        )

    assert resultado.status == execucao.FALHOU
    assert resultado.codigo_saida == 1
    quotes.assert_not_called()


def test_resume_recusa_etapa_externa_ambigua_e_override_reentra():
    repo = execucao.RepositorioExecucao()
    janela = mod.janela_logica("intraday", AGORA)
    aquisicao = repo.adquirir(AMBIENTE, "intraday", janela, "pytest")
    aberta = repo.iniciar_etapa(aquisicao.execucao.execution_id, mod.ETAPA_COTACOES)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE execucao_pipeline SET heartbeat_em = now() - interval '2 hours' "
            "WHERE execution_id = %s",
            (aquisicao.execucao.execution_id,),
        )
        conn.commit()

    with patch("src.etl.fetch_quotes.main") as quotes:
        recusada = mod.executar_intraday(agora=AGORA, resume=True)
    assert recusada.status == "resume_recusado"
    quotes.assert_not_called()

    with patch("src.pregao.calendario.avaliar", return_value=_calendario()), \
         patch("src.etl.fetch_quotes.main", return_value=_coleta("cotacoes")) as quotes, \
         patch("src.strategy.covered.executar_avaliacao_carteira", return_value=[]), \
         patch("src.quant.pipeline.enriquecer_execucao", return_value=0):
        retomada = mod.executar_intraday(
            agora=AGORA, resume=True,
            repetir_etapas_externas=frozenset({mod.ETAPA_COTACOES}),
        )

    assert retomada.codigo_saida == 0
    quotes.assert_called_once()
    historico = repo.tentativas(aquisicao.execucao.execution_id)
    cotacoes = [item for item in historico if item.etapa == mod.ETAPA_COTACOES]
    assert [item.tentativa for item in cotacoes] == [aberta.tentativa, 2]
    assert cotacoes[0].status == execucao.ETAPA_FALHA
    assert cotacoes[1].status == execucao.ETAPA_SUCESSO


def test_falha_quant_nao_remove_decisao_nem_relatorio_deterministico():
    def falhar_quant(*args, **kwargs):
        raise RuntimeError("QuantLib indisponível")

    patches = _patches_daily(quant=falhar_quant)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8]:
        resultado = mod.executar_daily(agora=AGORA)

    assert resultado.status == execucao.PARCIAL
    assert resultado.codigo_saida == 0
    assert por_execucao(resultado.execution_id) is not None
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM desfecho_avaliacao WHERE ticker_objeto = 'ZZOPS'"
        )
        assert cur.fetchone()[0] == 1


def test_falha_smtp_preserva_relatorios_persistidos():
    def falhar_smtp(*args, **kwargs):
        raise NotificacaoErro("SMTP indisponível")

    patches = _patches_daily(notificar=falhar_smtp)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8]:
        resultado = mod.executar_daily(agora=AGORA)

    assert resultado.status == execucao.PARCIAL
    assert resultado.codigo_saida == 0
    assert por_execucao(resultado.execution_id) is not None
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM relatorios_agente WHERE execution_id = %s",
            (resultado.execution_id,),
        )
        assert cur.fetchone()[0] == 1

    with patch("src.etl.fetch_quotes.main") as quotes, \
         patch("src.etl.fetch_candles.main") as candles, \
         patch("src.etl.fetch_options.main") as options, \
         patch("src.etl.fetch_news.main") as news, \
         patch.object(mod, "_executar_earnings") as earnings, \
         patch("src.strategy.covered.executar_avaliacao_carteira") as avaliar, \
         patch("src.quant.pipeline.enriquecer_execucao") as quant, \
         patch("src.agente.relatorio.compor") as compor, \
         patch("src.agente.notificar.notificar_relatorio", return_value=True) as smtp:
        retomada = mod.executar_daily(agora=AGORA, resume=True)

    assert retomada.status == execucao.EXECUTADO
    smtp.assert_called_once()
    for chamada in (quotes, candles, options, news, earnings, avaliar, quant, compor):
        chamada.assert_not_called()


def test_carimbo_da_avaliacao_vem_do_relogio_da_execucao():
    """A avaliação carimba o instante da EXECUÇÃO, não um `now()` novo.

    `janela` e `data` saem de `agora`, e o agente lê o insumo POR DATA. Um
    segundo relógio dentro do mesmo fluxo grava sugestão e desfecho num dia
    enquanto a leitura procura no outro: o insumo sai vazio, a etapa do
    agente é pulada como "sem_avaliacao_persistida" e o dia fica sem
    relatório — sem nada falhar. Uma execução que atravesse a virada do dia
    cai exatamente nisso, e foi assim que o CI quebrou: a suíte passava
    enquanto a data real coincidia com a injetada aqui.
    """
    carimbos = {}
    recebido = {}

    def avaliar(executado_em):
        carimbos["avaliacao"] = executado_em
        return _avaliar_persistindo(executado_em)

    def compor(insumo):
        recebido["insumo"] = insumo
        return Relatorio("Leitura.", "teste")

    patches = _patches_daily(compor=compor)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patch(
             "src.strategy.covered.executar_avaliacao_carteira",
             side_effect=avaliar,
         ), \
         patches[6], patches[7], patches[8]:
        resultado = mod.executar_daily(agora=AGORA)

    assert resultado.codigo_saida == 0
    assert carimbos["avaliacao"] == AGORA
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT executado_em FROM desfecho_avaliacao WHERE ticker_objeto = 'ZZOPS'"
        )
        assert cur.fetchone()[0] == AGORA, "o que foi gravado carrega o mesmo instante"

    # E o outro lado da ponte: o agente encontra o que a avaliação gravou.
    assert recebido["insumo"].data == DATA.isoformat()
    assert [s["codigo_opcao"] for s in recebido["insumo"].sugestoes] == ["ZZOPSA1"]


def test_agente_recebe_insumo_persistido_com_vereditos_sem_campos_crus():
    recebido = {}

    def compor(insumo):
        recebido["insumo"] = insumo
        return Relatorio("Leitura.", "teste")

    patches = _patches_daily(compor=compor)
    with patches[0], patches[1], patches[2], patches[3], patches[4], \
         patches[5], patches[6], patches[7], patches[8]:
        resultado = mod.executar_daily(agora=AGORA)

    assert resultado.codigo_saida == 0
    sugestao = recebido["insumo"].sugestoes[0]
    assert sugestao["criterios"][0]["estado"] == "aprovado"
    assert sugestao["criterios"][0]["aprovado"] is True
    assert not ({"iv_rank", "delta", "preco"} & sugestao.keys())

    etapas = [
        item.etapa
        for item in execucao.RepositorioExecucao().tentativas(resultado.execution_id)
    ]
    assert etapas == [
        mod.ETAPA_COTACOES,
        mod.ETAPA_CANDLES_1H,
        mod.ETAPA_CANDLES_1D,
        mod.ETAPA_OPCOES,
        mod.ETAPA_NOTICIAS,
        mod.ETAPA_EARNINGS,
        mod.ETAPA_POLITICA,
        mod.ETAPA_AVALIACAO,
        mod.ETAPA_QUANT,
        mod.ETAPA_RELATORIO,
        mod.ETAPA_AGENTE,
        mod.ETAPA_NOTIFICACAO,
    ]


@pytest.mark.parametrize("condicao", ["ausente", "falha", "orfa"])
def test_alerta_novo_detecta_ausencia_falha_e_orfa_sem_agente(condicao):
    repo = execucao.RepositorioExecucao()
    if condicao != "ausente":
        alvo = repo.adquirir(AMBIENTE, "daily", DATA.isoformat(), "pytest").execucao
        if condicao == "falha":
            repo.finalizar(alvo.execution_id, execucao.FALHOU, erro="falha diária")
        else:
            with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE execucao_pipeline SET heartbeat_em = "
                    "now() - interval '2 hours' WHERE execution_id = %s",
                    (alvo.execution_id,),
                )
                conn.commit()

    calendario = SimpleNamespace(dia_de_pregao=True, motivo="após fechamento")
    with patch("src.pregao.calendario.avaliar", return_value=calendario), \
         patch.object(mod, "_enviar_alerta") as enviar, \
         patch("src.agente.relatorio.compor") as agente:
        resultado = mod.executar_alerta(agora=AGORA)

    assert resultado.codigo_saida == 0
    enviar.assert_called_once()
    esperado = {"ausente": "ausente", "falha": "falhou", "orfa": "órfã"}[condicao]
    assert esperado in enviar.call_args.args[1]
    agente.assert_not_called()


def test_alerta_banco_indisponivel_ainda_usa_canal_independente():
    class RepoIndisponivel:
        def adquirir(self, *args, **kwargs):
            raise OSError("Neon fora do ar")

    with patch.object(mod, "_enviar_alerta") as enviar:
        resultado = mod.executar_alerta(agora=AGORA, repo=RepoIndisponivel())

    assert resultado.codigo_saida == 0
    assert resultado.status == execucao.PARCIAL
    assert "banco indisponível" in enviar.call_args.args[1]
