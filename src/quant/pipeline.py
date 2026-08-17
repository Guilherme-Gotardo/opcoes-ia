"""Junta os insumos do banco, chama o enriquecimento e persiste.

Esta é a camada COM I/O. `enrichment.py` continua puro de propósito: a conta
é testável sem banco, e o que depende de banco (histórico de IV, cadeia,
taxa vigente) fica aqui, onde pode ser lido de uma vez.

ENRIQUECIMENTO É OPCIONAL POR CONSTRUÇÃO
----------------------------------------
Nada aqui pode derrubar a avaliação. Sem QuantLib, sem taxa, sem opções —
o pipeline determinístico roda igual e o contexto simplesmente não sai, com
o motivo escrito na linha. É o que mantém a garantia central do plano: o
motor de decisão não passou a depender do modelo.

A TAXA, E POR QUE HÁ FALLBACK
-----------------------------
`taxa_vigente` busca no BCB e, se a rede falhar, reusa a última taxa já
gravada em `enriquecimento_quant` — com a idade declarada numa ressalva. Não
é cache escondido: a taxa que foi usada fica em cada linha, então "de quando
era a taxa" é sempre respondível. Uma Selic de três dias atrás muda o preço
teórico na quarta casa; ficar sem contexto por um timeout de rede custa mais.
"""
import datetime as dt
import json
import logging
from dataclasses import replace
from typing import Any, Sequence

from src.quant.enrichment import (
    Enriquecimento,
    ModeloIndisponivel,
    carregar_modelo,
    enriquecer,
)
from src.quant.taxa import TaxaLivreRisco, buscar as buscar_taxa

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

#: Janela do percentil de IV. 252 é o número de pregões num ano — a mesma
#: convenção da base 252 da Selic anualizada.
JANELA_PERCENTIL_DIAS = 252

#: A partir de quantos dias a taxa reaproveitada merece ressalva. A Selic só
#: muda em reunião do Copom (a cada ~45 dias), então uma taxa de ontem é a
#: mesma de hoje; uma de duas semanas pode ter atravessado uma decisão.
_IDADE_TAXA_TOLERADA_DIAS = 7


def _ultima_taxa_gravada(cur) -> TaxaLivreRisco | None:
    cur.execute(
        "SELECT taxa_livre_risco, taxa_observada_em FROM enriquecimento_quant "
        "WHERE taxa_livre_risco IS NOT NULL AND taxa_observada_em IS NOT NULL "
        "ORDER BY taxa_observada_em DESC LIMIT 1"
    )
    linha = cur.fetchone()
    if not linha:
        return None
    return TaxaLivreRisco(
        valor_aa=float(linha[0]), observada_em=linha[1],
        fonte="reaproveitada de enriquecimento_quant",
    )


def taxa_vigente(cur, hoje: dt.date | None = None) -> tuple[TaxaLivreRisco | None, list[str]]:
    """Taxa a usar agora, e as ressalvas que ela carrega."""
    hoje = hoje or dt.date.today()
    taxa = buscar_taxa()
    ressalvas: list[str] = []

    if taxa is None:
        taxa = _ultima_taxa_gravada(cur)
        if taxa is None:
            return None, ["taxa livre de risco indisponível: BCB fora do ar e "
                          "nenhuma taxa gravada anteriormente"]
        ressalvas.append(
            f"BCB indisponível; taxa reaproveitada de "
            f"{taxa.observada_em.isoformat()}"
        )

    idade = taxa.idade_em_dias(hoje)
    if idade > _IDADE_TAXA_TOLERADA_DIAS:
        ressalvas.append(
            f"taxa livre de risco observada há {idade} dias "
            f"({taxa.observada_em.isoformat()}) — pode ter atravessado uma "
            "reunião do Copom"
        )
    return taxa, ressalvas


def _dados_da_opcao(cur, codigo: str) -> dict[str, Any] | None:
    """Tipo, vencimento e IV da coleta mais recente da opção.

    `ResultadoAvaliacao` não carrega IV nem tipo do contrato — ele carrega o
    que o CRITÉRIO precisou. Buscar aqui evita alargar a estrutura de
    decisão para servir a uma camada de contexto.
    """
    cur.execute(
        "SELECT tipo, vencimento, volatilidade_implicita FROM opcoes "
        "WHERE codigo = %s ORDER BY coletado_em DESC LIMIT 1",
        (codigo,),
    )
    linha = cur.fetchone()
    if not linha:
        return None
    tipo, vencimento, iv = linha
    return {
        "tipo": tipo,
        "vencimento": vencimento,
        "volatilidade_implicita": float(iv) if iv is not None else None,
    }


