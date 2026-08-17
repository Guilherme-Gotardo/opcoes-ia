## Purpose

Manter cotações, dados de opções (preço/gregas/IV/IV rank) e notícias
atualizados no banco, dirigidos pelas posições realmente em carteira, com
falhas de coleta sempre explícitas — nunca silenciosas.

## Requirements

### Requirement: Coleta de cotações dirigida pela carteira
O sistema SHALL coletar cotações apenas para os tickers de ações que
possuem posição aberta em `posicoes`, sem depender de uma lista fixa
hardcoded de ativos.

#### Scenario: Nenhuma posição aberta
- **WHEN** não há nenhuma posição de ação aberta na carteira
- **THEN** o ETL de cotações não faz nenhuma chamada externa e registra que
  não havia tickers a coletar

### Requirement: Coleta de cotações respeita o limite de ativos por requisição
O sistema SHALL fazer uma requisição por ticker ao provedor de cotações
quando o plano configurado limitar a quantidade de ativos por requisição,
em vez de assumir que múltiplos tickers cabem numa única chamada.

#### Scenario: Carteira com múltiplos tickers de ação
- **WHEN** há mais de um ticker de ação com posição aberta e o plano do
  provedor permite apenas 1 ativo por requisição
- **THEN** o sistema faz uma requisição por ticker e todas as cotações
  válidas são gravadas, com falha de um ticker isolada dos demais

### Requirement: Orçamento de requests respeitado
O sistema SHALL conhecer um limite diário configurável de requests ao
provedor de mercado e SHALL NOT ultrapassá-lo silenciosamente.

#### Scenario: Orçamento diário insuficiente para toda a carteira
- **WHEN** a quantidade de tickers em carteira multiplicada pelo custo em
  requests da coleta excede o orçamento diário configurado
- **THEN** o sistema coleta cotações até o limite do orçamento, registra
  explicitamente quais tickers ficaram de fora por orçamento insuficiente, e
  não faz nenhuma chamada além do limite

### Requirement: Coleta de dados de opções contra a API real
O sistema SHALL coletar preço, gregas (delta, gamma, theta, vega, rho),
volatilidade implícita e IV rank para as opções relevantes aos
ticker-objeto em carteira, usando o formato de resposta validado da API de
opções configurada (não um formato assumido sem verificação).

#### Scenario: Resposta da API em formato inesperado
- **WHEN** a API de opções retorna um payload que não bate com o formato
  validado
- **THEN** o sistema não grava dados parciais ou incorretos na tabela
  `opcoes` e reporta o erro de formato explicitamente

#### Scenario: Provedor de opções indisponível no plano atual
- **WHEN** o provedor de dados de opções configurado retorna que o recurso
  não está disponível no plano contratado (ex.: requer upgrade)
- **THEN** o sistema não grava nenhuma linha em `opcoes` para aquele ticker,
  reporta o bloqueio de forma explícita (distinta de um erro genérico de
  formato ou de rede) e essa informação chega ao relatório diário como um
  alerta

### Requirement: Ferramentas de exploração ad-hoc para agentes (não persistido)
O sistema SHALL disponibilizar, para os agentes de LLM, um mecanismo de
consulta ad-hoc a dados de mercado (ex.: busca de ticker, fundamentals) via
o MCP do provedor configurado, sem que isso substitua a exigência de que
preço/grega/IV usados numa decisão de estratégia venham exclusivamente do
banco populado pelo ETL determinístico.

#### Scenario: Agente explora contexto de um ticker
- **WHEN** o `market-analyst` precisa de contexto adicional sobre um ativo
  durante a análise (ex.: nome completo, setor, fundamentals)
- **THEN** ele pode consultar o MCP do provedor configurado para essa
  informação de contexto, mas nunca usa esse canal para obter o preço/grega/
  IV usado pela avaliação de `covered-strategy-execution`

### Requirement: Isolamento de falha por ticker
O sistema SHALL continuar a coleta dos demais tickers quando um ticker
específico falhar, registrando a falha daquele ticker sem interromper o
restante nem omitir o erro do resumo final.

Quando a falha for causada por ativo não cadastrado, o sistema SHALL
reportá-la como tal, nomeando o ticker e a ação que resolve, e SHALL NOT
expor apenas o erro de integridade do banco de dados — a mensagem crua não
diz ao usuário o que fazer.

