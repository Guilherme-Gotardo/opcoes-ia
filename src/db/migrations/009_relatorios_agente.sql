-- 009: relatórios compostos pelo agente de IA (Fase 4 do plano).
--
-- POR QUE O TEXTO VAI PARA O BANCO, E NÃO SÓ PARA reports/
-- --------------------------------------------------------
-- `report/daily.py` escreve markdown em disco, e isso continua. Mas o
-- relatório do agente precisa aparecer na INTERFACE, e a API roda em
-- processo separado do pipeline — no caso do GitHub Actions, em máquina
-- separada. Ler do disco acoplaria a API ao sistema de arquivos de quem
-- gerou. O texto vai para as duas pontas: arquivo para ler no repositório,
-- linha para a tela.
--
-- POR QUE GUARDAR MODELO, FONTES E CUSTO JUNTO DO TEXTO
-- -----------------------------------------------------
-- Um relatório escrito por LLM sem procedência não é auditável: meses
-- depois ninguém sabe qual modelo escreveu, se ele consultou a web, o que
-- citou, nem quanto custou. `fontes` guarda as URLs que a busca trouxe —
-- é o que permite conferir uma afirmação de contexto externo contra o
-- original, e é a razão de a busca web ter sido escolhida em vez de um MCP
-- (ela devolve citação nativa).
--
-- `insumo_resumo` guarda CONTAGENS, não o insumo inteiro: quantas sugestões
-- e quantas linhas de desfecho o agente tinha na frente. Serve para
-- responder "sobre o que ele escreveu?" sem duplicar no banco dados que já
-- estão em `sugestoes`, `desfecho_avaliacao` e `enriquecimento_quant`.
--
-- Várias linhas por dia são esperadas: reprocessar gera outra: a interface
-- lê a mais recente, e o histórico preserva o que foi dito antes.

CREATE TABLE IF NOT EXISTS relatorios_agente (
    id              BIGSERIAL PRIMARY KEY,
    data            DATE NOT NULL,
    gerado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    texto           TEXT NOT NULL,

    -- Procedência. Sem estes campos o texto é anônimo.
    modelo          VARCHAR(40) NOT NULL,
    -- URLs que a busca web trouxe e o agente citou.
    fontes          JSONB NOT NULL DEFAULT '[]'::jsonb,
    buscas          INTEGER NOT NULL DEFAULT 0,
    tokens_entrada  INTEGER,
    tokens_saida    INTEGER,
    -- Contagens do que estava na frente do agente, não o insumo inteiro.
    insumo_resumo   JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- "O relatório de hoje" é a consulta da interface; "os últimos" é a do
-- histórico. As duas saem deste índice.
CREATE INDEX IF NOT EXISTS idx_relatorios_agente_data
    ON relatorios_agente (data DESC, gerado_em DESC);
