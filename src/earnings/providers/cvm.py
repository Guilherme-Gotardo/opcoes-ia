"""Provider regulatório: dados abertos da CVM (dump IPE).

O que esta fonte SABE e o que ela NÃO SABE
------------------------------------------
Sabe, com autoridade: que um resultado FOI divulgado, em que data e de
qual trimestre. O `Data_Entrega` de um documento da categoria «Dados
Econômico-Financeiros» é a data efetiva de divulgação — validado em
2026-08-15 contra o yfinance, com casamento exato em PETR4 (06/08),
ITUB4 (04/08) e ABEV3 (30/07).

Não sabe: a agenda FUTURA. O «Calendário de Eventos Corporativos» existe
como categoria, mas o CSV traz só metadados — as datas estão dentro de um
documento servido por um visualizador ASPX. Por isso este provider emite
exclusivamente `RELEASED`, nunca `CONFIRMED` de evento futuro.

PRAZO REGULATÓRIO ≠ DATA EFETIVA
--------------------------------
A CVM define prazos-limite (ITR em 45 dias após o trimestre; DFP em 3
meses após o exercício). Esses prazos NÃO são datas de divulgação: são o
último dia permitido. Uma empresa que divulga em 30/07 e outra que divulga
em 14/08 têm o mesmo prazo regulatório e datas de earnings completamente
diferentes. Este provider usa exclusivamente `Data_Entrega` — o momento em
que o documento efetivamente entrou.

LATÊNCIA CONHECIDA
------------------
O dump é regenerado periodicamente e ficou ~7 dias atrás da realidade na
medição de 2026-08-15 (última entrega no arquivo: 08/08). Consequência:
esta fonte não serve para detectar "divulgou ontem". É evidência
retroativa, e o `retrieved_at` reflete a geração do arquivo — não o
instante do download — para que a penalidade por idade em
`confidence.py` conte a defasagem real.
"""
import csv
import datetime as dt
import io
import logging
import re
import zipfile
from pathlib import Path

import requests

from src.db.connection import get_connection
from src.earnings.models import EarningsEventSource, EarningsStatus
from src.earnings.providers.base import ProviderIndisponivel

log = logging.getLogger(__name__)

URL_IPE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip"

#: Só esta categoria carrega o press-release/relatório de desempenho. Buscar
#: por texto livre em `Assunto` traz ruído — a Petrobras publica «informa
#: sobre resultado do 2º trimestre» como Comunicado ao Mercado semanas antes
#: da divulgação real (era o relatório de produção).
CATEGORIA_RESULTADOS = "Dados Econômico-Financeiros"

#: `Data_Referencia` precisa cair num fim de trimestre. Sem este filtro
#: entra lixo: na medição real, o BBAS3 tinha um «Relatório Credit Opinion
#: Moody's» na mesma categoria, com referência fora de trimestre.
FINS_DE_TRIMESTRE = {(3, 31), (6, 30), (9, 30), (12, 31)}

CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "cvm"
VALIDADE_CACHE_HORAS = 24


def normalizar_cnpj_raiz(cnpj: str | None) -> str | None:
    """Extrai a raiz (8 primeiros dígitos) de um CNPJ em qualquer formato."""
    if not cnpj:
        return None
    digitos = re.sub(r"\D", "", cnpj)
    return digitos[:8] if len(digitos) >= 8 else None


def periodo_de(data_referencia: dt.date) -> str:
    """Trimestre fiscal a partir da data de REFERÊNCIA do documento.

    Aqui não há inferência: a CVM informa explicitamente qual período o
    documento cobre. `2026-06-30` → `2026Q2`.
    """
    return f"{data_referencia.year}Q{(data_referencia.month - 1) // 3 + 1}"


