## Purpose

Preparar um banco alvo para receber a carteira, aplicando schema e migrações
de forma idempotente e reproduzível, para que provisionar uma instância nova
— gerenciada ou local — deixe de depender de comandos decorados e para que
os dois ambientes permaneçam com a mesma estrutura.

## ADDED Requirements

### Requirement: Aplicação idempotente de schema e migrações
O sistema SHALL oferecer uma operação executável que aplique, ao banco
indicado pela configuração de conexão, a definição de schema do projeto e em
seguida as migrações existentes em ordem crescente de número.

A operação SHALL ser idempotente: executada sobre um banco já preparado, ela
SHALL concluir com sucesso sem alterar estrutura nem dado existente.

A operação SHALL NOT remover, truncar ou sobrescrever dado já presente no
banco alvo.

#### Scenario: Banco vazio recebe a estrutura completa
- **WHEN** a operação é executada contra um banco sem nenhuma tabela do
  projeto
- **THEN** ao final existem todas as tabelas do schema, e a operação relata
  o que aplicou

#### Scenario: Segunda execução não altera nada
- **WHEN** a operação é executada duas vezes seguidas contra o mesmo banco
- **THEN** a segunda execução conclui com sucesso e a estrutura permanece
  igual à deixada pela primeira

#### Scenario: Dado existente é preservado
- **WHEN** a operação é executada contra um banco que já contém posições e
  cotações registradas
- **THEN** esses registros permanecem intactos após a execução

#### Scenario: Migrações são aplicadas em ordem
- **WHEN** existem várias migrações pendentes
- **THEN** elas são aplicadas em ordem crescente de número, e a ordem é
  visível no relato da execução

### Requirement: Falha explícita quando o alvo não é alcançável
Quando o banco alvo não puder ser alcançado — configuração ausente, destino
inacessível ou credencial recusada — o sistema SHALL falhar com erro
explícito que identifique a causa, e SHALL encerrar com código de saída
diferente de zero.

O sistema SHALL NOT relatar sucesso parcial: uma execução que não conseguiu
aplicar tudo o que se propôs SHALL ser reportada como falha.

#### Scenario: Configuração de conexão ausente
- **WHEN** a operação é executada sem que a configuração de conexão esteja
  definida
- **THEN** o sistema falha com mensagem que identifica a variável ausente e
  encerra com código diferente de zero, sem tentar conectar

#### Scenario: Banco inacessível
- **WHEN** a configuração aponta para um destino que não responde
- **THEN** o sistema falha identificando o destino e o erro de conexão, em
  vez de encerrar em silêncio como se nada houvesse a aplicar

#### Scenario: Falha no meio da aplicação
- **WHEN** uma das migrações falha durante a execução
- **THEN** o sistema reporta qual arquivo falhou e por quê, e encerra com
  código diferente de zero

### Requirement: Alvo da operação é confirmado antes de aplicar
O sistema SHALL identificar, no relato da execução, qual banco está sendo
preparado, sem expor a credencial contida na configuração de conexão.

Isso existe porque a mesma operação prepara tanto a instância gerenciada
quanto o banco local descartável, e aplicar no ambiente errado por engano é
o modo de falha previsível desta operação.

#### Scenario: Execução identifica o destino
- **WHEN** a operação é executada
- **THEN** o relato indica o servidor e a base de dados alvo antes de
  aplicar qualquer arquivo

#### Scenario: Credencial não aparece no relato
- **WHEN** a configuração de conexão contém usuário e senha
- **THEN** a senha não aparece em nenhuma linha do relato nem em mensagem de
  erro
