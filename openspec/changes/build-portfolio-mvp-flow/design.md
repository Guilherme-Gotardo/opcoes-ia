## Context

Ver `proposal.md` — a motivação é fechar o gap entre o scaffold (Fase 0) e um
fluxo diário que realmente roda. Constraints já fixadas pelo projeto
(`CLAUDE.md`, `docs/ARQUITETURA.md`):

- Nenhum agente de LLM "lembra" preço/grega/IV — sempre vem de `src/db` ou de
  chamada direta à API configurada.
- Regra de estratégia é código determinístico (`skills/covered-options-strategy`),
  não julgamento livre do LLM.
- Nunca executa ordem real; toda saída de estratégia é sugestão para revisão
  humana.
- Migrações de banco em `src/db/migrations/`; `schema.sql` não é editado
  retroativamente.
- `docs/ARQUITETURA.md` já registra como decisão em aberto que a primeira
  versão de "dashboard" deve ser "um script que gera um relatório
  Markdown/HTML estático a partir de `sugestoes`" — esta change resolve essa
  decisão em aberto.

## Goals / Non-Goals

**Goals:**
- Fechar o ciclo `posicoes` → ETL → avaliação de estratégia → sugestão
  persistida → relatório diário, de ponta a ponta, com dados reais.
- Manter cada etapa testável isoladamente (regras de estratégia como funções
  puras, sem precisar de banco para testar a lógica de decisão).
- Não introduzir nenhuma mudança de schema além do que já existe.

**Non-Goals:**
- Sincronização automática de custódia com a B3/corretora (permanece manual
  nesta fase, conforme decisão em aberto do `ARQUITETURA.md`).
- Dashboard interativo (fase futura — aqui o "relatório" é um artefato
  estático, não uma UI).
- Travas e condor (fora de escopo, fases futuras já documentadas na skill).
- Definição contratual de qual provedor de notícias pago usar (Partnr etc.) —
  esta change só garante que o ETL de notícias tenha um comportamento
  explícito, configurado ou não.

## Decisions

### 1. Entrada de posições como CLI, não API/UI
`src/portfolio/manage.py` expõe subcomandos (`add`, `close`, `list`) que
falam diretamente com `posicoes` via `src/db/connection.py`, seguindo o
mesmo padrão dos scripts de ETL (`python -m src.portfolio.manage add ...`).
Alternativa considerada: expor como API HTTP — rejeitada por não haver
nenhuma camada de serviço/UI no MVP; adicionar uma agora seria escopo extra
não pedido.

