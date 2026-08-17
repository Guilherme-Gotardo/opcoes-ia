-- 010: estado operacional durável e idempotente para runtimes efêmeros.
--
-- A chave lógica impede duas tarefas de executar a mesma janela. O `id`
-- BIGSERIAL antigo permanece porque API, alerta e scripts locais já o usam;
-- `execution_id` é o identificador estável propagado em logs e artefatos.

ALTER TABLE execucao_pipeline
    ADD COLUMN IF NOT EXISTS execution_id UUID DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS ambiente VARCHAR(30),
    ADD COLUMN IF NOT EXISTS tipo_fluxo VARCHAR(30),
    ADD COLUMN IF NOT EXISTS janela_logica VARCHAR(120),
    ADD COLUMN IF NOT EXISTS heartbeat_em TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS erro_sanitizado TEXT;

-- Linhas da migração 007 não tinham chave lógica. Cada uma recebe uma janela
-- própria, preservando todos os disparos históricos sem criar colisões.
UPDATE execucao_pipeline
SET execution_id = COALESCE(execution_id, gen_random_uuid()),
    ambiente = COALESCE(ambiente, 'legado'),
    tipo_fluxo = COALESCE(tipo_fluxo, 'intraday'),
    janela_logica = COALESCE(janela_logica, 'legacy:' || id::text),
    heartbeat_em = COALESCE(heartbeat_em, iniciado_em)
WHERE execution_id IS NULL
   OR ambiente IS NULL
   OR tipo_fluxo IS NULL
   OR janela_logica IS NULL
   OR heartbeat_em IS NULL;

ALTER TABLE execucao_pipeline
    ALTER COLUMN execution_id SET DEFAULT gen_random_uuid(),
    ALTER COLUMN execution_id SET NOT NULL,
    ALTER COLUMN ambiente SET NOT NULL,
    ALTER COLUMN tipo_fluxo SET NOT NULL,
    ALTER COLUMN janela_logica SET NOT NULL,
    ALTER COLUMN heartbeat_em SET DEFAULT now(),
    ALTER COLUMN heartbeat_em SET NOT NULL;

ALTER TABLE execucao_pipeline
    DROP CONSTRAINT IF EXISTS execucao_pipeline_status_valido;
ALTER TABLE execucao_pipeline
    ADD CONSTRAINT execucao_pipeline_status_valido CHECK (
        status IN (
            'executando', 'executado', 'parcial', 'pulado',
            'pulado_fora_de_pregao', 'falhou', 'orfa'
        )
    );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'execucao_pipeline_execution_id_unico'
          AND conrelid = 'execucao_pipeline'::regclass
    ) THEN
        ALTER TABLE execucao_pipeline
            ADD CONSTRAINT execucao_pipeline_execution_id_unico UNIQUE (execution_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'execucao_pipeline_janela_unica'
          AND conrelid = 'execucao_pipeline'::regclass
    ) THEN
        ALTER TABLE execucao_pipeline
            ADD CONSTRAINT execucao_pipeline_janela_unica
            UNIQUE (ambiente, tipo_fluxo, janela_logica);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_execucao_pipeline_heartbeat
    ON execucao_pipeline (heartbeat_em)
    WHERE status = 'executando';