def _ivs_historicas(cur, ticker: str, hoje: dt.date) -> list[float]:
    """IVs coletadas do ativo na janela do percentil.

    Uma IV por dia por opção — a distribuição é do ATIVO, não de uma série
    específica, porque é assim que "IV alta para este papel" se lê.
    """
    cur.execute(
        "SELECT volatilidade_implicita FROM opcoes "
        "WHERE ticker_objeto = %s AND volatilidade_implicita IS NOT NULL "
        "AND coletado_em >= %s",
        (ticker, hoje - dt.timedelta(days=JANELA_PERCENTIL_DIAS)),
    )
    return [float(v[0]) for v in cur.fetchall()]


def _ivs_da_cadeia(cur, ticker: str, vencimento, excluir_codigo: str) -> list[float]:
    """IVs das OUTRAS opções do mesmo ativo e vencimento, coleta mais recente.

    Exclui a própria opção: incluí-la puxaria a média na direção dela e
    subestimaria o skew — a comparação é contra as vizinhas.
    """
    cur.execute(
        """
        SELECT DISTINCT ON (codigo) volatilidade_implicita
        FROM opcoes
        WHERE ticker_objeto = %s AND vencimento = %s AND codigo <> %s
          AND volatilidade_implicita IS NOT NULL
        ORDER BY codigo, coletado_em DESC
        """,
        (ticker, vencimento, excluir_codigo),
    )
    return [float(v[0]) for v in cur.fetchall()]


def gravar(cur, executado_em: dt.datetime, ticker: str, codigo: str,
           enr: Enriquecimento) -> None:
    """Persiste uma linha. Reprocessar a mesma execução atualiza, não duplica."""
    cur.execute(
        """
        INSERT INTO enriquecimento_quant (
            executado_em, codigo_opcao, ticker_objeto,
            delta_modelo, gamma, theta_dia, vega_pp, rho_pp, preco_teorico,
            prob_exercicio_vencimento, iv_percentil_252d, skew_vs_cadeia,
            modelo, estilo_exercicio, taxa_livre_risco, taxa_observada_em,
            volatilidade_usada, ressalvas, calculado_em
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (executado_em, codigo_opcao) DO UPDATE SET
            delta_modelo = EXCLUDED.delta_modelo,
            gamma = EXCLUDED.gamma,
            theta_dia = EXCLUDED.theta_dia,
            vega_pp = EXCLUDED.vega_pp,
            rho_pp = EXCLUDED.rho_pp,
            preco_teorico = EXCLUDED.preco_teorico,
            prob_exercicio_vencimento = EXCLUDED.prob_exercicio_vencimento,
            iv_percentil_252d = EXCLUDED.iv_percentil_252d,
            skew_vs_cadeia = EXCLUDED.skew_vs_cadeia,
            modelo = EXCLUDED.modelo,
            estilo_exercicio = EXCLUDED.estilo_exercicio,
            taxa_livre_risco = EXCLUDED.taxa_livre_risco,
            taxa_observada_em = EXCLUDED.taxa_observada_em,
            volatilidade_usada = EXCLUDED.volatilidade_usada,
            ressalvas = EXCLUDED.ressalvas,
            calculado_em = EXCLUDED.calculado_em
        """,
        (
            executado_em, codigo, ticker,
            enr.delta_modelo, enr.gamma, enr.theta_dia, enr.vega_pp, enr.rho_pp,
            enr.preco_teorico, enr.prob_exercicio_vencimento,
            enr.iv_percentil_252d, enr.skew_vs_cadeia,
            enr.modelo, enr.estilo_exercicio, enr.taxa_livre_risco,
            enr.taxa_observada_em, enr.volatilidade_usada,
            json.dumps(list(enr.ressalvas), ensure_ascii=False),
            enr.calculado_em,
        ),
    )


