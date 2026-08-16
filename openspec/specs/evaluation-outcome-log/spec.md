## Purpose

Preservar, além do fim do processo que avaliou, o desfecho de cada execução
da avaliação de estratégia — quantas opções foram avaliadas por ativo e por
que as não-sugeridas não passaram — para que "nenhuma sugestão" deixe de ser
um silêncio e para que a evolução disso seja comparável ao longo do tempo.

## Requirements

### Requirement: Registro do desfecho de cada execução
O sistema SHALL registrar, ao final de cada execução da avaliação de
estratégia, o desfecho por ativo avaliado: quantas opções foram avaliadas,
quantas geraram sugestão e quantas não geraram, com o momento da execução.

O registro SHALL ser gravado mesmo quando nenhuma sugestão for gerada — é
justamente esse o caso que ele existe para explicar.

#### Scenario: Execução sem nenhuma sugestão
- **WHEN** a avaliação percorre a carteira e nenhuma opção passa em todos os
  critérios
- **THEN** o desfecho fica registrado, informando por ativo quantas opções
  foram avaliadas e por que nenhuma passou

#### Scenario: Execução com sugestões
- **WHEN** a avaliação gera sugestões para um ativo e descarta outras opções
- **THEN** o registro traz tanto a contagem de sugeridas quanto a das
  não-sugeridas com seus motivos

#### Scenario: Ativo sem nenhuma opção para avaliar
- **WHEN** um ativo em carteira não tem nenhuma opção coletada
- **THEN** o registro representa isso explicitamente, distinguindo "nada a
  avaliar" de "avaliado e nada passou"

### Requirement: Agregação por ativo e motivo
O sistema SHALL agregar o desfecho por (execução, ativo, motivo de
não-sugestão), e SHALL NOT gravar uma linha por opção avaliada.

Quando o motivo for reprovação em critério de mercado, o registro SHALL
informar quantas opções caíram em cada critério. Uma mesma opção pode ser
contada em mais de um critério quando reprovar em vários — a contagem
responde "quantas foram barradas por este critério", não particiona o
conjunto.

O sistema SHALL preservar, para cada motivo registrado, uma opção
representativa com seus valores avaliados, para que o registro seja legível
sem consultar a cadeia inteira.

#### Scenario: Motivo comum a muitas opções gera um registro
- **WHEN** o ativo não tem data de resultado confiável e todas as suas opções
  são bloqueadas pelo mesmo motivo
- **THEN** o desfecho grava um registro para aquele motivo com a contagem de
  opções afetadas, em vez de um registro por opção

#### Scenario: Contagem por critério reprovado
- **WHEN** opções de um ativo são reprovadas por critérios diferentes
- **THEN** o registro informa quantas caíram em cada critério

#### Scenario: Amostra acompanha o motivo
- **WHEN** um motivo é registrado com várias opções afetadas
- **THEN** o registro inclui uma opção representativa com seus valores
  avaliados

### Requirement: Motivos distinguem falta de dado de reprovação no mérito
O sistema SHALL registrar como motivos distintos: reprovação em critério de
mercado, ausência de dado necessário para avaliar, não atendimento de
pré-requisito estrutural, e bloqueio por data de resultado não verificável.

O sistema SHALL NOT agrupar sob o mesmo motivo uma opção reprovada contra um
valor real e uma que não pôde ser avaliada — as duas situações exigem ações
opostas de quem lê.

#### Scenario: Dado ausente não vira reprovação
- **WHEN** uma posição não tem cotação utilizável e por isso não é avaliada
- **THEN** o registro classifica isso como dado insuficiente, e não como
  reprovação em critério

#### Scenario: Bloqueio por data desconhecida é distinguível
- **WHEN** as opções passam nos critérios de mercado mas a data de resultado
  do ativo é desconhecida e a política é bloquear
- **THEN** o registro identifica esse motivo especificamente, permitindo
  reconhecer que a ação que destrava é registrar a data

### Requirement: Histórico comparável entre execuções
O sistema SHALL preservar os registros de execuções anteriores, permitindo
comparar o desfecho de datas diferentes, e SHALL NOT sobrescrever o registro
de uma execução anterior ao gravar uma nova.

#### Scenario: Duas execuções no mesmo dia
- **WHEN** a avaliação roda duas vezes no mesmo dia
- **THEN** os dois desfechos ficam registrados e distinguíveis pelo momento
  da execução

#### Scenario: Evolução de um motivo ao longo do tempo
- **WHEN** um ativo é reprovado pelo mesmo critério em execuções de dias
  diferentes
- **THEN** é possível recuperar essa sequência a partir dos registros
