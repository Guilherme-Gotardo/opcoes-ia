## ADDED Requirements

### Requirement: Avaliações bloqueadas por data de resultado são reportadas
O relatório diário SHALL listar explicitamente as avaliações que não geraram
sugestão por data de resultado desconhecida, identificando o ativo e a opção
avaliada, e SHALL NOT representá-las apenas como ausência de sugestão.

#### Scenario: Bloqueio por data desconhecida aparece no relatório
- **WHEN** uma posição atende a todos os critérios de mercado mas é
  bloqueada porque a data de resultado do ativo é desconhecida e a política
  configurada é `bloquear`
- **THEN** o relatório contém uma entrada identificando esse bloqueio, em vez
  de apenas "Nenhuma sugestão hoje." sem explicação

#### Scenario: Nenhum bloqueio no dia
- **WHEN** nenhuma avaliação do dia foi bloqueada por data de resultado
  desconhecida
- **THEN** o relatório não inclui a seção de avaliações bloqueadas, sem
  gerar uma seção vazia

### Requirement: Bloqueio reportado mostra os critérios já verificados
Ao reportar uma avaliação bloqueada por data de resultado desconhecida, o
relatório SHALL mostrar o resultado de cada critério que pôde ser
verificado, para que a proximidade da oportunidade seja visível mesmo sem a
sugestão ter sido emitida.

#### Scenario: Critérios verificados acompanham o bloqueio
- **WHEN** o relatório lista uma avaliação bloqueada por data de resultado
  desconhecida
- **THEN** a entrada mostra o valor e o veredito de cada critério de mercado
  avaliado, e identifica o critério de resultado como não verificável

### Requirement: Bloqueio reportado indica a ação para destravar
Ao reportar uma avaliação bloqueada por data de resultado desconhecida, o
relatório SHALL indicar qual ação humana destrava a avaliação.

#### Scenario: Relatório orienta o registro da data
- **WHEN** o relatório lista uma avaliação bloqueada por falta de data de
  resultado
- **THEN** a entrada indica que registrar a data de divulgação do ativo
  destrava a avaliação

### Requirement: Sugestão sinalizada carrega o aviso no relatório
Quando a política configurada for `sinalizar` e uma sugestão for emitida com
data de resultado desconhecida, o relatório SHALL exibir junto à sugestão o
aviso de que a agenda de resultados não foi verificada.

#### Scenario: Sugestão sinalizada exibe o aviso
- **WHEN** o relatório lista uma sugestão gerada sob a política `sinalizar`
  com data de resultado desconhecida
- **THEN** o aviso de que a agenda de resultados precisa de verificação
  manual aparece junto dessa sugestão, somando-se à indicação de que ela
  está pendente de revisão humana
