## MODIFIED Requirements

### Requirement: Avaliações bloqueadas por data de resultado são reportadas
O relatório diário SHALL listar explicitamente as avaliações que não geraram
sugestão, identificando o ativo, o motivo e quantas opções foram afetadas, e
SHALL NOT representá-las apenas como ausência de sugestão.

O relatório SHALL cobrir todos os motivos de não-sugestão registrados — data
de resultado desconhecida, reprovação em critério de mercado, dado
insuficiente e pré-requisito não atendido — e SHALL distinguir reprovação no
mérito de ausência de dado.

O relatório SHALL montar essa seção a partir do desfecho persistido da
execução, e não depender de receber os resultados na mesma execução que os
produziu — assim relatório e demais consumidores enxergam a mesma coisa.

#### Scenario: Bloqueio por data desconhecida aparece no relatório
- **WHEN** uma posição atende a todos os critérios de mercado mas é
  bloqueada porque a data de resultado do ativo é desconhecida e a política
  configurada é `bloquear`
- **THEN** o relatório contém uma entrada identificando esse bloqueio, em vez
  de apenas "Nenhuma sugestão hoje." sem explicação

#### Scenario: Reprovação em critério também é reportada
- **WHEN** opções de um ativo são reprovadas por IV rank abaixo do mínimo
- **THEN** o relatório informa esse motivo e quantas opções foram afetadas,
  em vez de omitir a informação por não ser bloqueio de data

#### Scenario: Relatório gerado separadamente da avaliação
- **WHEN** o relatório é gerado por um processo diferente do que executou a
  avaliação
- **THEN** a seção de não-sugestões é montada normalmente a partir do
  desfecho registrado

#### Scenario: Nenhum bloqueio no dia
- **WHEN** nenhuma avaliação do dia deixou de gerar sugestão
- **THEN** o relatório não inclui a seção de avaliações bloqueadas, sem
  gerar uma seção vazia
