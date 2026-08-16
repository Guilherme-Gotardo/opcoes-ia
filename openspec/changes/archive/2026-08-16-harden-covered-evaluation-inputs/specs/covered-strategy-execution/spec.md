## MODIFIED Requirements

### Requirement: Dado ausente nunca é assumido nem derruba a avaliação
A avaliação SHALL tratar todo campo obrigatório ausente como "dado
insuficiente", registrando o motivo, e SHALL NOT assumir valor padrão nem
interromper a execução com exceção.

`strike` SHALL constar entre os campos obrigatórios: ele é base do cálculo
de garantia no covered put e do notional descoberto no covered call.

O sistema SHALL NOT substituir `strike` ausente por zero ao calcular
exposição — um dado faltando não pode APROVAR o critério que existe para
barrar.

#### Scenario: Strike ausente em covered put
- **WHEN** uma opção de venda candidata não tem strike registrado
- **THEN** a avaliação registra dado insuficiente nomeando o strike, sem
  levantar exceção

#### Scenario: Strike ausente em covered call
- **WHEN** uma opção de compra candidata não tem strike registrado
- **THEN** a avaliação registra dado insuficiente, e o critério de exposição
  não é dado como aprovado por exposição zero

#### Scenario: Caixa ausente com strike válido
- **WHEN** o strike existe mas o caixa/garantia disponível não foi informado
- **THEN** o motivo registrado é a ausência do caixa

### Requirement: Todo valor usado numa decisão vem de dado fresco
A avaliação SHALL aplicar uma janela de frescor ao DADO DA OPÇÃO — preço,
delta e IV rank — além da janela já aplicada à cotação da ação.

A janela da opção SHALL ser configurável de forma independente
(`opcao_frescor_maximo_horas`) e SHALL herdar a janela da cotação quando não
configurada.

Dado de opção sem data de coleta SHALL ser tratado como insuficiente: não
saber a idade não autoriza o uso.

#### Scenario: Opção coletada fora da janela
- **WHEN** o dado mais recente de uma opção foi coletado além da janela
- **THEN** a avaliação registra dado insuficiente, nomeando o código da
  opção e a idade do dado

#### Scenario: Janela da opção mais curta que a da cotação
- **WHEN** `opcao_frescor_maximo_horas` é menor que
  `cotacao_frescor_maximo_horas`
- **THEN** a opção é barrada pela janela menor sem que a cotação da ação
  seja afetada

### Requirement: A condição em que um número foi produzido acompanha o número
Quando o patrimônio a mercado estiver incompleto, o critério de exposição
SHALL declarar, no próprio detalhe, que o denominador é parcial e quais
tickers ficaram sem cotação.

O detalhe do critério de prêmio SHALL apresentar o equivalente mensal ao
lado do percentual bruto, para que o viés de prazo do limiar fique visível.

O sistema SHALL oferecer um critério adicional opcional de prêmio
normalizado por prazo, e SHALL NOT alterar a postura de risco vigente quando
esse parâmetro não estiver configurado.

#### Scenario: Exposição calculada sobre patrimônio parcial
- **WHEN** algum ticker da carteira está sem cotação utilizável
- **THEN** o detalhe do critério de exposição nomeia os tickers ausentes e
  informa que a exposição real é menor ou igual à exibida

#### Scenario: Prêmio bruto e mensal no mesmo detalhe
- **WHEN** uma opção é avaliada pelo critério de prêmio mínimo
- **THEN** o detalhe mostra o percentual bruto e o equivalente mensal, e o
  veredito continua sendo dado sobre o bruto

#### Scenario: Critério mensal configurado
- **WHEN** `premio_minimo_pct_ao_mes` está configurado e uma opção passa no
  bruto mas não no normalizado
- **THEN** a avaliação reprova, registrando os dois critérios separadamente
