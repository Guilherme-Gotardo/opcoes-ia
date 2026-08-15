-- Schema inicial do opcoes-ia
-- Convenção: todo timestamp em UTC; valores monetários em BRL com 4 casas decimais.

CREATE TABLE IF NOT EXISTS ativos (
    ticker          VARCHAR(12) PRIMARY KEY,   -- ex: PETR4
    nome            VARCHAR(120) NOT NULL,
    tipo            VARCHAR(20) NOT NULL,      -- 'acao', 'fii', 'bdr'
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cotacoes (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(12) NOT NULL REFERENCES ativos(ticker),
    preco           NUMERIC(14,4) NOT NULL,
    volume          BIGINT,
    coletado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    fonte           VARCHAR(30) NOT NULL       -- ex: 'oplab', 'brapi'
);
CREATE INDEX IF NOT EXISTS idx_cotacoes_ticker_data ON cotacoes (ticker, coletado_em DESC);

CREATE TABLE IF NOT EXISTS opcoes (
    id                  BIGSERIAL PRIMARY KEY,
    codigo              VARCHAR(20) NOT NULL,      -- ex: PETRJ380
    ticker_objeto       VARCHAR(12) NOT NULL REFERENCES ativos(ticker),
    tipo                VARCHAR(4) NOT NULL,       -- 'CALL' | 'PUT'
    strike              NUMERIC(14,4) NOT NULL,
    vencimento          DATE NOT NULL,
    preco               NUMERIC(14,4),
    delta               NUMERIC(6,4),
    gamma               NUMERIC(8,6),
    theta               NUMERIC(8,4),
    vega                NUMERIC(8,4),
    rho                 NUMERIC(8,4),
    volatilidade_implicita NUMERIC(6,4),
    iv_rank             NUMERIC(5,2),
    coletado_em         TIMESTAMPTZ NOT NULL DEFAULT now(),
    fonte               VARCHAR(30) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opcoes_codigo_data ON opcoes (codigo, coletado_em DESC);
CREATE INDEX IF NOT EXISTS idx_opcoes_objeto ON opcoes (ticker_objeto, vencimento);

-- "Estoque de patrimônio": posições atuais do usuário (espelho, não corretora real)
CREATE TABLE IF NOT EXISTS posicoes (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(12) NOT NULL,      -- ação ou código da opção
    tipo_ativo      VARCHAR(10) NOT NULL,      -- 'ACAO' | 'OPCAO'
    quantidade      INTEGER NOT NULL,          -- negativo = posição vendida (opção)
    preco_medio     NUMERIC(14,4) NOT NULL,
    aberta_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    fechada_em      TIMESTAMPTZ,               -- NULL = posição em aberto
    origem          VARCHAR(30) NOT NULL DEFAULT 'manual' -- 'manual' | 'sincronizacao_b3'
);
CREATE INDEX IF NOT EXISTS idx_posicoes_abertas ON posicoes (ticker) WHERE fechada_em IS NULL;

CREATE TABLE IF NOT EXISTS noticias (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(12) REFERENCES ativos(ticker),
    titulo          TEXT NOT NULL,
    resumo          TEXT,                      -- sempre resumo próprio, nunca texto copiado da fonte
    url             TEXT,
    publicado_em    TIMESTAMPTZ,
    coletado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    fonte           VARCHAR(60) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_noticias_ticker_data ON noticias (ticker, publicado_em DESC);

-- Log de sugestões geradas pelos agentes (nunca execuções reais)
CREATE TABLE IF NOT EXISTS sugestoes (
    id                  BIGSERIAL PRIMARY KEY,
    ticker_objeto       VARCHAR(12) NOT NULL,
    tipo_operacao       VARCHAR(30) NOT NULL,   -- 'covered_call', 'covered_put', ...
    codigo_opcao        VARCHAR(20),
    strike              NUMERIC(14,4),
    vencimento          DATE,
    premio_estimado     NUMERIC(14,4),
    criterios_json       JSONB NOT NULL,         -- snapshot dos critérios avaliados
    gerado_em           TIMESTAMPTZ NOT NULL DEFAULT now(),
    status              VARCHAR(20) NOT NULL DEFAULT 'pendente' -- 'pendente'|'aceita'|'descartada'
);

-- Eventos de resultado (Earnings Event Service).
-- Criados originalmente pela migração 001_earnings_events.sql; replicados aqui
-- para que um banco novo saia idêntico a um migrado (ver src/db/migrations/README.md).
CREATE TABLE IF NOT EXISTS earnings_events (
    id                  VARCHAR(32) PRIMARY KEY,      -- "PETR4:2026Q2"
    ticker              VARCHAR(12) NOT NULL,
    fiscal_period       VARCHAR(8)  NOT NULL,         -- "2026Q2"
    company_name        VARCHAR(120),

    -- Estimada e confirmada são colunas SEPARADAS de propósito: manter a
    -- estimativa depois de haver confirmação preserva a discordância em
    -- vez de apagá-la.
    expected_date       DATE,
    confirmed_date      DATE,
    expected_time       TIME,
    confirmed_time      TIME,

    session             VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN',
    status              VARCHAR(16) NOT NULL,
    confidence          SMALLINT    NOT NULL,
    conflicts           JSONB       NOT NULL DEFAULT '[]'::jsonb,

    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT earnings_events_ticker_periodo UNIQUE (ticker, fiscal_period),
    CONSTRAINT earnings_events_confidence_faixa CHECK (confidence BETWEEN 0 AND 100),
    CONSTRAINT earnings_events_status_valido CHECK (
        status IN ('ESTIMATED', 'CONFIRMED', 'RELEASED', 'RESCHEDULED')
    ),
    CONSTRAINT earnings_events_session_valida CHECK (
        session IN ('BEFORE_OPEN', 'DURING_SESSION', 'AFTER_CLOSE', 'UNKNOWN')
    )
);

CREATE INDEX IF NOT EXISTS idx_earnings_events_ticker
    ON earnings_events (ticker);

-- Busca "próximo resultado do ativo": a data que vale é a confirmada
-- quando existe, senão a estimada.
CREATE INDEX IF NOT EXISTS idx_earnings_events_data_efetiva
    ON earnings_events (ticker, COALESCE(confirmed_date, expected_date));

-- O que cada fonte afirmou, preservado como veio. Linhas perdedoras de um
-- conflito FICAM: são o rastro que responde "por que o sistema achava
-- isso?" meses depois.
CREATE TABLE IF NOT EXISTS earnings_event_sources (
    id                  BIGSERIAL PRIMARY KEY,
    event_id            VARCHAR(32) NOT NULL
                            REFERENCES earnings_events(id) ON DELETE CASCADE,
    provider            VARCHAR(40) NOT NULL,
    reported_date       DATE,
    reported_time       TIME,
    status              VARCHAR(16),
    session             VARCHAR(16),
    fiscal_period       VARCHAR(8),
    source_url          TEXT,
    confidence          SMALLINT    NOT NULL,
    retrieved_at        TIMESTAMPTZ NOT NULL,

    CONSTRAINT earnings_sources_confidence_faixa CHECK (confidence BETWEEN 0 AND 100),
    CONSTRAINT earnings_sources_status_valido CHECK (
        status IS NULL OR status IN ('ESTIMATED', 'CONFIRMED', 'RELEASED', 'RESCHEDULED')
    ),
    -- A mesma fonte, para o mesmo evento, afirmando a mesma data no mesmo
    -- instante é uma reingestão — não uma segunda opinião.
    CONSTRAINT earnings_sources_sem_duplicata UNIQUE (event_id, provider, retrieved_at)
);

CREATE INDEX IF NOT EXISTS idx_earnings_sources_evento
    ON earnings_event_sources (event_id, retrieved_at DESC);
