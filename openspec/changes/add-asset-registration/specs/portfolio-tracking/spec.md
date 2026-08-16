## MODIFIED Requirements

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
