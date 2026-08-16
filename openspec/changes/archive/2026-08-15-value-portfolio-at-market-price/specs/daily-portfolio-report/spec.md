## ADDED Requirements

### Requirement: Carteira reportada a preço de mercado
O relatório diário SHALL valorizar cada posição aberta e o patrimônio total
pela última cotação vigente do ticker, não pelo preço médio de entrada, e
SHALL identificar explicitamente que o valor mostrado é a mercado.

O relatório SHALL exibir, para cada posição, tanto o preço médio de entrada
quanto o preço de mercado utilizado, para que a base de custo continue
visível sem ser confundida com valor.

O relatório SHALL informar a data/hora da cotação usada em cada valorização,
para que o leitor saiba de quando é o número que está lendo.

#### Scenario: Patrimônio reflete o mercado, não o custo
- **WHEN** a carteira tem posições cujo preço de mercado difere do preço
  médio de entrada
- **THEN** o patrimônio total do relatório é a soma dos valores a mercado, e
  o texto identifica esse valor como sendo a preço de mercado

#### Scenario: Preço médio permanece visível
- **WHEN** o relatório lista as posições abertas
- **THEN** cada linha mostra o preço médio de entrada e o preço de mercado
  lado a lado, sem que um substitua o outro

### Requirement: Exposição por ativo é calculada a mercado
O relatório diário SHALL calcular o percentual de exposição por
ativo-objeto sobre valores a preço de mercado, tanto no numerador quanto no
denominador, de modo que o percentual mostrado ao usuário seja consistente
com o critério de exposição aplicado na avaliação de estratégia.

#### Scenario: Percentual de exposição consistente com a avaliação
- **WHEN** o relatório mostra a exposição percentual de um ativo e a
  avaliação de estratégia do mesmo dia avaliou o critério de exposição para
  esse ativo
- **THEN** ambos os percentuais partem da mesma base de valorização a
  mercado

### Requirement: Posição sem cotação utilizável é sinalizada, nunca estimada
Quando não houver cotação dentro da janela de frescor configurada para um
ativo da carteira, o relatório SHALL sinalizar essa posição explicitamente,
identificando o ticker e a idade da última cotação encontrada, e SHALL NOT
apresentar um valor de mercado derivado do preço médio de entrada ou de
qualquer outra estimativa para essa posição.

O relatório SHALL deixar claro que o patrimônio total mostrado está
incompleto quando alguma posição ficou sem valorização a mercado, em vez de
apresentar um total que aparenta cobrir a carteira inteira.

#### Scenario: Ativo sem cotação fresca no dia
- **WHEN** uma posição em ação não tem cotação dentro da janela de frescor
  configurada
- **THEN** o relatório sinaliza essa posição com o ticker e a idade da
  última cotação, e não mostra valor de mercado estimado para ela

#### Scenario: Patrimônio parcial é declarado como parcial
- **WHEN** ao menos uma posição da carteira ficou sem cotação utilizável
- **THEN** o relatório indica que o patrimônio total não cobre todas as
  posições, identificando quais ficaram de fora

#### Scenario: Carteira inteira valorizada
- **WHEN** todas as posições abertas têm cotação dentro da janela de frescor
- **THEN** o relatório apresenta o patrimônio total sem ressalva de
  cobertura parcial
