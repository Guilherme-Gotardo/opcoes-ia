## Why

O scaffold inicial (Fase 0) existe, mas o fluxo diário descrito no README/CLAUDE.md
não roda de ponta a ponta hoje: não há como alimentar a tabela `posicoes` (o
"estoque de patrimônio" que é a premissa do projeto), o ETL de opções é um stub
não validado contra a API real, o de notícias é um placeholder inerte, e o
agente `strategy-covered` não tem nenhum código que leia a carteira real, avalie
os critérios da skill contra dados do banco e grave o resultado em `sugestoes`
— hoje tudo isso só existe como texto de instrução para o LLM, sem rastro
persistido e auditável. Sem isso, o orquestrador não tem sobre o que orquestrar.
Esta change fecha as Fases 1–3 do roadmap para chegar a um MVP que realmente
acompanha a carteira e produz sugestões diárias registradas no banco.

## What Changes

- Adicionar um mecanismo de entrada/atualização manual das posições
  (ações e opções) na tabela `posicoes`, servindo como o "estoque de
  patrimônio" — sem execução real de ordens, apenas espelho do que o usuário
  informa.
- Adotar a Brapi (https://brapi.dev) como único provedor de dados de mercado
  (cotações e opções) deste MVP inicial, adiando a integração com a OpLab
  para uma change futura (não removida do produto, só fora do escopo desta
  change). `fetch_quotes.py` usa `GET /api/v2/stocks/quote` (confirmado:
  plano Free permite só 1 ativo por requisição); `fetch_options.py` passa a
  apontar para os endpoints reais de `/api/v2/options/*` documentados em
  https://brapi.dev/docs/opcoes, mas fica bloqueado no plano Free (exceto o
  ticker de sandbox `PETR4`) até upgrade para o plano Pro — tratado como gap
  explícito, documentado, não como stub silencioso.
- Implementar um orçamento de requests para os ETLs de mercado (plano Free:
  15.000 requests/mês, meta operacional de até ~600/dia), contabilizando o
  custo de 1 request por ticker em carteira antes de rodar e reportando
  explicitamente quando o orçamento diário não cobre a carteira inteira, em
  vez de estourar a cota mensal silenciosamente.
- Disponibilizar o MCP da Brapi (`https://brapi.dev/api/mcp/mcp`) como
  ferramenta adicional para os agentes de LLM (ex.: `market-analyst`)
  explorarem contexto de mercado ad-hoc durante a análise — sem substituir a
  regra de que preço/grega/IV usados numa decisão de estratégia sempre vêm
  de `src/db` populado pelo ETL determinístico.
- Implementar `src/etl/fetch_news.py` contra uma fonte real definida nesta
  change, ou — se a fonte ainda não puder ser contratada/validada — deixar o
  ETL de notícias claramente opcional no fluxo diário (não bloqueando os
  demais passos) em vez de placeholder silencioso.
- Implementar o código que permite ao agente `strategy-covered` avaliar as
  posições elegíveis da carteira contra `skills/covered-options-strategy`
  usando dados reais do banco, e persistir cada avaliação (aceita ou
  descartada, com critérios e números) na tabela `sugestoes`.
- Implementar a geração de um relatório diário persistido (arquivo ou
  registro no banco) consolidando carteira, alertas e sugestões, para que o
  `orchestrator` tenha uma saída revisável além do texto de chat.
- Atualizar `docs/ARQUITETURA.md` (seção "decisões em aberto") e o checklist
  de "Estado atual" do `CLAUDE.md` conforme cada item avançar.

## Capabilities

### New Capabilities
- `portfolio-tracking`: entrada e atualização das posições de ações/opções em
  carteira (o "estoque de patrimônio"), incluindo validação básica contra o
  schema (`posicoes`) e regras de abertura/fechamento de posição.
- `market-data-collection`: ETL de cotações, opções (preço/gregas/IV/IV rank)
  e notícias, dirigido pelos tickers atualmente em carteira, com tratamento
  de erro explícito (sem silenciar falha de fonte).
- `covered-strategy-execution`: avaliação determinística das posições
  elegíveis contra os critérios de `covered-options-strategy` usando dados
  reais do banco, com persistência auditável de cada sugestão (aceita ou
  descartada) em `sugestoes`.
- `daily-portfolio-report`: consolidação e persistência de um relatório
  diário (resumo da carteira, alertas, sugestões) a partir dos dados e
  sugestões gerados nas capabilities acima.

### Modified Capabilities
(nenhuma — não há specs existentes neste projeto ainda)

## Impact

- `src/etl/fetch_quotes.py` (redesenho para 1 request por ticker + orçamento),
  `src/etl/fetch_options.py` (troca de provedor OpLab → Brapi),
  `src/etl/fetch_news.py` (correção/implementação)
- Novo módulo para entrada/gestão de `posicoes` (ex.: `src/portfolio/`)
- Novo módulo para avaliação da estratégia e persistência de sugestões (ex.:
  `src/strategy/`), consumido pelo agente `strategy-covered`
- Novo módulo para geração do relatório diário (ex.: `src/report/`), consumido
  pelo agente `orchestrator`
- `.claude/agents/data-collector.md`, `.claude/agents/strategy-covered.md`,
  `.claude/agents/orchestrator.md` (ajustar instruções para referenciar o
  código real quando ele existir, em vez de descrever um fluxo só conceitual)
- `.claude/agents/market-analyst.md` (wiring do MCP da Brapi como ferramenta
  de exploração ad-hoc)
- `tests/` (cobertura para os módulos novos)
- `docs/ARQUITETURA.md`, `CLAUDE.md` (atualização do estado atual do projeto)
- Sem mudança de schema além do já existente em `src/db/schema.sql`; se algum
  gap exigir coluna/tabela nova, entra como migração em `src/db/migrations/`
  (regra 4 do `CLAUDE.md`), nunca editando `schema.sql` retroativamente.
