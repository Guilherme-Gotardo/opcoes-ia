-- 002 — Fase 2 dos providers de earnings.
-- Aditiva e idempotente. Convenção do projeto: todo timestamp em UTC.

-- (a) CNPJ em `ativos`.
-- O dump IPE da CVM identifica a companhia por CNPJ, nunca por ticker.
-- Sem este mapeamento não há como ligar «PETR4» a «33.000.167/0001-01», e
-- o CvmProvider fica cego. Guardamos só os 8 primeiros dígitos (raiz do
-- CNPJ) normalizados, porque é o que identifica a companhia — filial e
-- dígito verificador variam e atrapalhariam o casamento.
ALTER TABLE ativos ADD COLUMN IF NOT EXISTS cnpj_raiz VARCHAR(8);

CREATE INDEX IF NOT EXISTS idx_ativos_cnpj_raiz ON ativos (cnpj_raiz);

-- (b) Entradas manuais de data de resultado.
--
-- Tabela SEPARADA de `earnings_event_sources` de propósito. As fontes são
-- um log append-only de afirmações — é o rastro de auditoria e não deve
-- ser editado. Já a entrada manual é do usuário: ele erra ao digitar, a
-- empresa remarca, e ele precisa poder corrigir ou apagar. Misturar as
-- duas coisas tornaria impossível corrigir um erro de digitação sem
-- adulterar o histórico.
--
-- O ManualProvider lê daqui e PRODUZ fontes; esta tabela é a origem, não
-- o registro.
CREATE TABLE IF NOT EXISTS earnings_manual_entries (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(12) NOT NULL,
    fiscal_period   VARCHAR(8)  NOT NULL,      -- "2026Q3"
    data_resultado  DATE        NOT NULL,
    hora_resultado  TIME,
    session         VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN',
    origem          TEXT,                      -- de onde o usuário tirou (URL do RI)
    observacao      TEXT,
    registrado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Uma entrada por trimestre por ativo: corrigir é UPDATE, não empilhar
    -- linhas divergentes que depois brigariam entre si na resolução.
    CONSTRAINT earnings_manual_ticker_periodo UNIQUE (ticker, fiscal_period),
    CONSTRAINT earnings_manual_session_valida CHECK (
        session IN ('BEFORE_OPEN', 'DURING_SESSION', 'AFTER_CLOSE', 'UNKNOWN')
    )
);

CREATE INDEX IF NOT EXISTS idx_earnings_manual_ticker
    ON earnings_manual_entries (ticker, data_resultado);
