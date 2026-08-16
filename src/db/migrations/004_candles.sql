-- 004: candles OHLC por intervalo.
--
-- POR QUE UMA TABELA NOVA, E NÃO COLUNAS EM `cotacoes`
-- ---------------------------------------------------
-- `cotacoes` guarda UM preço por coleta — o último negócio no instante em
-- que o ETL rodou. É a resposta para "quanto vale agora", e é o que a
-- valorização da carteira consome. Uma vela é outra coisa: um resumo de um
-- PERÍODO (abertura, máxima, mínima, fechamento). Enfiar OHLC em `cotacoes`
-- obrigaria toda linha existente a ter quatro colunas nulas e faria
-- `MAX(coletado_em)` — usado pela valorização e pelo painel de operação —
-- passar a competir com linhas de granularidade diferente.
--
-- O INTERVALO É COLUNA, NÃO TABELA
-- --------------------------------
-- Guardar `intervalo` por linha é o que permite conviverem 1d e 1h hoje e
-- 15m amanhã sem migração nova: quem consome pede o intervalo que quer, e a
-- interface desenha o que vier. Um intervalo por tabela travaria isso.
--
-- A JANELA É IDENTIDADE
-- ---------------------
-- `abertura_em` é o INÍCIO do período, não o momento da coleta. É o que
-- torna a vela idempotente: recoletar o mesmo período atualiza a linha em
-- vez de duplicar — necessário porque máxima, mínima e fechamento mudam
-- enquanto o período ainda está aberto.

CREATE TABLE IF NOT EXISTS candles (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(12) NOT NULL REFERENCES ativos(ticker),
    intervalo       VARCHAR(8)  NOT NULL,      -- '1h', '1d', '15m'...
    abertura_em     TIMESTAMPTZ NOT NULL,      -- início do período, em UTC
    abertura        NUMERIC(14,4) NOT NULL,
    maxima          NUMERIC(14,4) NOT NULL,
    minima          NUMERIC(14,4) NOT NULL,
    fechamento      NUMERIC(14,4) NOT NULL,
    volume          BIGINT,
    fonte           VARCHAR(30) NOT NULL,
    coletado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT candles_janela_unica UNIQUE (ticker, intervalo, abertura_em),

    -- Invariante de OHLC: a máxima é o teto do período e a mínima o piso.
    -- Não é preciosismo — um mapeamento trocado no provedor (já aconteceu
    -- neste projeto com `fetch_quotes` em 2026-08-14) passaria despercebido
    -- e só apareceria como vela desenhada de cabeça para baixo meses
    -- depois. Aqui o banco recusa na hora de gravar.
    CONSTRAINT candles_ohlc_coerente CHECK (
        maxima >= minima
        AND maxima >= abertura AND maxima >= fechamento
        AND minima <= abertura AND minima <= fechamento
    ),
    CONSTRAINT candles_precos_positivos CHECK (
        abertura > 0 AND maxima > 0 AND minima > 0 AND fechamento > 0
    )
);

-- A consulta do gráfico é sempre "as N velas mais recentes deste ticker
-- neste intervalo".
CREATE INDEX IF NOT EXISTS idx_candles_ticker_intervalo
    ON candles (ticker, intervalo, abertura_em DESC);
