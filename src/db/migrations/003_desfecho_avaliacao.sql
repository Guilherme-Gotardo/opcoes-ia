-- 003 — Desfecho de cada execução da avaliação de estratégia.
-- Aditiva e idempotente. Convenção do projeto: todo timestamp em UTC.
--
-- POR QUE ESTA TABELA EXISTE
-- A avaliação sabe exatamente por que não sugeriu nada — e jogava fora.
-- `executar_avaliacao_carteira()` produz um resultado por par posição×opção
-- com o veredito de cada critério, mas só as elegíveis iam para `sugestoes`.
-- O resto vivia em memória e morria com o processo; o relatório só enxergava
-- porque recebia por argumento, no mesmo processo. Qualquer outro consumidor
-- — a interface web, uma comparação entre dias — ficava sem nada, e
-- "nenhuma sugestão hoje" virava um silêncio indistinguível de "nada valia a
-- pena".
--
-- POR QUE AGREGADA, E NÃO UMA LINHA POR OPÇÃO
-- O bloqueio por data de resultado é por ATIVO: se falta a data da PETR4,
-- todas as opções dela caem no mesmo motivo. Com uma cadeia real de 100+
-- séries, uma linha por opção gravaria ~100 registros idênticos exceto pelo
-- código da opção, para expressar um fato só. Aqui o volume acompanha a
-- informação, não o tamanho da cadeia.
--
-- POR QUE NÃO EM `sugestoes`
-- Uma avaliação bloqueada não é uma sugestão. Além da semântica, o requisito
-- "Nenhuma execução automática" exige que toda sugestão persistida permaneça
-- `pendente` — criar um status `bloqueada` ali forçaria reinterpretar esse
-- requisito para acomodar algo que não é sugestão.

CREATE TABLE IF NOT EXISTS desfecho_avaliacao (
    id                  BIGSERIAL PRIMARY KEY,

    -- Mesmo timestamp para todas as linhas de uma execução: é o que agrupa
    -- o desfecho e o que distingue duas execuções no mesmo dia.
    executado_em        TIMESTAMPTZ NOT NULL,

    ticker_objeto       VARCHAR(12) NOT NULL REFERENCES ativos(ticker),

    -- Conjunto fechado, derivado do que a avaliação já distingue:
    --   'sugerida'                 — passou em todos os critérios
    --   'bloqueio_data_resultado'  — critérios de mercado ok, data não verificável
    --   'criterio_reprovado'       — reprovada contra um valor real
    --   'dado_insuficiente'        — faltou dado para avaliar
    --   'pre_requisito'            — lote ou caixa insuficiente
    --   'sem_opcoes'               — nada a avaliar para o ativo
    -- Código, não a frase de `motivo_nao_elegivel`: agrupar por texto livre
    -- quebraria no primeiro ajuste de redação.
    motivo              VARCHAR(30) NOT NULL,

    -- Quantas opções caíram neste motivo nesta execução.
    quantidade          INTEGER NOT NULL,

    -- Contagem por critério reprovado, ex.: {"iv_rank": 8, "delta": 5}.
    -- ATENÇÃO: a soma PODE EXCEDER `quantidade`. Uma opção reprovada em dois
    -- critérios é contada nos dois — a pergunta que isto responde é "quantas
    -- foram barradas por este critério", não "como as opções se dividem".
    -- Particionar exigiria eleger um critério principal, e a regra de negócio
    -- não tem essa hierarquia: `avaliar()` trata todos como igualmente
    -- obrigatórios.
    criterios_contagem  JSONB,

    -- Uma opção representativa, para o registro ser legível sem consultar a
    -- cadeia inteira. É AMOSTRA PARA LEITURA, não referência para operar: a
    -- série pode nem existir mais quando alguém ler.
    amostra             JSONB,

    criado_em           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Consulta dominante: "o desfecho da execução mais recente de tal dia".
CREATE INDEX IF NOT EXISTS idx_desfecho_execucao
    ON desfecho_avaliacao (executado_em DESC);

-- Consulta de evolução: "há quantos dias PETR4 é reprovada por IV rank?".
CREATE INDEX IF NOT EXISTS idx_desfecho_ticker_motivo
    ON desfecho_avaliacao (ticker_objeto, motivo, executado_em DESC);
