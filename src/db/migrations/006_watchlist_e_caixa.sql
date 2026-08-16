-- 006: vigiar ativo sem ter posição, e registrar o caixa que garante uma put.
--
-- (a) WATCHLIST — POR QUE COLUNA EM `ativos`, E NÃO TABELA NOVA
-- ------------------------------------------------------------
-- Até aqui o universo de análise era a CARTEIRA: `fetch_options` e a
-- avaliação partiam de `posicoes` abertas. Isso é correto para venda
-- coberta — "coberta" quer dizer que as ações já são suas —, mas fecha a
-- porta para procurar oportunidade em ativo que ainda não se tem.
--
-- Vigiar é atributo do CADASTRO, não entidade própria: só se vigia o que
-- está em `ativos` (as FKs de cotação, opção e notícia já exigem isso), e
-- uma tabela separada só acrescentaria um join para responder "este ticker
-- entra na varredura?". `vigiado_motivo` guarda POR QUE ele entrou — a
-- pergunta que aparece meses depois, quando ninguém lembra.
--
-- O universo de coleta passa a ser CARTEIRA ∪ VIGIADOS. A união importa:
-- um ativo em carteira é coletado mesmo sem estar vigiado, senão parar de
-- vigiar deixaria a posição sem preço.
--
-- LIMITE QUE ISTO NÃO REMOVE: o orçamento diário de requests. Com ~4
-- requests por ticker (cotação + duas janelas de vela + opções), 600/dia
-- comportam ~150 tickers usando o orçamento inteiro. Vigiar a bolsa toda
-- não cabe — a watchlist existe justamente para a escolha ser explícita.
--
-- (b) CAIXA — O GAP QUE BLOQUEIA A PUT COBERTA
-- --------------------------------------------
-- `avaliar()` já suporta covered put e exige `caixa_disponivel`: sem
-- garantia para honrar o exercício ao strike, a operação não é coberta. Só
-- que não havia onde registrar esse caixa, então nenhuma put era avaliada
-- contra a carteira real (gap documentado no CLAUDE.md).
--
-- Tabela de LANÇAMENTOS, não um saldo único: um saldo que se sobrescreve
-- perde a história de como chegou ali, e é a história que explica uma
-- decisão passada. O saldo é a soma dos lançamentos.

ALTER TABLE ativos ADD COLUMN IF NOT EXISTS vigiado BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE ativos ADD COLUMN IF NOT EXISTS vigiado_motivo TEXT;
ALTER TABLE ativos ADD COLUMN IF NOT EXISTS vigiado_desde TIMESTAMPTZ;

-- "Quais entram na varredura de hoje" é a consulta do módulo de
-- oportunidades e dos ETLs.
CREATE INDEX IF NOT EXISTS idx_ativos_vigiados
    ON ativos (ticker) WHERE vigiado;

CREATE TABLE IF NOT EXISTS caixa_lancamentos (
    id              BIGSERIAL PRIMARY KEY,
    -- Positivo = aporte/liberação; negativo = retirada/bloqueio. O saldo é
    -- a soma, e o sinal preserva o que aconteceu em vez de só onde chegou.
    valor           NUMERIC(14,2) NOT NULL,
    descricao       TEXT,
    ocorrido_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
    registrado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT caixa_valor_nao_zero CHECK (valor <> 0)
);

CREATE INDEX IF NOT EXISTS idx_caixa_ocorrido
    ON caixa_lancamentos (ocorrido_em DESC);
