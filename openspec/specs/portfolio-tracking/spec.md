## Purpose

Manter um espelho fiel do que o usuário realmente tem alocado em ações e
opções — o "estoque de patrimônio" — sem representar nem permitir execução
real de ordens em corretora.

## Requirements

### Requirement: Registro manual de posição
O sistema SHALL permitir registrar uma nova posição (ticker, tipo_ativo
`ACAO` ou `OPCAO`, quantidade, preço médio) como origem `manual`, sem
depender de nenhuma corretora ou execução real.

O sistema SHALL exigir que o ativo referenciado pela posição já esteja
cadastrado, e SHALL rejeitar o registro com mensagem que cite a ação de
cadastro quando não estiver. O sistema SHALL NOT cadastrar o ativo
automaticamente a partir do ticker informado: isso exigiria inventar o nome
do ativo.

Para posição em opção, o ativo que precisa estar cadastrado é o
ativo-objeto, não o código da opção.

#### Scenario: Registrar posição comprada em ação
- **WHEN** o usuário informa uma posição com tipo_ativo `ACAO` e quantidade
  positiva, para um ativo já cadastrado
- **THEN** o sistema grava a posição em `posicoes` com `origem = 'manual'` e
  `fechada_em` nulo

#### Scenario: Registrar posição vendida em opção
- **WHEN** o usuário informa uma posição com tipo_ativo `OPCAO` e quantidade
  negativa (venda)
- **THEN** o sistema grava a posição em `posicoes` preservando o sinal da
  quantidade como venda

#### Scenario: Posição em ativo não cadastrado é recusada
- **WHEN** o usuário tenta registrar uma posição em ação cujo ticker não está
  no cadastro de ativos
- **THEN** o sistema recusa o registro com mensagem que identifica o ticker e
  cita a ação de cadastro, em vez de gravar uma posição que a coleta de
  cotações não consegue acompanhar
### Requirement: Validação de entrada
O sistema SHALL rejeitar o registro de uma posição com quantidade igual a
zero ou preço médio menor ou igual a zero, informando o motivo da rejeição.

#### Scenario: Quantidade zero rejeitada
- **WHEN** o usuário tenta registrar uma posição com quantidade = 0
- **THEN** o sistema recusa a gravação e retorna uma mensagem explicando que
  quantidade zero não é uma posição válida

### Requirement: Encerramento de posição
O sistema SHALL permitir encerrar uma posição em aberto marcando
`fechada_em`, preservando o histórico da posição em vez de removê-la.

#### Scenario: Encerrar posição existente
- **WHEN** o usuário encerra uma posição que está com `fechada_em` nulo
- **THEN** o sistema grava o timestamp atual em `fechada_em` e a posição para
  de aparecer nas consultas de posições abertas

### Requirement: Consulta de posições abertas
O sistema SHALL fornecer uma forma de consultar as posições atualmente
abertas, agrupadas por ticker, para ser usada como insumo pelo ETL de
mercado e pela avaliação de estratégia.

#### Scenario: Consultar posições abertas para alimentar o ETL
- **WHEN** o ETL de cotações ou opções precisa saber quais tickers estão em
  carteira
- **THEN** a consulta retorna apenas posições com `fechada_em` nulo,
  refletindo o estado atual do patrimônio
