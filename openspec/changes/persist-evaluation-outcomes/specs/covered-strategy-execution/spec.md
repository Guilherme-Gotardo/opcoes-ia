## MODIFIED Requirements

### Requirement: Persistência auditável de cada sugestão gerada
O sistema SHALL persistir cada sugestão gerada em `sugestoes`, incluindo o
snapshot completo dos critérios avaliados e seus valores em
`criterios_json`, com status inicial `pendente`.

O sistema SHALL, além disso, persistir o desfecho da execução como um todo —
inclusive quando nenhuma sugestão for gerada — de modo que o motivo de cada
não-sugestão sobreviva ao fim do processo que avaliou.

`sugestoes` SHALL continuar contendo apenas as avaliações que passaram em
todos os critérios: uma avaliação não-sugerida SHALL NOT ser gravada ali com
um status alternativo.

#### Scenario: Sugestão gerada é persistida com rastro
- **WHEN** uma posição atende a todos os critérios e uma sugestão de
  covered call é gerada
- **THEN** o sistema grava uma linha em `sugestoes` com strike, vencimento,
  prêmio estimado e o valor de cada critério avaliado

#### Scenario: Execução sem sugestão também deixa rastro
- **WHEN** a avaliação percorre a carteira e nenhuma opção passa em todos os
  critérios
- **THEN** nenhuma linha é gravada em `sugestoes`, e o desfecho da execução
  fica registrado com o motivo de cada não-sugestão

#### Scenario: Avaliação não-sugerida não polui as sugestões
- **WHEN** uma avaliação é bloqueada ou reprovada
- **THEN** ela não aparece em `sugestoes` sob nenhum status
