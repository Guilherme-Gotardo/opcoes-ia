## MODIFIED Requirements

### Requirement: Avaliação baseada em dados reais do banco
O sistema SHALL avaliar cada posição elegível usando exclusivamente dados
já persistidos no banco (`posicoes`, `cotacoes`, `opcoes`,
`eventos_resultado`) e os parâmetros de
`skills/covered-options-strategy/params.yaml` — nunca um valor de mercado
estimado ou lembrado pelo agente.

O sistema SHALL distinguir dois grupos de dados ausentes:
- **Dado de mercado ausente** (IV rank, gregas, preço, dias até o
  vencimento, exposição): interrompe a avaliação daquela posição, que é
  marcada como "dado insuficiente".
- **Data de resultado desconhecida**: NÃO interrompe a avaliação. Os demais
  critérios SHALL ser avaliados e reportados normalmente, e o critério de
  evento de resultado SHALL ser marcado como "indisponível".

#### Scenario: Dado de mercado ausente ou desatualizado
- **WHEN** o IV rank ou as gregas necessárias para avaliar uma posição não
  existem ou estão desatualizados no banco
- **THEN** o sistema marca essa posição como "dado insuficiente" em vez de
  avaliar com um valor assumido

#### Scenario: Data de resultado desconhecida não impede a avaliação
- **WHEN** todos os dados de mercado de uma posição estão disponíveis, mas
  nenhuma data de resultado foi registrada para o ativo
- **THEN** o sistema avalia e reporta o resultado de cada um dos demais
  critérios, marcando apenas o critério de evento de resultado como
  "indisponível", em vez de descartar a posição sem avaliar nada

### Requirement: Todos os critérios precisam passar
O sistema SHALL gerar uma sugestão de venda coberta para uma posição
apenas quando TODOS os critérios de mercado definidos em `params.yaml`
(IV rank mínimo, faixa de delta, faixa de dias até o vencimento, prêmio
mínimo, exposição máxima por ativo, ausência de evento de resultado
próximo) forem satisfeitos — o sistema SHALL NOT relaxar, arredondar ou
ignorar qualquer critério para forçar uma sugestão.

O sistema SHALL distinguir, ao reportar uma não-sugestão, um critério
**reprovado** (avaliado contra um valor real e não atendido) de um critério
**não verificável** (sem dado para avaliar), e SHALL NOT tratar os dois como
a mesma coisa.

#### Scenario: Um critério não atendido
- **WHEN** quatro de cinco critérios de mercado passam mas o IV rank está
  abaixo do mínimo configurado
- **THEN** o sistema não gera sugestão para essa posição

#### Scenario: Motivo da não-sugestão distingue reprovado de não verificável
- **WHEN** uma posição não gera sugestão porque o delta está fora da faixa e
  a data de resultado é desconhecida
- **THEN** o motivo reportado identifica o delta como critério reprovado e a
  data de resultado como critério não verificável, separadamente

## ADDED Requirements

### Requirement: Política configurável para data de resultado desconhecida
O sistema SHALL ler de `params.yaml` a política a aplicar quando a data de
resultado de um ativo for desconhecida, suportando os valores `bloquear` e
`sinalizar`, e SHALL adotar `bloquear` quando o parâmetro estiver ausente.

#### Scenario: Política bloquear com data desconhecida
- **WHEN** a política configurada é `bloquear`, a data de resultado do ativo
  é desconhecida e todos os demais critérios são atendidos
- **THEN** o sistema não gera sugestão para essa posição, e registra que o
  bloqueio se deu por data de resultado não verificável — não por reprovação
  em um critério de mercado

#### Scenario: Política sinalizar com data desconhecida
- **WHEN** a política configurada é `sinalizar`, a data de resultado do ativo
  é desconhecida e todos os demais critérios são atendidos
- **THEN** o sistema gera a sugestão marcada como pendente de verificação
  manual da agenda de resultados, e essa marcação acompanha a sugestão
  persistida

#### Scenario: Parâmetro de política ausente
- **WHEN** `params.yaml` não define a política para data desconhecida
- **THEN** o sistema aplica `bloquear`, preservando a postura conservadora

#### Scenario: Valor de política inválido
- **WHEN** `params.yaml` define um valor de política diferente de `bloquear`
  ou `sinalizar`
- **THEN** o sistema falha com erro explícito em vez de adivinhar a intenção
  ou silenciosamente usar o padrão

### Requirement: Data de resultado conhecida é avaliada normalmente
O sistema SHALL, quando houver data de resultado registrada para o ativo,
avaliar o critério de proximidade de evento contra o limiar
`dias_bloqueio_antes_resultado` de `params.yaml`, independentemente da
política configurada para data desconhecida.

#### Scenario: Resultado próximo demais reprova o critério
- **WHEN** a data de resultado registrada está a menos dias de distância do
  que o limiar configurado
- **THEN** o critério é reprovado e nenhuma sugestão é gerada, mesmo que a
  política para data desconhecida seja `sinalizar`

#### Scenario: Resultado suficientemente distante aprova o critério
- **WHEN** a data de resultado registrada está a mais dias de distância do
  que o limiar configurado
- **THEN** o critério é aprovado e a sugestão não carrega marcação de
  verificação manual da agenda
