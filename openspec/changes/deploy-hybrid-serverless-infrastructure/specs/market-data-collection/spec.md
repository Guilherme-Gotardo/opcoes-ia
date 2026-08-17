## ADDED Requirements

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
