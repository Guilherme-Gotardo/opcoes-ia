## MODIFIED Requirements

### Requirement: Segredos são injetados em runtime
O sistema SHALL armazenar credenciais fora do código, das imagens e dos planos
de infraestrutura legíveis, e SHALL entregar a cada runtime somente os segredos
necessários para sua função. O sistema SHALL NOT registrar valores secretos em
logs. Credenciais de provedores externos, incluindo a credencial de envio de
e-mail, SHALL ser gravadas por canal administrativo fora da infraestrutura como
código; a infraestrutura declara o continente do segredo e quem pode lê-lo,
nunca o seu valor.

#### Scenario: Imagem publicada no registro
- **WHEN** uma imagem de aplicação é construída e publicada
- **THEN** ela não contém URL credenciada do banco, tokens de provedores, chave
  Anthropic nem credenciais SMTP

#### Scenario: API inicia sem credencial do agente
- **WHEN** a API serverless é iniciada
- **THEN** ela recebe somente as credenciais necessárias aos endpoints que
  serve e não precisa da chave Anthropic ou da credencial SMTP

#### Scenario: Credencial de envio de e-mail é provisionada
- **WHEN** a identidade de envio de e-mail é criada pela infraestrutura como
  código
- **THEN** o plano e o estado da infraestrutura descrevem a identidade e sua
  política, mas não contêm a chave nem a senha de envio, que são geradas e
  gravadas por canal administrativo separado

#### Scenario: Inventário não secreto é versionado
- **WHEN** servidor, porta, remetente e destinatário do canal de e-mail são
  declarados
- **THEN** eles permanecem no inventário versionado por não serem segredos, e
  nenhum valor de senha acompanha esse inventário
