## Purpose

Avaliar, de forma determinística e auditável, quais posições da carteira
real são elegíveis para venda coberta (call/put) segundo a skill
`covered-options-strategy`, sem nunca decidir por julgamento livre do
modelo nem executar qualquer ordem.

## Requirements

### Requirement: Avaliação baseada em dados reais do banco
O sistema SHALL avaliar cada posição elegível usando exclusivamente dados
já persistidos no banco (`posicoes`, `cotacoes`, `opcoes`,
`earnings_events`) e os parâmetros de
`skills/covered-options-strategy/params.yaml` — nunca um valor de mercado
estimado ou lembrado pelo agente.

Todo valor monetário de posição usado numa decisão — valor da posição
coberta para o critério de prêmio mínimo, cobertura disponível e patrimônio
total para o critério de exposição — SHALL ser derivado da última cotação
registrada em `cotacoes` para o ticker. O preço médio de entrada
(`posicoes.preco_medio`) é base de custo e SHALL NOT ser usado como valor de
mercado, nem como fallback quando a cotação faltar.

O sistema SHALL distinguir dois grupos de dados ausentes:
- **Dado de mercado ausente** (IV rank, gregas, preço da opção, dias até o
  vencimento, exposição, **cotação do ativo-objeto**): interrompe a
  avaliação daquela posição, que é marcada como "dado insuficiente".
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

#### Scenario: Valor de posição vem da cotação, não do custo
- **WHEN** um ativo tem cotação vigente em `cotacoes` cujo preço difere do
  preço médio de entrada da posição
- **THEN** os critérios de prêmio mínimo e de exposição são calculados sobre
  o preço da cotação, e o preço médio não influencia nenhum dos dois

### Requirement: Pré-requisito de elegibilidade
O sistema SHALL descartar uma posição antes de avaliar critérios de
mercado quando o pré-requisito estrutural da skill não for atendido (lote
completo do ativo-objeto para covered call; caixa/garantia suficiente para
covered put).

#### Scenario: Posição sem lote completo
- **WHEN** uma posição em ação tem menos de 100 ações (ou não é múltiplo de
  100) sem estar comprometida em outra operação
- **THEN** o sistema descarta essa posição para covered call sem avaliar os
  critérios de mercado

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

### Requirement: Persistência auditável de cada sugestão gerada
O sistema SHALL persistir cada sugestão gerada em `sugestoes`, incluindo o
snapshot completo dos critérios avaliados e seus valores em
`criterios_json`, com status inicial `pendente`.

#### Scenario: Sugestão gerada é persistida com rastro
- **WHEN** uma posição atende a todos os critérios e uma sugestão de
  covered call é gerada
- **THEN** o sistema grava uma linha em `sugestoes` com strike, vencimento,
  prêmio estimado e o valor de cada critério avaliado

### Requirement: Nenhuma execução automática
O sistema SHALL NOT, em nenhuma circunstância, enviar, confirmar ou marcar
como executada uma ordem em corretora a partir de uma sugestão gerada. Toda
sugestão persistida SHALL permanecer com status `pendente` até uma ação
humana explícita fora deste fluxo automatizado.

#### Scenario: Sugestão gerada nunca muda para aceita sozinha
- **WHEN** o fluxo automatizado termina de gerar sugestões para o dia
- **THEN** nenhuma sugestão gerada nesse fluxo está com status diferente de
  `pendente`

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

### Requirement: Exposição de operação coberta conta apenas a parte descoberta
O critério `exposicao_maxima_pct_ativo` SHALL medir a exposição em opção
**não coberta** por ativo-objeto. A exposição nova que uma operação
adiciona SHALL ser o notional da opção menos a cobertura já presente na
carteira para aquele ativo, com piso em zero — ações do ativo-objeto
disponíveis no caso de covered call, caixa/garantia informado no caso de
covered put.

O sistema SHALL NOT contar como exposição nova um notional que já está
coberto por posição existente: a operação não adiciona risco direcional que
a carteira ainda não carregue, e contá-lo duas vezes reprovaria toda covered
call de um ativo cujo strike seja alto em relação ao patrimônio.

O denominador do percentual SHALL ser o patrimônio total valorizado a preço
de mercado.

#### Scenario: Covered call totalmente coberta não adiciona exposição
- **WHEN** a carteira tem 100 ações do ativo-objeto e a opção avaliada é uma
  call de 1 contrato sobre esse mesmo ativo
- **THEN** a exposição nova computada para o critério é zero, e o critério é
  aprovado independentemente do strike

#### Scenario: Parte descoberta conta integralmente
- **WHEN** a operação avaliada cobre um notional maior do que a cobertura
  disponível na carteira para aquele ativo
- **THEN** apenas a diferença entre o notional e a cobertura entra no
  cálculo da exposição, e o critério é avaliado contra o limite configurado

#### Scenario: Exposição em opção descoberta já existente continua contando
- **WHEN** a carteira já tem posição em opção não coberta do ativo-objeto
- **THEN** essa exposição existente permanece somada no cálculo do
  percentual, e pode reprovar o critério por si só

### Requirement: Cotação ausente ou fora da janela de frescor é dado insuficiente
O sistema SHALL considerar utilizável apenas a cotação cuja idade esteja
dentro da janela de frescor configurada em `params.yaml`. Quando o ativo não
tiver cotação registrada, ou a mais recente estiver fora dessa janela, o
sistema SHALL marcar a avaliação daquela posição como "dado insuficiente",
identificando o ticker e a idade da cotação encontrada.

O sistema SHALL NOT substituir a cotação ausente pelo preço médio de
entrada, nem por qualquer outro valor derivado, estimado ou lembrado.

O sistema SHALL adotar um padrão conservador quando o parâmetro de frescor
estiver ausente, e SHALL falhar com erro explícito quando o valor
configurado for inválido — em vez de cair silenciosamente no padrão.

#### Scenario: Ativo sem nenhuma cotação
- **WHEN** uma posição em ação não tem nenhuma cotação registrada
- **THEN** a avaliação dessa posição é marcada como "dado insuficiente" por
  falta de cotação, e nenhuma sugestão é gerada para ela

#### Scenario: Cotação mais antiga que a janela configurada
- **WHEN** a cotação mais recente de um ativo é mais antiga que a janela de
  frescor configurada
- **THEN** a avaliação dessa posição é marcada como "dado insuficiente",
  informando a idade da cotação, em vez de usar o preço desatualizado

#### Scenario: Cotação de pregão anterior dentro da janela
- **WHEN** não houve pregão desde a última coleta, mas a cotação mais
  recente ainda está dentro da janela de frescor configurada
- **THEN** a cotação é usada normalmente e a avaliação prossegue

#### Scenario: Janela de frescor inválida
- **WHEN** `params.yaml` define uma janela de frescor de cotação com valor
  inválido
- **THEN** o sistema falha com erro explícito em vez de usar o padrão
