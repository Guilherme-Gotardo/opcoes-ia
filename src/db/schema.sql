-- Schema inicial do opcoes-ia
-- Convenção: todo timestamp em UTC; valores monetários em BRL com 4 casas decimais.

CREATE TABLE IF NOT EXISTS ativos (
    ticker          VARCHAR(12) PRIMARY KEY,   -- ex: PETR4
    nome            VARCHAR(120) NOT NULL,
    tipo            VARCHAR(20) NOT NULL,      -- 'acao', 'fii', 'bdr'
    cnpj_raiz       VARCHAR(8),                -- raiz do CNPJ; mapeia o dump da CVM
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Watchlist (migração 006). Vigiar é atributo do cadastro: só se vigia
    -- o que está aqui, e o universo de coleta é CARTEIRA ∪ VIGIADOS.
    -- `vigiado_motivo` guarda por que entrou — a pergunta que aparece
    -- meses depois.
    vigiado         BOOLEAN NOT NULL DEFAULT FALSE,
    vigiado_motivo  TEXT,
    vigiado_desde   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ativos_cnpj_raiz ON ativos (cnpj_raiz);

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
    origem          VARCHAR(30) NOT NULL DEFAULT 'manual', -- 'manual' | 'sincronizacao_b3'

    -- Campos de OPÇÃO (migração 005). NULL em posição de ação.
    -- `ticker_objeto` é informado, não inferido: `ticker` guarda o código
    -- da opção, e derivar o objeto exigiria interpretar código B3 — que
    -- este projeto não faz em lugar nenhum. Sem esta coluna não existe
    -- ligação entre a opção vendida e a ação que a cobre, e a pergunta
    -- central da venda coberta ("a ação passou do strike?") fica sem
    -- resposta.
    ticker_objeto   VARCHAR(12) REFERENCES ativos(ticker),
    strike          NUMERIC(14,4),
    vencimento      DATE,

    -- Desfecho (migração 005). `fechada_em` diz QUANDO fechou, nunca COMO
    -- — e o resultado depende disso: expirada rende o prêmio inteiro,
    -- recomprada rende o prêmio menos a recompra, exercida atravessa duas
    -- categorias fiscais.
    preco_fechamento  NUMERIC(14,4),
    motivo_fechamento VARCHAR(20),

    CONSTRAINT posicoes_motivo_fechamento_valido CHECK (
        motivo_fechamento IS NULL
        OR motivo_fechamento IN ('expirada', 'recomprada', 'exercida', 'encerrada')
    ),
    CONSTRAINT posicoes_fechamento_declarado CHECK (
        fechada_em IS NULL OR motivo_fechamento IS NOT NULL
    )
);

-- O índice de opção por ativo-objeto NÃO fica aqui, e isso é deliberado.
-- `bootstrap` aplica schema.sql ANTES das migrações. Num banco que já tem
-- `posicoes`, o `CREATE TABLE IF NOT EXISTS` acima é pulado inteiro — mas
-- um `CREATE INDEX` solto logo abaixo rodaria e falharia, porque a coluna
-- só passa a existir quando a migração 005 roda, depois. O índice vive lá,
-- e um banco novo o recebe do mesmo jeito (bootstrap aplica os dois).
--
-- Regra geral que isto estabelece: coisa NOVA em tabela ANTIGA vai só na
-- migração. `schema.sql` descreve o estado final da tabela, não comandos
-- avulsos que dependem de colunas recém-criadas.
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