### 2. Brapi como provedor único de mercado neste MVP; OpLab adiada
Esta change adota a Brapi (https://brapi.dev) como único provedor de
cotações e opções, substituindo a integração com a OpLab planejada
originalmente — a OpLab fica adiada para uma change futura, não removida do
produto. Motivo: o usuário já tem `BRAPI_TOKEN` real (plano Free) e não tem
assinatura OpLab; validar contra a Brapi agora desbloqueia progresso real em
vez de ficar bloqueado esperando uma assinatura paga.

`fetch_quotes.py` e `fetch_options.py` validam defensivamente o formato da
resposta da Brapi antes de inserir qualquer linha (mesmo princípio já usado
para OpLab): erro explícito em vez de gravar `NULL` silencioso. Confirmado
contra a API real em 2026-08-14 com o token do usuário:
- **Cotações** (`GET /api/v2/stocks/quote`): os campos de mercado vêm
  aninhados em `results[].data.*`, não no nível raiz do item como o código
  original assumia — corrigido (`_extrair_campos`, `FormatoRespostaInvalido`).
- **Opções** (`/api/v2/options/{expirations,strikes,chain,historical,
  analytics,analytics/history}`, ver https://brapi.dev/docs/opcoes): exigem
  plano Pro (R$139,99/mês) para qualquer ticker além de `PETR4` (liberado
  como sandbox público, não é uma liberação do plano do usuário) — toda
  chamada para outro ticker retorna `403 FEATURE_NOT_AVAILABLE`. Enquanto o
  usuário estiver no plano Free, a coleta de opções (e por consequência a
  avaliação de covered call/put, que depende de IV/delta/prêmio) permanece
  bloqueada — mesmo espírito do gap já documentado para OpLab, só que agora
  contra um endpoint e formato de bloqueio já confirmados, prontos para
  ligar assim que o plano for atualizado.

### 3. Notícias: interface agnóstica de provedor, comportamento explícito
`fetch_news.py` usa `NEWS_API_KEY` (já presente em `.env.example`) contra um
provedor de News API genérico (estilo NewsAPI.org: busca por ticker,
resposta com título/resumo/url/data). Se `NEWS_API_KEY` estiver vazia, o
ETL reporta explicitamente "não configurado" e retorna sem erro — isso
satisfaz o requisito de "nunca terminar silenciosamente" sem exigir que a
escolha comercial definitiva (ex.: Partnr) seja feita agora. Deduplicação de
notícia repetida é feita em nível de aplicação (checar `url` já existente
para o ticker antes de inserir), sem exigir `UNIQUE` novo no schema.

### 4. Avaliação de estratégia como função pura + camada de persistência
`src/strategy/covered.py` separa:
- `avaliar(posicao, dados_mercado, params) -> ResultadoAvaliacao` — função
  pura, sem I/O, testável sem banco.
- `executar_avaliacao_carteira()` — busca posições/dados reais no banco,
  chama `avaliar` para cada uma, e persiste em `sugestoes` apenas os
  resultados que passaram em todos os critérios.

Isso mantém "regra decide número" testável por `pytest` sem precisar do
Postgres rodando, e o `strategy-covered` (agente) só invoca
`executar_avaliacao_carteira()` via `Bash`.

### 5. Relatório diário como arquivo Markdown, não tabela nova
`src/report/daily.py` gera `reports/<AAAA-MM-DD>.md` (um arquivo por dia,
nunca sobrescrito) a partir de `posicoes`, alertas coletados durante o ETL
do dia e das linhas de `sugestoes` geradas na mesma execução. `reports/`
entra no `.gitignore` (dado patrimonial pessoal não deve ir para o
repositório). Alternativa considerada: nova tabela `relatorios_diarios` —
rejeitada por exigir migração para um dado que já está 100% derivável das
tabelas existentes; revisitar apenas se a Fase 4 (dashboard) precisar
consultar relatórios via SQL.

### 6. Agentes passam a invocar código real, não só descrever o fluxo
Os arquivos em `.claude/agents/` são atualizados para referenciar os
comandos reais (`python -m src.portfolio.manage`, `python -m
src.strategy.covered`, `python -m src.report.daily`) nos passos onde hoje
descrevem a ação apenas em prosa. O conteúdo comportamental (o que cada
agente pode/não pode fazer) não muda.

### 7. Orçamento de requests da Brapi (plano Free: 15k/mês, ~600/dia)
`fetch_quotes.py` passa a mandar 1 request por ticker (confirmado: o plano
Free rejeita mais de 1 ativo por requisição, erro
`QUOTES_PER_REQUEST_EXCEEDED`), e precisa de um orçamento explícito para não
estourar a cota mensal silenciosamente. Decisão: um contador simples,
derivado do histórico de linhas já gravadas em `cotacoes`/`opcoes` no
dia/mês corrente via `coletado_em` (sem tabela nova), comparado a um limite
configurável (`BRAPI_REQUESTS_DIA_MAXIMO`, default consistente com ~600/dia)
antes de iniciar a coleta; se o orçamento diário for insuficiente para
cobrir 1 request por ticker em carteira, o ETL loga um alerta explícito e
processa parcialmente (os tickers que cabem no orçamento) em vez de
estourar. Esse orçamento é compartilhado com qualquer uso do Brapi MCP pelos
agentes (mesma conta/token) — ver decisão 8. Alternativa considerada:
sincronizar contra um endpoint de "uso da conta" da própria Brapi —
rejeitada porque a API pública não expõe esse dado (nenhum header de
rate-limit foi observado nas respostas testadas) e adicionaria uma
dependência de rede extra só para contar requests.

### 8. Brapi MCP como ferramenta ad-hoc do agente, nunca fonte de dado persistido
Confirmado contra a API real: `https://brapi.dev/api/mcp/mcp` (protocolo
MCP/JSON-RPC, autenticado com `Authorization: Bearer <BRAPI_TOKEN>`) funciona
no plano Free e expõe 69 tools, cada uma respeitando a mesma restrição de
plano da REST (ex.: `get_option_chain` retorna o mesmo erro pedindo plano
Pro). O formato de resposta do MCP é achatado (campos no nível raiz),
diferente do REST puro (aninhado em `data`) — são interfaces distintas, não
intercambiáveis linha a linha.

Decisão: o agente `market-analyst` pode usar o MCP da Brapi como ferramenta
de exploração ad-hoc (ex.: buscar ticker, ver fundamentals) durante a
contextualização — nunca como substituto do dado persistido em `src/db`
usado por `strategy/covered.py` para decidir critérios (regra 1 do
`CLAUDE.md` permanece: preço/grega/IV usados na decisão sempre vêm do banco
populado pelo ETL determinístico, nunca de uma chamada ad-hoc do agente
durante a análise). Cada chamada MCP consome a mesma cota de requests do ETL
(decisão 7). Alternativa considerada: dar ao `strategy-covered` acesso
direto ao MCP — rejeitada porque isso reabriria a porta para o agente
"decidir" com dado não auditável, violando a regra 2 do `CLAUDE.md`
(separação decisão vs. execução: skill decide, LLM só contextualiza).

## Risks / Trade-offs

- [Formato real da API da Brapi difere do assumido] → mitigado pela
  validação defensiva (decisão 2); falha alto e claro em vez de gravar dado
  errado. Já se concretizou uma vez (campos de cotação aninhados em `data`)
  e foi corrigido.
- [Plano Free da Brapi não cobre opções] → aceito como gap explícito
  (decisão 2): covered call/put fica bloqueada até upgrade para Pro, no
  mesmo padrão de "dado insuficiente" já usado para outros gaps do MVP.
- [Orçamento de requests estourado por crescimento da carteira ou uso do MCP
  pelos agentes] → mitigado pelo contador/limite diário configurável
  (decisão 7), compartilhado entre ETL e MCP.
- [Relatório em arquivo não é consultável via SQL] → aceitável para o MVP;
  formato Markdown com nome de arquivo por data já permite comparação
  manual; migração para tabela fica registrada como opção futura na decisão 5.
- [Rate limit do provedor de notícias genérico] → mitigado limitando a busca
  aos tickers atualmente em carteira e deduplicando por `url` antes de
  inserir.
- [Múltiplas execuções no mesmo dia gerando sugestões duplicadas em
  `sugestoes`] → mitigado checando, antes de inserir, se já existe uma
  sugestão `pendente` para o mesmo `codigo_opcao` gerada no mesmo dia.

## Migration Plan

Nenhuma migração de schema é necessária (todas as tabelas usadas já existem
em `schema.sql`). Passos de rollout:

1. Implementar e testar localmente com `docker compose up -d db` e uma
   posição de teste cadastrada manualmente. (Concluído em 2026-08-14 com
   Brapi/cotações — ver tasks.md 6.1.)
2. Validar `fetch_options.py` contra os endpoints reais de opções da Brapi
   assim que o plano for atualizado para Pro (bloqueado no Free, exceto o
   sandbox `PETR4`) antes de habilitar no workflow agendado. A integração
   com a OpLab fica adiada para uma change futura.
3. Atualizar `.github/workflows/daily-etl.yml` para incluir os novos passos
   (avaliação de estratégia + geração de relatório) só depois do passo 2
   estar validado — e para respeitar o orçamento diário de requests da
   Brapi (decisão 7) na frequência de execução agendada.
4. Rollback: como não há mudança de schema e as escritas são aditivas
   (novas linhas em `posicoes`/`sugestoes`, novos arquivos em `reports/`),
   reverter é apenas reverter os commits — nenhum dado histórico precisa ser
   desfeito.

## Open Questions

- Qual provedor de notícias definitivo será contratado (NewsAPI genérico vs.
  Partnr) — não bloqueia esta change porque a interface é agnóstica de
  provedor e o comportamento observável ("configurado" vs. "não
  configurado") já está especificado.
- Quando fazer upgrade do plano Brapi Free para Pro (R$139,99/mês,
  necessário para dados de opções) — não bloqueia esta change porque a
  avaliação de covered call/put já é tratada como "dado insuficiente"
  enquanto os dados de opções não existirem no banco; decisão de negócio do
  usuário, fora do escopo técnico desta change.
- Quando (e se) retomar a integração com a OpLab como provedor adicional ou
  alternativo, dado que a Brapi já cobre cotações e (no plano Pro) opções.
