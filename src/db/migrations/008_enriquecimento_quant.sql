-- 008: contexto quantitativo por opção avaliada (Fase 2 do plano de automação).
--
-- POR QUE TABELA PRÓPRIA, E NÃO COLUNAS EM `sugestoes` OU EM `criterios_json`
-- --------------------------------------------------------------------------
-- São naturezas diferentes de dado, e juntá-las apagaria a distinção que
-- justifica a Fase 2 existir:
--
--   `criterios_json`  GATE  — o que aprovou ou reprovou a operação.
--   este                CONTEXTO — números que ajudam a entender, e que
--                       NÃO decidem nada.
--
-- Guardar theta ao lado de "iv_rank aprovado" faria um número de contexto
-- parecer um critério que alguém precisou passar. E `sugestoes` só recebe as
-- ELEGÍVEIS: o contexto é útil justamente na reprovação, para enxergar quão
-- perto a opção estava — por isso a chave é a execução, não a sugestão.
--
-- Reprocessável de forma independente: melhorar o modelo (mais passos, um
-- dividend yield real) é recalcular estas linhas, sem refazer a avaliação
-- nem mexer numa sugestão já registrada.
--
-- POR QUE TANTA COLUNA DE AUDITORIA
-- ---------------------------------
-- `modelo`, `estilo_exercicio`, `taxa_livre_risco`, `taxa_observada_em` e
-- `volatilidade_usada` não são metadados decorativos: sem eles, um preço
-- teórico de três meses atrás é um número solto que ninguém consegue
-- reconstruir nem contestar. É a mesma razão de `preco_mercado` +
-- `cotacao_em` existirem em `ResultadoAvaliacao`.
--
-- `estilo_exercicio` em especial: a convenção da B3 é call americana e put
-- europeia, e apreçar uma put europeia como americana superestima o prêmio
-- em 2% a 9% conforme o moneyness. Gravar o estilo USADO por linha faz uma
-- futura correção da premissa não reescrever a história.
--
-- `delta_modelo` NÃO se chama `delta`: `opcoes.delta` vem do provedor e é o
-- que o critério de gate consome. Nomes iguais convidariam a trocar um pelo
-- outro em alguma consulta, e a troca só apareceria como sugestão estranha
-- meses depois.

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
