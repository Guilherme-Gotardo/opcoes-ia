-- 005: o que faltava para ACOMPANHAR uma operação de opção.
--
-- POR QUE `posicoes` NÃO BASTAVA
-- ------------------------------
-- A tabela registrava que existe uma posição vendida em PETRI450 por
-- R$ 1,15. Isso é suficiente para valorizar a carteira e não é suficiente
-- para acompanhar a operação: faltava saber a que preço ela pode ser
-- exercida (`strike`), até quando (`vencimento`) e sobre qual ação
-- (`ticker_objeto`).
--
-- A ausência de `ticker_objeto` era a mais limitante. `posicoes.ticker`
-- guarda o CÓDIGO da opção, que não é linha em `ativos` — então não havia
-- NENHUMA ligação entre a opção vendida e a ação que a cobre. Sem ela não
-- dá para comparar o strike com a cotação, que é justamente a pergunta
-- central de uma venda coberta: "a ação passou do strike?".
--
-- Derivar o objeto a partir do código exigiria interpretar código B3, que
-- este projeto não faz em lugar nenhum — por isso é coluna informada, não
-- inferida.
--
-- SEM O DESFECHO NÃO HÁ RESULTADO
-- -------------------------------
-- `fechada_em` dizia QUANDO a posição fechou, nunca COMO. Mas o resultado
-- financeiro depende exatamente disso: uma call que expira sem exercício
-- rende o prêmio inteiro; recomprada, rende o prêmio menos o custo da
-- recompra; exercida, rende o prêmio mais o resultado da venda da ação ao
-- strike — e essa última atravessa duas categorias fiscais diferentes.
-- Sem `motivo_fechamento` e `preco_fechamento`, "quanto rendeu" só podia
-- ser estimado, e estimar dinheiro realizado é pior do que não mostrar.
--
-- Todas as colunas são NULL-áveis: posição em ação não tem strike, e
-- posição aberta não tem desfecho. A migração é aditiva e idempotente.

ALTER TABLE posicoes ADD COLUMN IF NOT EXISTS ticker_objeto VARCHAR(12)
    REFERENCES ativos(ticker);
ALTER TABLE posicoes ADD COLUMN IF NOT EXISTS strike NUMERIC(14,4);
ALTER TABLE posicoes ADD COLUMN IF NOT EXISTS vencimento DATE;
ALTER TABLE posicoes ADD COLUMN IF NOT EXISTS preco_fechamento NUMERIC(14,4);
ALTER TABLE posicoes ADD COLUMN IF NOT EXISTS motivo_fechamento VARCHAR(20);

-- Conjunto fechado, como `desfecho_avaliacao.motivo`: texto livre aqui
-- viraria "expirou", "expirada", "venceu" na mesma base, e a apuração não
-- teria como somar.
--
-- `expirada`  — virou pó, o vendedor fica com o prêmio inteiro
-- `recomprada`— fechada por compra antes do vencimento (`preco_fechamento`
--               é o que se pagou para sair)
-- `exercida`  — a ação foi entregue ao strike
-- `encerrada` — posição em ação, ou fechamento sem classificação de opção
ALTER TABLE posicoes DROP CONSTRAINT IF EXISTS posicoes_motivo_fechamento_valido;
ALTER TABLE posicoes ADD CONSTRAINT posicoes_motivo_fechamento_valido CHECK (
    motivo_fechamento IS NULL
    OR motivo_fechamento IN ('expirada', 'recomprada', 'exercida', 'encerrada')
);

-- Uma posição fechada precisa dizer como fechou. Sem isto, o registro
-- antigo (só `fechada_em`) continuaria possível e o acompanhamento teria
-- linhas mudas — exatamente o buraco que esta migração fecha.
-- Posições JÁ fechadas antes desta migração ficam de fora da checagem por
-- `NOT VALID`: elas não têm como saber o próprio desfecho retroativamente,
-- e inventá-lo seria pior do que assumir a lacuna.
ALTER TABLE posicoes DROP CONSTRAINT IF EXISTS posicoes_fechamento_declarado;
ALTER TABLE posicoes ADD CONSTRAINT posicoes_fechamento_declarado CHECK (
    fechada_em IS NULL OR motivo_fechamento IS NOT NULL
) NOT VALID;

-- "Quais operações de opção estão abertas neste ativo-objeto" é a consulta
-- do módulo de acompanhamento.
CREATE INDEX IF NOT EXISTS idx_posicoes_opcao_objeto
    ON posicoes (ticker_objeto, vencimento)
    WHERE tipo_ativo = 'OPCAO' AND fechada_em IS NULL;
