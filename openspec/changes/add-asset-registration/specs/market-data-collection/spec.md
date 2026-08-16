## MODIFIED Requirements

### Requirement: Isolamento de falha por ticker
O sistema SHALL continuar a coleta dos demais tickers quando um ticker
específico falhar, registrando a falha daquele ticker sem interromper o
restante nem omitir o erro do resumo final.

Quando a falha for causada por ativo não cadastrado, o sistema SHALL
reportá-la como tal, nomeando o ticker e a ação que resolve, e SHALL NOT
expor apenas o erro de integridade do banco de dados — a mensagem crua não
diz ao usuário o que fazer.

#### Scenario: Um ticker falha, outros continuam
- **WHEN** a coleta de opções falha para um ticker específico da carteira
- **THEN** os demais tickers continuam sendo coletados normalmente e o
  ticker que falhou aparece listado como falha no resumo da execução

#### Scenario: Ticker sem ativo cadastrado
- **WHEN** a coleta de cotações encontra um ticker que não está no cadastro
  de ativos
- **THEN** a falha reportada identifica o ticker como ativo não cadastrado e
  cita a ação de cadastro, em vez de reproduzir a violação de chave
  estrangeira do banco