def enriquecer_avaliacoes(cur, executado_em: dt.datetime, resultados: Sequence) -> int:
    """Enriquece toda opção avaliada e grava. Devolve quantas linhas gravou.

    TODA opção, elegível ou não: o contexto é justamente o que mostra quão
    perto uma reprovada estava, e restringir às sugestões apagaria essa
    leitura.

    Nunca levanta. Uma falha aqui não pode invalidar a avaliação, que é
    determinística e já terminou quando esta função é chamada.
    """
    if not resultados:
        return 0

    try:
        params = carregar_modelo()
    except Exception as e:  # noqa: BLE001 — configuração ruim não derruba avaliação
        log.warning("Enriquecimento pulado: modelo.yaml inválido (%s)", e)
        return 0

    hoje = executado_em.date()
    taxa, ressalvas_taxa = taxa_vigente(cur, hoje)
    gravadas = 0

    for r in resultados:
        codigo = getattr(r, "codigo_opcao", None)
        if not codigo:
            continue
        try:
            dados = _dados_da_opcao(cur, codigo)
            if dados is None:
                # A opção foi avaliada mas não está em `opcoes` — só acontece
                # com entrada sintética. Grava a linha mesmo assim: "não deu
                # para enriquecer, e por quê" é informação.
                enr = Enriquecimento(
                    modelo="indisponivel", calculado_em=executado_em,
                    ressalvas=(*ressalvas_taxa,
                               f"opção {codigo} não encontrada em `opcoes`"),
                )
            else:
                vencimento = dados["vencimento"]
                dias = (vencimento - hoje).days if vencimento else None
                enr = enriquecer(
                    tipo=dados["tipo"] or "CALL",
                    preco_objeto=getattr(r, "preco_mercado", None),
                    strike=getattr(r, "strike", None),
                    dias_vencimento=dias,
                    volatilidade_implicita=dados["volatilidade_implicita"],
                    taxa=taxa,
                    ivs_historicas=_ivs_historicas(cur, r.ticker_objeto, hoje),
                    ivs_da_cadeia=(
                        _ivs_da_cadeia(cur, r.ticker_objeto, vencimento, codigo)
                        if vencimento else []
                    ),
                    params=params,
                    agora=executado_em,
                )
                if ressalvas_taxa:
                    # As ressalvas da taxa valem para TODA opção da execução,
                    # e vêm primeiro: são sobre o insumo, não sobre a conta.
                    enr = replace(enr, ressalvas=(*ressalvas_taxa, *enr.ressalvas))
            gravar(cur, executado_em, r.ticker_objeto, codigo, enr)
            gravadas += 1
        except ModeloIndisponivel as e:
            # Uma vez basta: sem QuantLib nenhuma opção vai enriquecer.
            log.warning("Enriquecimento indisponível: %s", e)
            return gravadas
        except Exception:  # noqa: BLE001
            log.exception("Falha ao enriquecer %s — seguindo com as demais", codigo)

    if gravadas:
        log.info(
            "Enriquecimento quantitativo: %d opção(ões) contextualizada(s)%s",
            gravadas,
            f" (ressalvas de taxa: {'; '.join(ressalvas_taxa)})" if ressalvas_taxa else "",
        )
    return gravadas


def enriquecer_execucao(executado_em: dt.datetime, resultados: Sequence) -> int:
    """Enriquece uma execução em TRANSAÇÃO PRÓPRIA, depois do commit da
    avaliação.

    A transação separada não é detalhe de arrumação — é o que impede o
    contexto de derrubar a decisão. Se estas linhas fossem gravadas junto das
    sugestões, um erro de banco aqui (a tabela não existir, por exemplo,
    porque a migração 008 não foi aplicada) abortaria a transação inteira, e
    o `commit` seguinte levaria embora sugestões e desfecho já calculados.
    Enriquecimento é opcional; avaliação não é.
    """
    from src.db.connection import get_connection  # noqa: PLC0415 — só aqui

    if not resultados:
        return 0
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.enriquecimento_quant')")
            if cur.fetchone()[0] is None:
                log.warning(
                    "Enriquecimento pulado: tabela `enriquecimento_quant` não "
                    "existe neste banco (aplique a migração 008 com "
                    "`python -m src.db.bootstrap`)."
                )
                return 0
            gravadas = enriquecer_avaliacoes(cur, executado_em, resultados)
            conn.commit()
            return gravadas
    except Exception:  # noqa: BLE001 — nunca derruba a avaliação
        log.exception("Enriquecimento quantitativo falhou por inteiro.")
        return 0
