## Purpose

Consolidar em um artefato persistido e comparável ao longo do tempo o
resultado da rodada diária (carteira, alertas, sugestões), para que a saída
do `orchestrator` seja revisável fora do chat e nunca se perca.

## Requirements

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
relatório SHALL indicar a sequência completa de ações humanas que destrava a
avaliação — registrar a data **e** consolidá-la — e SHALL NOT indicar apenas
o registro, que sozinho não torna a data consultável pela avaliação.

#### Scenario: Relatório orienta o registro da data
- **WHEN** o relatório lista uma avaliação bloqueada por falta de data de
  resultado
- **THEN** a entrada indica que registrar a data de divulgação do ativo
  destrava a avaliação

#### Scenario: Orientação inclui a consolidação
- **WHEN** o relatório lista uma avaliação bloqueada por falta de data de
  resultado
- **THEN** a orientação apresenta também o passo de consolidação, de modo que
  seguir a instrução ao pé da letra torne a data efetivamente consultável na
  avaliação seguinte

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
