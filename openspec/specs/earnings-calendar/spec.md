## Purpose

Manter, de forma rastreável e sempre informada por um humano, as datas de
divulgação de resultado trimestral dos ativos da carteira, para que a
avaliação de venda coberta possa verificar o critério de proximidade de
evento sem nunca inferir ou estimar uma data.

## Requirements

### Requirement: Registro manual de data de resultado
O sistema SHALL permitir registrar a data de divulgação de resultado de um
ativo informada por um humano, e SHALL NOT derivar, estimar ou inferir essa
data a partir de histórico de balanços, periodicidade observada ou qualquer
outro sinal indireto.

#### Scenario: Registro de uma data informada pelo usuário
- **WHEN** o usuário registra que um ativo divulga resultado em uma data
  específica
- **THEN** o sistema persiste essa data associada ao ativo, junto com o
  momento do registro e a origem informada

#### Scenario: Ativo sem data registrada
- **WHEN** nenhuma data de resultado foi registrada para um ativo
- **THEN** o sistema reporta a data como desconhecida, e SHALL NOT produzir
  uma data derivada de trimestres anteriores

### Requirement: Rejeição de registro inválido
O sistema SHALL rejeitar, com erro explícito, um registro de data de
resultado que não seja utilizável para avaliação — e SHALL NOT ajustar,
arredondar ou reinterpretar a entrada para torná-la aceitável.

#### Scenario: Data em formato inválido
- **WHEN** o usuário informa uma data que não é uma data de calendário
  válida
- **THEN** o sistema rejeita o registro com uma mensagem que identifica o
  problema, sem gravar nada

### Requirement: Consulta da data vigente de um ativo
O sistema SHALL, ao ser consultado sobre a próxima data de resultado de um
ativo em uma data de referência, retornar a próxima data registrada igual ou
posterior à referência, ou o estado explícito "desconhecida" quando não
houver nenhuma.

#### Scenario: Próxima data à frente da referência
- **WHEN** um ativo tem datas de resultado registradas tanto no passado
  quanto no futuro em relação à data de referência
- **THEN** o sistema retorna a próxima data futura, ignorando as passadas

#### Scenario: Apenas datas passadas registradas
- **WHEN** um ativo tem apenas datas de resultado já ocorridas em relação à
  data de referência
- **THEN** o sistema retorna o estado "desconhecida", e SHALL NOT retornar
  uma data passada como se fosse a próxima

### Requirement: Correção de uma data registrada
O sistema SHALL permitir corrigir ou remover uma data registrada quando a
empresa alterar sua agenda, preservando a rastreabilidade de que houve
alteração.

#### Scenario: Empresa antecipa a divulgação
- **WHEN** o usuário corrige a data de resultado previamente registrada para
  um ativo
- **THEN** as consultas subsequentes passam a refletir a nova data, e o
  registro anterior permanece auditável

### Requirement: Consolidação executável das fontes de resultado
O sistema SHALL oferecer uma operação executável que consolide as datas de
resultado das fontes configuradas na consulta que o motor de opções faz,
aplicando as mesmas regras de resolução de conflito e precedência já
definidas para o serviço — em particular, uma estimativa SHALL NOT
sobrescrever uma confirmação.

Sem essa operação, uma data registrada manualmente permanece invisível para
a avaliação de estratégia: registrar SHALL NOT ser confundido com
consolidar.

#### Scenario: Data registrada manualmente passa a ser consultável
- **WHEN** o usuário registra a data de resultado de um ativo e em seguida
  executa a consolidação
- **THEN** a consulta da data vigente daquele ativo passa a devolver a data
  registrada, em vez de "desconhecida"

#### Scenario: Consolidação é idempotente
- **WHEN** a consolidação é executada duas vezes seguidas sem que nenhuma
  fonte tenha mudado
- **THEN** o resultado da segunda execução é igual ao da primeira, sem
  duplicar eventos nem alterar a data vigente

#### Scenario: Confirmação sobrevive a uma estimativa posterior
- **WHEN** uma data confirmada já está consolidada e uma fonte secundária
  afirma uma data diferente como estimativa
- **THEN** a data vigente continua sendo a confirmada, e a divergência é
  registrada como conflito em vez de sobrescrever

### Requirement: Seleção explícita das fontes consultadas
A operação de consolidação SHALL consultar, por padrão, apenas a fonte de
registro manual — a única com autoridade para afirmar uma data confirmada e
a única que não depende de rede. As demais fontes SHALL ser consultadas
somente quando pedidas explicitamente.

Uma fonte desconhecida SHALL provocar erro explícito, e o sistema SHALL NOT
ignorá-la em silêncio nem prosseguir com o subconjunto reconhecido — rodar
menos fontes do que o usuário pediu produziria "nenhum evento" por um motivo
que ele não teria como ver.

#### Scenario: Execução padrão não depende de rede
- **WHEN** a consolidação é executada sem indicar fontes
- **THEN** somente a fonte de registro manual é consultada, e a operação
  conclui sem depender de nenhum serviço externo

#### Scenario: Fonte adicional pedida explicitamente
- **WHEN** a consolidação é executada indicando uma fonte externa além da
  manual
- **THEN** ambas são consultadas e suas afirmações entram na resolução de
  conflito

#### Scenario: Fonte desconhecida falha alto
- **WHEN** a consolidação é executada indicando um nome de fonte que não
  existe
- **THEN** o sistema falha com erro explícito nomeando o valor inválido e as
  fontes válidas, sem consolidar nada

### Requirement: Escopo de tickers derivado da carteira
A operação de consolidação SHALL, por padrão, abranger os tickers com
posição em aberto — os mesmos que a avaliação de estratégia percorre — e
SHALL aceitar uma lista explícita que substitua esse padrão.

Quando não houver posição em aberto nem lista explícita, o sistema SHALL
informar que não há o que consolidar e encerrar sem efeito, em vez de
percorrer todos os ativos cadastrados.

#### Scenario: Padrão acompanha a carteira
- **WHEN** a consolidação é executada sem lista de tickers e existem
  posições em aberto
- **THEN** apenas os ativos dessas posições são consolidados

#### Scenario: Lista explícita substitui o padrão
- **WHEN** a consolidação é executada com uma lista explícita de tickers
- **THEN** apenas os tickers dessa lista são consolidados, mesmo que a
  carteira contenha outros

#### Scenario: Carteira vazia não vira varredura
- **WHEN** a consolidação é executada sem lista explícita e não há posição
  em aberto
- **THEN** o sistema informa que não há tickers a consolidar e encerra sem
  consultar nenhuma fonte

### Requirement: Falha de fonte é reportada, nunca virada ausência de evento
Quando uma fonte consultada falhar, a operação de consolidação SHALL
continuar com as demais e SHALL reportar explicitamente qual fonte falhou e
por quê, distinguindo "não conseguimos consultar" de "não há evento".

A operação SHALL sinalizar de forma distinguível a execução em que toda
fonte pedida falhou, para que uma consolidação sem nenhum dado não seja
lida como consolidação bem-sucedida sem eventos.

#### Scenario: Uma fonte fora do ar não derruba as outras
- **WHEN** duas fontes são pedidas e uma delas falha
- **THEN** as afirmações da fonte que respondeu são consolidadas
  normalmente, e a falha da outra é reportada identificando a fonte e o
  motivo

#### Scenario: Todas as fontes falharam
- **WHEN** todas as fontes pedidas falham na mesma execução
- **THEN** o sistema sinaliza que nenhuma fonte pôde ser consultada, em vez
  de reportar consolidação concluída com zero eventos