-- Desfecho de cada execução da avaliação de estratégia.
-- Criado originalmente pela migração 003_desfecho_avaliacao.sql; replicado
-- aqui para que um banco novo saia idêntico a um migrado (ver
-- src/db/migrations/README.md). O raciocínio completo está na migração.
--
-- Existe porque só as sugestões elegíveis iam para `sugestoes`: o motivo de
-- cada NÃO-sugestão morria com o processo, e "nenhuma sugestão hoje" ficava
-- indistinguível de "nada valia a pena". Agregado por (execução, ativo,
-- motivo) porque o bloqueio por data de resultado é por ativo — uma linha
-- por opção gravaria centenas de registros para um fato só.
CREATE TABLE IF NOT EXISTS desfecho_avaliacao (
    id                  BIGSERIAL PRIMARY KEY,
    executado_em        TIMESTAMPTZ NOT NULL,   -- agrupa as linhas de uma execução
    ticker_objeto       VARCHAR(12) NOT NULL REFERENCES ativos(ticker),
    motivo              VARCHAR(30) NOT NULL,   -- código fechado, não texto livre
    quantidade          INTEGER NOT NULL,       -- opções que caíram neste motivo
    -- Contagem por critério reprovado. A soma PODE EXCEDER `quantidade`:
    -- opção reprovada em dois critérios conta nos dois.
    criterios_contagem  JSONB,
    amostra             JSONB,                  -- amostra para leitura, não para operar
    criado_em           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_desfecho_execucao
    ON desfecho_avaliacao (executado_em DESC);
CREATE INDEX IF NOT EXISTS idx_desfecho_ticker_motivo
    ON desfecho_avaliacao (ticker_objeto, motivo, executado_em DESC);

-- Candles OHLC por intervalo.
-- Criada originalmente pela migração 004_candles.sql; replicada aqui para
-- que um banco novo saia idêntico a um migrado (ver
-- src/db/migrations/README.md). O raciocínio completo está na migração.
--
-- Separada de `cotacoes` porque são coisas diferentes: `cotacoes` é um
-- preço por instante de coleta (o que a valorização da carteira consome),
-- uma vela é o resumo de um PERÍODO. O `intervalo` é coluna para que 1d,
-- 1h e um futuro 15m convivam sem migração nova.
CREATE TABLE IF NOT EXISTS candles (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(12) NOT NULL REFERENCES ativos(ticker),
    intervalo       VARCHAR(8)  NOT NULL,
    abertura_em     TIMESTAMPTZ NOT NULL,      -- início do período, em UTC
    abertura        NUMERIC(14,4) NOT NULL,
    maxima          NUMERIC(14,4) NOT NULL,
    minima          NUMERIC(14,4) NOT NULL,
    fechamento      NUMERIC(14,4) NOT NULL,
    volume          BIGINT,
    fonte           VARCHAR(30) NOT NULL,
    coletado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT candles_janela_unica UNIQUE (ticker, intervalo, abertura_em),
    -- Um mapeamento trocado no provedor viraria vela de cabeça para baixo;
    -- o banco recusa na hora de gravar.
    CONSTRAINT candles_ohlc_coerente CHECK (
        maxima >= minima
        AND maxima >= abertura AND maxima >= fechamento
        AND minima <= abertura AND minima <= fechamento
    ),
    CONSTRAINT candles_precos_positivos CHECK (
        abertura > 0 AND maxima > 0 AND minima > 0 AND fechamento > 0
    )
);

CREATE INDEX IF NOT EXISTS idx_candles_ticker_intervalo
    ON candles (ticker, intervalo, abertura_em DESC);


-- Lançamentos de caixa/garantia (migração 006).
-- É o que faltava para avaliar PUT coberta contra a carteira real:
-- `avaliar()` exige `caixa_disponivel` — sem garantia para honrar o
-- exercício ao strike, a operação não é coberta.
--
-- Tabela de LANÇAMENTOS, não saldo único: um saldo que se sobrescreve
-- perde a história de como chegou ali, e é a história que explica uma
-- decisão passada. O saldo é a soma.
CREATE TABLE IF NOT EXISTS caixa_lancamentos (
    id              BIGSERIAL PRIMARY KEY,
    valor           NUMERIC(14,2) NOT NULL,   -- + aporte, - retirada
    descricao       TEXT,
    ocorrido_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    registrado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT caixa_valor_nao_zero CHECK (valor <> 0)
);

CREATE INDEX IF NOT EXISTS idx_caixa_ocorrido
    ON caixa_lancamentos (ocorrido_em DESC);

-- Log de execução do pipeline de pregão (migração 007).
-- Criado originalmente pela migração 007_execucao_pipeline.sql; replicado
-- aqui para que um banco novo saia idêntico a um migrado (ver
-- src/db/migrations/README.md). O raciocínio completo está na migração.
--
-- É o único lugar do projeto onde EXECUÇÃO vira estado consultável: cada
-- disparo grava uma linha (executado / pulado_fora_de_pregao / falhou).
-- A linha é aberta antes do trabalho, então `executando` com `encerrado_em`
-- NULL é um processo que morreu no meio — o rastro de "crashou".
CREATE TABLE IF NOT EXISTS execucao_pipeline (
    id              BIGSERIAL PRIMARY KEY,
    execution_id    UUID NOT NULL DEFAULT gen_random_uuid(),
    ambiente        VARCHAR(30) NOT NULL,
    tipo_fluxo      VARCHAR(30) NOT NULL,
    janela_logica   VARCHAR(120) NOT NULL,
    iniciado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    encerrado_em    TIMESTAMPTZ,
    -- 30, não 20: 'pulado_fora_de_pregao' tem 21 caracteres (ver migração).
    status          VARCHAR(30) NOT NULL,
    gatilho         VARCHAR(30) NOT NULL DEFAULT 'manual',
    detalhe         JSONB,
    erro_sanitizado TEXT,

    CONSTRAINT execucao_pipeline_execution_id_unico UNIQUE (execution_id),
    CONSTRAINT execucao_pipeline_janela_unica
        UNIQUE (ambiente, tipo_fluxo, janela_logica),
    CONSTRAINT execucao_pipeline_status_valido CHECK (
        status IN (
            'executando', 'executado', 'parcial', 'pulado',
            'pulado_fora_de_pregao', 'falhou', 'orfa'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_execucao_pipeline_inicio
    ON execucao_pipeline (iniciado_em DESC);

-- Contexto quantitativo por opção avaliada (migração 008).
-- Criado originalmente pela migração 008_enriquecimento_quant.sql; replicado
-- aqui para que um banco novo saia idêntico a um migrado (ver
-- src/db/migrations/README.md). O raciocínio completo está na migração.
--
-- Resumo: é CONTEXTO, não GATE. `criterios_json` guarda o que aprovou ou
-- reprovou; isto guarda números que ajudam a entender e não decidem nada. A
-- chave é a EXECUÇÃO, não a sugestão, porque o contexto é útil justamente
-- na reprovação — e `sugestoes` só recebe as elegíveis.
CREATE TABLE IF NOT EXISTS enriquecimento_quant (
    id                  BIGSERIAL PRIMARY KEY,
    -- Agrupa com `desfecho_avaliacao`: mesmo carimbo, mesma execução.
    executado_em        TIMESTAMPTZ NOT NULL,
    codigo_opcao        VARCHAR(20) NOT NULL,
    ticker_objeto       VARCHAR(12) NOT NULL REFERENCES ativos(ticker),

    -- Gregas do MODELO. Unidades fixadas aqui para não circularem duas
    -- convenções: theta por DIA corrido, vega e rho por PONTO PERCENTUAL.
    delta_modelo        NUMERIC(10,6),
    gamma               NUMERIC(12,8),
    theta_dia           NUMERIC(12,6),
    vega_pp             NUMERIC(12,6),
    rho_pp              NUMERIC(12,6),
    preco_teorico       NUMERIC(14,4),

    -- Probabilidade risco-neutra de terminar dentro do dinheiro NO
    -- VENCIMENTO. Não inclui exercício antecipado — a ressalva
    -- correspondente viaja em `ressalvas` quando o contrato é americano.
    prob_exercicio_vencimento NUMERIC(6,4),
    iv_percentil_252d   NUMERIC(6,4),
    skew_vs_cadeia      NUMERIC(8,4),

    -- Auditoria: sem isto o número não é reconstruível depois.
    modelo              VARCHAR(40) NOT NULL,
    estilo_exercicio    VARCHAR(12),
    taxa_livre_risco    NUMERIC(8,6),
    taxa_observada_em   DATE,
    volatilidade_usada  NUMERIC(8,6),
    -- Por que cada campo nulo está nulo. Lista vazia = tudo calculado.
    ressalvas           JSONB NOT NULL DEFAULT '[]'::jsonb,
    calculado_em        TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Uma linha por opção por execução. Reprocessar a mesma execução
    -- atualiza em vez de duplicar (ON CONFLICT no repositório).
    CONSTRAINT enriquecimento_quant_unico UNIQUE (executado_em, codigo_opcao)
);

-- "O contexto da execução que acabou de rodar" é a consulta da interface e
-- do relatório.
CREATE INDEX IF NOT EXISTS idx_enriquecimento_execucao
    ON enriquecimento_quant (executado_em DESC);

-- "Como esta opção evoluiu" — série histórica de uma opção específica.
CREATE INDEX IF NOT EXISTS idx_enriquecimento_opcao
    ON enriquecimento_quant (codigo_opcao, executado_em DESC);

-- Estado operacional introduzido pela migração 010. As FKs para
-- `execucao_pipeline(execution_id)` são adicionadas pela migração: num banco
-- antigo, schema.sql roda antes do ALTER que cria essa coluna.
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

    CONSTRAINT relatorios_deterministicos_execucao_unica UNIQUE (execution_id),
    CONSTRAINT relatorios_deterministicos_formato_valido CHECK (formato IN ('markdown'))
);

CREATE INDEX IF NOT EXISTS idx_relatorios_deterministicos_data
    ON relatorios_deterministicos (data DESC, gerado_em DESC);

CREATE TABLE IF NOT EXISTS relatorios_agente (
    id              BIGSERIAL PRIMARY KEY,
    execution_id    UUID,
    data            DATE NOT NULL,
    gerado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    texto           TEXT NOT NULL,
    modelo          VARCHAR(40) NOT NULL,
    fontes          JSONB NOT NULL DEFAULT '[]'::jsonb,
    buscas          INTEGER NOT NULL DEFAULT 0,
    tokens_entrada  INTEGER,
    tokens_saida    INTEGER,
    insumo_resumo   JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_relatorios_agente_data
    ON relatorios_agente (data DESC, gerado_em DESC);

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
