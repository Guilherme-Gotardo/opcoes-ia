## Purpose

Avaliar, de forma determinística e auditável, quais posições da carteira
real são elegíveis para venda coberta (call/put) segundo a skill
`covered-options-strategy`, sem nunca decidir por julgamento livre do
modelo nem executar qualquer ordem.

## ADDED Requirements

### Requirement: Avaliação baseada em dados reais do banco
O sistema SHALL avaliar cada posição elegível usando exclusivamente dados
já persistidos no banco (`posicoes`, `cotacoes`, `opcoes`) e os parâmetros
de `skills/covered-options-strategy/params.yaml` — nunca um valor de
mercado estimado ou lembrado pelo agente.

#### Scenario: Dado de mercado ausente ou desatualizado
- **WHEN** o IV rank ou as gregas necessárias para avaliar uma posição não
  existem ou estão desatualizados no banco
- **THEN** o sistema marca essa posição como "dado insuficiente" em vez de
  avaliar com um valor assumido

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

#### Scenario: Um critério não atendido
- **WHEN** quatro de cinco critérios de mercado passam mas o IV rank está
  abaixo do mínimo configurado
- **THEN** o sistema não gera sugestão para essa posição

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
