# infrastructure-delivery Specification

## Purpose

Permitir criar, alterar e recuperar a infraestrutura hospedada de forma
reproduzível, revisável e sem credenciais permanentes no sistema de CI/CD.

## Requirements

### Requirement: Infraestrutura é declarativa e reproduzível
Todos os recursos necessários para executar a aplicação em produção SHALL ser
declarados como código versionado, incluindo identidades, rede, compute,
registro de imagens, agendamentos, observabilidade, segredos referenciados e
proteção de acesso. O deploy SHALL NOT depender de configuração manual não
documentada no console.

#### Scenario: Ambiente é recriado
- **WHEN** a infraestrutura é aplicada em uma conta ou ambiente vazio com as
  entradas exigidas
- **THEN** os recursos da aplicação são criados de forma reproduzível e as
  únicas ações manuais restantes são declaradas como pré-requisitos externos

#### Scenario: Pull request altera infraestrutura
- **WHEN** uma mudança de infraestrutura é proposta
- **THEN** a revisão apresenta o plano antes de qualquer aplicação

### Requirement: CI/CD usa identidade federada
O sistema de CI/CD SHALL autenticar na AWS por identidade federada de curta
duração, com permissões distintas para plano, publicação de imagem, migração e
deploy. O repositório SHALL NOT armazenar chave de acesso AWS permanente.

#### Scenario: Workflow de deploy inicia
- **WHEN** um workflow autorizado solicita credenciais AWS
- **THEN** ele recebe credenciais temporárias limitadas ao ambiente e à função
  do job

### Requirement: Testes usam banco descartável
O pipeline de CI SHALL executar testes que escrevem dados somente contra um
Postgres descartável criado para a execução e SHALL NOT usar o Neon de produção
como banco de testes.

#### Scenario: Pull request executa testes de integração
- **WHEN** os testes são iniciados no CI
- **THEN** `DATABASE_URL` aponta para o banco efêmero do job e nenhuma
  credencial de produção é disponibilizada

### Requirement: Artefatos de aplicação são imutáveis
Cada deploy SHALL referenciar imagens por digest ou identificador imutável
produzido de um commit testado. O mesmo artefato SHALL ser promovido sem rebuild
entre validação e produção.

#### Scenario: Nova versão é implantada
- **WHEN** um commit aprovado é promovido
- **THEN** API e tarefas referenciam os digests validados para aquela versão

#### Scenario: Rollback é necessário
- **WHEN** uma versão implantada apresenta regressão
- **THEN** o deploy consegue restaurar os digests e definições anteriores sem
  reconstruir a imagem antiga

### Requirement: Migração tem gate único
Cada release SHALL executar as migrações idempotentes uma única vez, de forma
serializada, antes de direcionar os runtimes novos ao schema esperado. Uma
migração com falha SHALL impedir a promoção dos runtimes, sem executar rollback
destrutivo automático do banco.

#### Scenario: Dois deploys concorrem
- **WHEN** dois workflows tentam migrar o mesmo ambiente
- **THEN** apenas um adquire o gate de migração e o outro aguarda ou termina sem
  aplicar as migrações em paralelo

#### Scenario: Migração falha
- **WHEN** o comando de bootstrap retorna erro
- **THEN** a release não atualiza API nem tarefas e preserva os runtimes
  anteriores

### Requirement: Cutover elimina agendamento duplicado
O processo de promoção SHALL verificar que EventBridge é o único agendador
operacional ativo antes de declarar o cutover concluído. Cron do GitHub Actions
e timers systemd de produção SHALL estar desativados, com procedimento explícito
para rollback.

#### Scenario: Agendador legado ainda está ativo
- **WHEN** a verificação de cutover detecta cron ou timer de produção capaz de
  disparar o mesmo fluxo
- **THEN** o cutover não é declarado concluído e o risco de execução duplicada
  é reportado

### Requirement: Frontend e API são promovidos de forma compatível
O deploy SHALL publicar o contrato OpenAPI usado pelo cliente tipado e SHALL
coordenar a origem CloudFront, hostname e política de acesso esperados pelo
frontend antes de liberar o tráfego de produção. O frontend SHALL ser publicado
por identidade federada própria, sem chave AWS permanente, e a invalidação do
shell SHALL ocorrer somente depois do upload completo.

#### Scenario: Contrato incompatível com o frontend
- **WHEN** a checagem tipada do frontend falha contra o contrato a promover
- **THEN** a promoção coordenada é bloqueada antes da liberação de tráfego

#### Scenario: Bundle é publicado
- **WHEN** um commit aprovado do frontend conclui lint, tipos e build
- **THEN** o workflow envia os artefatos ao armazenamento AWS pela role OIDC
  restrita e invalida o shell da distribuição depois do upload

#### Scenario: Publicação falha no meio
- **WHEN** o upload de qualquer parte do bundle falha
- **THEN** o workflow não invalida o shell como se a nova versão estivesse
  completa
