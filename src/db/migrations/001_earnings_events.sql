-- 001 — Earnings Event Service: eventos de resultado e suas fontes.
-- Aditiva e idempotente: aplicável sobre o banco pessoal existente sem
-- recriar nada. Convenção do projeto: todo timestamp em UTC.

-- Um evento por trimestre fiscal por ativo. A identidade natural é
-- (ticker, fiscal_period) — é isso que impede que a mesma divulgação vire
-- duas linhas quando duas fontes discordam da data.
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
