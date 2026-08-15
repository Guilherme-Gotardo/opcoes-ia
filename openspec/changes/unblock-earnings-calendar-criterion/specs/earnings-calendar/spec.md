## Purpose

Manter, de forma rastreável e sempre informada por um humano, as datas de
divulgação de resultado trimestral dos ativos da carteira, para que a
avaliação de venda coberta possa verificar o critério de proximidade de
evento sem nunca inferir ou estimar uma data.

## ADDED Requirements

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
