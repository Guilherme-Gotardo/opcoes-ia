## Purpose

Consolidar em um artefato persistido e comparável ao longo do tempo o
resultado da rodada diária (carteira, alertas, sugestões), para que a saída
do `orchestrator` seja revisável fora do chat e nunca se perca.

## ADDED Requirements

### Requirement: Conteúdo consolidado do relatório
O sistema SHALL consolidar, em um único relatório por execução, o resumo
da carteira atual (posições e exposição por ativo), os alertas relevantes
(dado desatualizado, notícia/evento de impacto) e as sugestões geradas na
avaliação de estratégia do dia, cada uma com sua justificativa numérica.

#### Scenario: Relatório inclui as três seções
- **WHEN** o fluxo diário termina de coletar dados e avaliar estratégias
- **THEN** o relatório gerado contém resumo da carteira, alertas e
  sugestões (ou explicita "nenhuma sugestão hoje" quando não houver)

### Requirement: Persistência histórica do relatório
O sistema SHALL persistir cada relatório diário como um artefato distinto,
sem sobrescrever o relatório de um dia anterior, permitindo comparar dias
diferentes posteriormente.

#### Scenario: Dois dias consecutivos geram dois relatórios
- **WHEN** o fluxo diário roda em dois dias diferentes
- **THEN** existem dois relatórios persistidos, um para cada dia, ambos
  consultáveis

### Requirement: Nenhuma lacuna de dado é preenchida por suposição
O sistema SHALL sinalizar explicitamente no relatório qualquer dado
incompleto, inconsistente ou desatualizado retornado pelas etapas
anteriores, em vez de omitir a lacuna ou preencher com um valor assumido.

#### Scenario: Dado desatualizado é sinalizado
- **WHEN** algum ativo da carteira não teve cotação coletada com sucesso
  no dia
- **THEN** o relatório inclui um alerta explícito sobre esse ativo em vez
  de simplesmente omiti-lo

#### Scenario: Opções indisponíveis por limite de plano
- **WHEN** a coleta de opções não roda para um ativo porque o plano do
  provedor configurado não dá acesso a esse dado
- **THEN** o relatório inclui um alerta explícito indicando que a avaliação
  de covered call/put para aquele ativo está bloqueada por limite de plano,
  em vez de simplesmente mostrar "nenhuma sugestão hoje" sem explicação

### Requirement: Linguagem de revisão humana, nunca de execução
O relatório gerado SHALL deixar explícito que toda sugestão nele contida é
para revisão humana, e SHALL NOT conter nenhuma linguagem que possa ser
confundida com confirmação de ordem executada.

#### Scenario: Sugestão listada no relatório
- **WHEN** o relatório lista uma sugestão de covered call
- **THEN** o texto ao lado da sugestão indica que ela está pendente de
  revisão humana