CREATE TABLE IF NOT EXISTS execucao_etapa_tentativa (
    id                  BIGSERIAL PRIMARY KEY,
    execution_id        UUID NOT NULL,
    etapa               VARCHAR(60) NOT NULL,
    tentativa           INTEGER NOT NULL,
    status              VARCHAR(20) NOT NULL,
    iniciado_em         TIMESTAMPTZ NOT NULL DEFAULT now(),
    encerrado_em        TIMESTAMPTZ,
    alvos_tentados      INTEGER NOT NULL DEFAULT 0,
    alvos_persistidos   INTEGER NOT NULL DEFAULT 0,
    alvos_falhos        INTEGER NOT NULL DEFAULT 0,
    alvos_nao_executados INTEGER NOT NULL DEFAULT 0,
    detalhe             JSONB NOT NULL DEFAULT '{}'::jsonb,
    erro_sanitizado     TEXT,

    CONSTRAINT execucao_etapa_execucao_fk FOREIGN KEY (execution_id)
        REFERENCES execucao_pipeline(execution_id) ON DELETE CASCADE,
    CONSTRAINT execucao_etapa_tentativa_unica
        UNIQUE (execution_id, etapa, tentativa),
    CONSTRAINT execucao_etapa_tentativa_positiva CHECK (tentativa > 0),
    CONSTRAINT execucao_etapa_status_valido CHECK (
        status IN ('executando', 'sucesso', 'parcial', 'falha', 'bloqueado', 'pulado')
    ),
    CONSTRAINT execucao_etapa_contagens_validas CHECK (
        alvos_tentados >= 0 AND alvos_persistidos >= 0
        AND alvos_falhos >= 0 AND alvos_nao_executados >= 0
    ),
    CONSTRAINT execucao_etapa_timestamps_validos CHECK (
        (status = 'executando' AND encerrado_em IS NULL)
        OR (status <> 'executando' AND encerrado_em IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_execucao_etapa_execucao
    ON execucao_etapa_tentativa (execution_id, iniciado_em);

CREATE TABLE IF NOT EXISTS relatorios_deterministicos (
    id              BIGSERIAL PRIMARY KEY,
    execution_id    UUID NOT NULL,
    data            DATE NOT NULL,
    conteudo        TEXT NOT NULL,
    formato         VARCHAR(20) NOT NULL DEFAULT 'markdown',
    gerado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT relatorios_deterministicos_execucao_fk FOREIGN KEY (execution_id)
        REFERENCES execucao_pipeline(execution_id) ON DELETE CASCADE,
    CONSTRAINT relatorios_deterministicos_execucao_unica UNIQUE (execution_id),
    CONSTRAINT relatorios_deterministicos_formato_valido CHECK (formato IN ('markdown'))
);

CREATE INDEX IF NOT EXISTS idx_relatorios_deterministicos_data
    ON relatorios_deterministicos (data DESC, gerado_em DESC);

-- O relatório do agente já existia. O vínculo é opcional para preservar as
-- linhas históricas e o CLI legado; novas execuções hospedadas o preenchem.
ALTER TABLE relatorios_agente
    ADD COLUMN IF NOT EXISTS execution_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relatorios_agente_execucao_fk'
          AND conrelid = 'relatorios_agente'::regclass
    ) THEN
        ALTER TABLE relatorios_agente
            ADD CONSTRAINT relatorios_agente_execucao_fk
            FOREIGN KEY (execution_id) REFERENCES execucao_pipeline(execution_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_relatorios_agente_execucao
    ON relatorios_agente (execution_id)
    WHERE execution_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS notificacoes_relatorio (
    id                  BIGSERIAL PRIMARY KEY,
    execution_id        UUID NOT NULL,
    relatorio_agente_id BIGINT NOT NULL,
    canal               VARCHAR(30) NOT NULL,
    status              VARCHAR(20) NOT NULL,
    reservado_em        TIMESTAMPTZ NOT NULL DEFAULT now(),
    concluido_em        TIMESTAMPTZ,
    detalhe             JSONB NOT NULL DEFAULT '{}'::jsonb,
    erro_sanitizado     TEXT,

    CONSTRAINT notificacoes_relatorio_execucao_fk FOREIGN KEY (execution_id)
        REFERENCES execucao_pipeline(execution_id) ON DELETE CASCADE,
    CONSTRAINT notificacoes_relatorio_agente_fk FOREIGN KEY (relatorio_agente_id)
        REFERENCES relatorios_agente(id) ON DELETE CASCADE,
    CONSTRAINT notificacoes_relatorio_unica UNIQUE (relatorio_agente_id, canal),
    CONSTRAINT notificacoes_relatorio_status_valido CHECK (
        status IN ('reservada', 'enviada', 'falhou')
    ),
    CONSTRAINT notificacoes_relatorio_timestamps_validos CHECK (
        (status = 'reservada' AND concluido_em IS NULL)
        OR (status <> 'reservada' AND concluido_em IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_notificacoes_relatorio_execucao
    ON notificacoes_relatorio (execution_id, reservado_em DESC);

-- `schema.sql` cria as tabelas sem estas FKs para continuar aplicável sobre
-- um banco cuja `execucao_pipeline` ainda não recebeu `execution_id`. Depois
-- do ALTER acima, este bloco torna banco novo e migrado equivalentes.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'execucao_etapa_execucao_fk'
          AND conrelid = 'execucao_etapa_tentativa'::regclass
    ) THEN
        ALTER TABLE execucao_etapa_tentativa
            ADD CONSTRAINT execucao_etapa_execucao_fk FOREIGN KEY (execution_id)
            REFERENCES execucao_pipeline(execution_id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relatorios_deterministicos_execucao_fk'
          AND conrelid = 'relatorios_deterministicos'::regclass
    ) THEN
        ALTER TABLE relatorios_deterministicos
            ADD CONSTRAINT relatorios_deterministicos_execucao_fk
            FOREIGN KEY (execution_id)
            REFERENCES execucao_pipeline(execution_id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'notificacoes_relatorio_execucao_fk'
          AND conrelid = 'notificacoes_relatorio'::regclass
    ) THEN
        ALTER TABLE notificacoes_relatorio
            ADD CONSTRAINT notificacoes_relatorio_execucao_fk
            FOREIGN KEY (execution_id)
            REFERENCES execucao_pipeline(execution_id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'notificacoes_relatorio_agente_fk'
          AND conrelid = 'notificacoes_relatorio'::regclass
    ) THEN
        ALTER TABLE notificacoes_relatorio
            ADD CONSTRAINT notificacoes_relatorio_agente_fk
            FOREIGN KEY (relatorio_agente_id)
            REFERENCES relatorios_agente(id) ON DELETE CASCADE;
    END IF;
END $$;