class CvmProvider:
    """Divulgações já ocorridas, conforme o dump IPE da CVM."""

    name = "cvm"

    def __init__(self, cache_dir: Path | None = None, session: requests.Session | None = None):
        self.cache_dir = cache_dir or CACHE_DIR
        self.session = session or requests.Session()

    # ------------------------------------------------------------------
    # Mapeamento CNPJ → ticker
    # ------------------------------------------------------------------
    def _mapa_cnpj_para_tickers(self, tickers: list[str]) -> dict[str, list[str]]:
        """Lê de `ativos.cnpj_raiz`. Ticker sem CNPJ é pulado com aviso.

        Pular em vez de falhar é deliberado: um ativo novo sem CNPJ
        cadastrado não pode derrubar a coleta dos demais. Mas o aviso
        precisa aparecer, porque o efeito silencioso seria "esse ativo
        nunca tem resultado" — indistinguível de cobertura real.
        """
        alvo = [t.upper() for t in tickers]
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, cnpj_raiz FROM ativos WHERE ticker = ANY(%s)",
                (alvo,),
            )
            linhas = cur.fetchall()

        mapa: dict[str, list[str]] = {}
        conhecidos = set()
        for ticker, cnpj_raiz in linhas:
            conhecidos.add(ticker)
            if not cnpj_raiz:
                continue
            mapa.setdefault(cnpj_raiz, []).append(ticker)

        sem_cnpj = sorted(set(alvo) - {t for ts in mapa.values() for t in ts})
        if sem_cnpj:
            log.warning(
                "Sem cnpj_raiz cadastrado em `ativos` (CVM não consegue mapear): %s. "
                'Registre com: python -m src.assets.manage add PETR4 "Petrobras PN" '
                "acao --cnpj-raiz 33000167",
                ", ".join(sem_cnpj),
            )
        return mapa

    # ------------------------------------------------------------------
    # Download e cache do dump
    # ------------------------------------------------------------------
    def _caminho_cache(self, ano: int) -> Path:
        return self.cache_dir / f"ipe_cia_aberta_{ano}.zip"

    def _cache_valido(self, caminho: Path) -> bool:
        if not caminho.exists():
            return False
        idade_h = (dt.datetime.now().timestamp() - caminho.stat().st_mtime) / 3600
        return idade_h < VALIDADE_CACHE_HORAS

    def _baixar(self, ano: int) -> Path:
        """Baixa o zip do ano, reaproveitando o cache local quando fresco.

        O dump tem ~12 MB e é regenerado com dias de intervalo; rebaixar a
        cada execução seria desperdício sem ganho de atualidade.
        """
        caminho = self._caminho_cache(ano)
        if self._cache_valido(caminho):
            log.info("CVM %d: usando cache local.", ano)
            return caminho

        url = URL_IPE.format(ano=ano)
        try:
            resp = self.session.get(url, timeout=120)
            resp.raise_for_status()
        except requests.RequestException as exc:
            if caminho.exists():
                log.warning(
                    "CVM %d: download falhou (%s); usando cache vencido.", ano, exc
                )
                return caminho
            raise ProviderIndisponivel(
                f"não foi possível baixar o dump IPE de {ano}: {exc}"
            ) from exc

        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(resp.content)
        log.info("CVM %d: baixado (%d KB).", ano, len(resp.content) // 1024)
        return caminho

    def _data_de_geracao(self, caminho: Path) -> dt.datetime:
        """Quando a CVM GEROU o dump — não quando nós o baixamos.

        Vem do timestamp da entrada dentro do zip, que o próprio zip
        preserva. O `mtime` do arquivo baixado seria a hora do download e
        faria um dump defasado parecer recém-coletado, anulando a
        penalidade por idade em `confidence.py`.

        Medido em 2026-08-15: o zip de 2026 foi gerado em 2026-08-09 —
        6 dias de defasagem, exatamente a latência que faz esta fonte não
        servir para detectar "divulgou ontem".
        """
        try:
            with zipfile.ZipFile(caminho) as z:
                entrada = next(i for i in z.infolist() if i.filename.endswith(".csv"))
                return dt.datetime(*entrada.date_time, tzinfo=dt.timezone.utc)
        except (zipfile.BadZipFile, StopIteration, ValueError):
            # Sem timestamp legível, o mtime é a melhor aproximação — e
            # erra para o lado otimista, então registramos o aviso.
            log.warning(
                "Não foi possível ler a data de geração de %s; usando mtime.",
                caminho.name,
            )
            return dt.datetime.fromtimestamp(caminho.stat().st_mtime, tz=dt.timezone.utc)

    def _linhas(self, caminho: Path):
        with zipfile.ZipFile(caminho) as z:
            nome_csv = next(n for n in z.namelist() if n.endswith(".csv"))
            with z.open(nome_csv) as bruto:
                texto = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
                yield from csv.DictReader(texto, delimiter=";")

    # ------------------------------------------------------------------
    # Extração
    # ------------------------------------------------------------------
    def _extrair(
        self,
        anos: list[int],
        mapa_cnpj: dict[str, list[str]],
        desde: dt.date | None,
        ate: dt.date | None,
    ) -> list[EarningsEventSource]:
        # Uma companhia entrega vários documentos no mesmo dia (DFs
        # completas, análise gerencial, press-release). Todos representam a
        # MESMA divulgação — deduplicamos por (ticker, período), guardando
        # a entrega mais antiga, que é o instante em que o mercado soube.
        melhor: dict[tuple[str, str], tuple[dt.date, dt.datetime]] = {}

        for ano in anos:
            caminho = self._baixar(ano)
            gerado_em = self._data_de_geracao(caminho)

            for linha in self._linhas(caminho):
                if linha.get("Categoria") != CATEGORIA_RESULTADOS:
                    continue
                raiz = normalizar_cnpj_raiz(linha.get("CNPJ_Companhia"))
                if raiz not in mapa_cnpj:
                    continue
                try:
                    referencia = dt.date.fromisoformat(linha["Data_Referencia"])
                    entrega = dt.date.fromisoformat(linha["Data_Entrega"])
                except (ValueError, KeyError, TypeError):
                    continue
                if (referencia.month, referencia.day) not in FINS_DE_TRIMESTRE:
                    continue
                if desde and entrega < desde:
                    continue
                if ate and entrega > ate:
                    continue

                periodo = periodo_de(referencia)
                for ticker in mapa_cnpj[raiz]:
                    chave = (ticker, periodo)
                    atual = melhor.get(chave)
                    if atual is None or entrega < atual[0]:
                        melhor[chave] = (entrega, gerado_em)

        return [
            EarningsEventSource(
                ticker=ticker,
                provider=self.name,
                date=entrega,
                fiscal_period=periodo,
                # A CVM confirma que saiu, nunca que vai sair.
                status=EarningsStatus.RELEASED,
                # `Data_Entrega` é uma data sem hora no CSV — não inventamos
                # sessão a partir dela. Fica UNKNOWN, o que AMPLIA a janela
                # de risco em vez de estreitá-la.
                session=None,
                source_url="https://dados.cvm.gov.br/dataset/cia_aberta-doc-ipe",
                retrieved_at=gerado_em,
                confidence=100,
            )
            for (ticker, periodo), (entrega, gerado_em) in sorted(melhor.items())
        ]

    # ------------------------------------------------------------------
    # Contrato EarningsProvider
    # ------------------------------------------------------------------
    def get_upcoming_earnings(self, tickers: list[str]) -> list[EarningsEventSource]:
        """Sempre vazio, por construção.

        A CVM não publica agenda futura em formato estruturado. Retornar
        vazio é a resposta honesta — inventar uma data a partir do prazo
        regulatório seria fabricar o dado que este serviço existe para
        proteger.
        """
        log.info(
            "CvmProvider não fornece agenda futura (só divulgações ocorridas); "
            "use get_historical_earnings."
        )
        return []

    def get_historical_earnings(
        self, ticker: str, start: dt.date, end: dt.date
    ) -> list[EarningsEventSource]:
        return self.coletar_divulgacoes([ticker], start, end)

    def coletar_divulgacoes(
        self, tickers: list[str], start: dt.date, end: dt.date
    ) -> list[EarningsEventSource]:
        """Divulgações ocorridas no intervalo, para os tickers pedidos.

        Varre os anos cobertos pelo intervalo: o calendário e os documentos
        de um ano aparecem tanto no dump do próprio ano quanto no anterior.
        """
        mapa = self._mapa_cnpj_para_tickers(tickers)
        if not mapa:
            log.warning("Nenhum ticker com cnpj_raiz cadastrado; CVM não tem o que buscar.")
            return []
        anos = sorted({start.year, end.year})
        return self._extrair(anos, mapa, desde=start, ate=end)
