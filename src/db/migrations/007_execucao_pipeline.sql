-- 007: log auditável de cada disparo do pipeline de pregão.
--
-- POR QUE ESTA TABELA EXISTE
-- --------------------------
-- Até aqui NADA no projeto registrava execução: `/operacao` deriva saúde
-- dos carimbos de coleta e declara `rastreia_falhas: false`, e o journald
-- do systemd guarda stdout, não estado consultável. Sem esta tabela,
-- "o pipeline rodou hoje?" não tem resposta no banco — e "pulou porque não
-- era pregão" fica indistinguível de "falhou em silêncio". É o pré-
-- requisito da observabilidade (Fase 5 do plano de automação): não existe
-- alerta de falha sem um lugar onde a falha esteja escrita.
--
-- Uma linha por DISPARO, não por etapa: o que se audita é "o gatilho
-- disparou, e no que deu". O detalhe por etapa (cotação, avaliação) vai em
-- `detalhe` JSONB — consultável, sem virar schema rígido que cada etapa
-- nova obrigaria a migrar.
--
-- `status = 'executando'` é informação, não lixo: a linha é aberta ANTES
-- do trabalho e commitada na hora, então um processo que morre no meio
-- deixa a linha aberta — que é exatamente o rastro de "crashou". Um
-- INSERT só no final não registraria esse caso.

CREATE TABLE IF NOT EXISTS execucao_pipeline (
    id              BIGSERIAL PRIMARY KEY,
    iniciado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    encerrado_em    TIMESTAMPTZ,                -- NULL = morreu no meio
    -- 30, não 20: 'pulado_fora_de_pregao' tem 21 caracteres. Com VARCHAR(20)
    -- o CHECK abaixo listava um valor que o tipo não comporta, e TODO pulo
    -- por fora-de-pregão — o caminho mais percorrido, já que a maior parte
    -- das horas do ano não é pregão — estourava StringDataRightTruncation.
    status          VARCHAR(30) NOT NULL,
    gatilho         VARCHAR(30) NOT NULL DEFAULT 'manual', -- 'systemd' | 'manual'
    detalhe         JSONB,  -- resumo por etapa; erro+traceback quando falhou

    CONSTRAINT execucao_pipeline_status_valido CHECK (
        status IN ('executando', 'executado', 'pulado_fora_de_pregao', 'falhou')
    )
);

-- Correção de largura para bancos que chegaram a receber a versão anterior
-- desta migração (status VARCHAR(20)). Alargar é aditivo — nenhum valor
-- existente cabe menos depois —, e `CREATE TABLE IF NOT EXISTS` sozinho não
-- alcança uma tabela que já existe, o que deixaria a correção valendo só
-- para banco novo. Rodar de novo num banco já corrigido é inofensivo.
ALTER TABLE execucao_pipeline ALTER COLUMN status TYPE VARCHAR(30);

CREATE INDEX IF NOT EXISTS idx_execucao_pipeline_inicio
    ON execucao_pipeline (iniciado_em DESC);