#### Scenario: Um ticker falha, outros continuam
- **WHEN** a coleta de opções falha para um ticker específico da carteira
- **THEN** os demais tickers continuam sendo coletados normalmente e o
  ticker que falhou aparece listado como falha no resumo da execução

#### Scenario: Ticker sem ativo cadastrado
- **WHEN** a coleta de cotações encontra um ticker que não está no cadastro
  de ativos
- **THEN** a falha reportada identifica o ticker como ativo não cadastrado e
  cita a ação de cadastro, em vez de reproduzir a violação de chave
  estrangeira do banco
### Requirement: Coleta de notícias explícita quanto ao seu estado
O sistema SHALL, para cada execução do ETL de notícias, ou (a) coletar
notícias reais de uma fonte configurada e resumida em texto próprio, ou (b)
reportar de forma explícita que a coleta de notícias não está configurada —
nunca terminar silenciosamente sem indicar qual dos dois casos ocorreu.

#### Scenario: Fonte de notícias não configurada
- **WHEN** nenhuma fonte de notícias está configurada no ambiente
- **THEN** o ETL reporta claramente que a etapa foi pulada por falta de
  configuração, e essa informação chega ao relatório diário como um alerta

### Requirement: Rastreabilidade de atualização por fonte
O sistema SHALL permitir determinar, para cada fonte de dados (cotações,
opções, notícias), o timestamp da última coleta bem-sucedida, para que
consumidores downstream identifiquem dado desatualizado.

#### Scenario: Consumidor verifica frescor do dado
- **WHEN** o agente de análise de mercado ou de estratégia precisa decidir
  se um dado está atualizado o suficiente para uso
- **THEN** ele consegue obter o timestamp da última coleta bem-sucedida
  daquela fonte a partir do banco

### Requirement: Resultado operacional agregado da coleta
Cada execução de coleta SHALL produzir um resultado estruturado por fonte com
estado `sucesso`, `parcial`, `falha`, `bloqueado` ou `pulado`, além das contagens
de alvos tentados, persistidos, falhos e não executados. O resultado SHALL
preservar o detalhe por ticker já exigido e SHALL ser consumível pelo
orquestrador e pela observabilidade sem interpretação de texto livre.

#### Scenario: Parte dos tickers falha
- **WHEN** ao menos um ticker é persistido e ao menos um ticker falha para uma
  fonte
- **THEN** a fonte termina como `parcial`, com contagens e tickers afetados

#### Scenario: Todos os tickers falham
- **WHEN** havia alvos para uma fonte e nenhum deles foi coletado com sucesso
- **THEN** a fonte termina como `falha`, exceto quando todos os alvos têm um
  bloqueio de plano explicitamente classificado

#### Scenario: Recurso indisponível no plano contratado
- **WHEN** o provedor recusa a coleta porque o recurso não pertence ao plano
- **THEN** a fonte termina como `bloqueado`, distinta de erro de rede, formato
  ou aplicação

#### Scenario: Fonte opcional não configurada
- **WHEN** uma fonte opcional não tem credencial ou configuração
- **THEN** a fonte termina como `pulado` com motivo explícito, e não como sucesso
  vazio

#### Scenario: Universo de coleta vazio
- **WHEN** não há ativos em carteira nem vigiados para coletar
- **THEN** a fonte termina como `pulado` com motivo de universo vazio e sem
  chamada externa

### Requirement: Resultado agregado controla o desfecho da etapa
O orquestrador SHALL avaliar os resultados agregados de todas as fontes e SHALL
registrar a etapa como concluída, parcial ou falha conforme uma política
configurada e versionada. Uma coleta totalmente falha SHALL NOT produzir uma
execução geral indistinguível de sucesso completo.

#### Scenario: Fonte obrigatória falha totalmente
- **WHEN** uma fonte marcada como obrigatória termina como `falha`
- **THEN** a etapa de coleta e a execução geral refletem a falha segundo a
  política, sem ocultá-la em logs de aviso

#### Scenario: Fonte opcional é pulada
- **WHEN** uma fonte opcional termina como `pulado` por falta de configuração
- **THEN** o fluxo pode continuar, mas o estado e o motivo permanecem visíveis
  no resultado da execução e no relatório
