## Why

O `daily-etl.yml` não tem para onde escrever. `DATABASE_URL` aponta hoje
para o Postgres do `docker-compose`, que só existe na máquina do usuário —
o GitHub Actions não alcança `localhost:5433`. O cron está agendado desde o
início do projeto e nunca produziu efeito nenhum: todo passo do workflow
falharia na conexão.

Isso ficou mais concreto com a change anterior. O passo
`Consolidar datas de resultado` que acabou de entrar no workflow é o elo que
torna a agenda de resultados consultável pela avaliação — e ele também não
tem banco. Automatizar a coleta, a consolidação e (na pendência seguinte) a
avaliação de estratégia só faz sentido depois que existir um banco acessível
pela internet.

Além disso, subir o schema num banco novo hoje é um `psql` decorado: o
`README.md` de `src/db/migrations/` diz explicitamente que "ainda não há
runner automático". Provisionar um banco gerenciado à mão, uma vez, é
tolerável; repetir isso a cada migração futura em dois ambientes é como se
perde a paridade entre eles.

## What Changes

- **Neon vira a fonte da verdade** da carteira: posições, sugestões,
  cotações e eventos de resultado passam a viver na instância gerenciada,
  que é o que o Actions escreve e o que o usuário opera.
- **O Postgres do `docker-compose` vira banco descartável**, para teste de
  integração e experimentação. Pode ser derrubado e recriado sem perda —
  deixa de guardar carteira real.
- **Começar do zero.** Nada é migrado do banco local: o schema sobe vazio e
  as posições são cadastradas por `src/portfolio/manage.py` quando o usuário
  quiser. Sem `pg_dump`, sem risco de carregar resíduo de experimentação.
- **Novo comando de bootstrap de schema** (`python -m src.db.bootstrap`),
  que aplica `schema.sql` e as migrações em ordem contra o `DATABASE_URL`
  configurado, relatando o que aplicou. Serve tanto para preparar o Neon
  quanto para recriar o banco local descartável.
- **`.env.example` documenta o formato do Neon**, com TLS explícito, e passa
  a mostrar as duas configurações (gerenciada e local) em vez de só a local.
- **Runbook de provisionamento** com os passos que só o usuário pode
  executar, e a validação por `workflow_dispatch` antes de confiar no cron.
- **BREAKING (operacional, não de API):** depois desta change,
  `DATABASE_URL` apontando para o banco local passa a significar "banco
  descartável". Quem esperar encontrar a carteira real ali vai achar um
  banco vazio.

## Capabilities

### New Capabilities

- `database-bootstrap`: aplicação idempotente e reproduzível do schema e das
  migrações a um banco alvo, com falha explícita quando o alvo não é
  alcançável e relato do que foi aplicado.

### Modified Capabilities

Nenhuma. Onde o banco mora e como o schema chega nele não altera nenhum
requisito de comportamento das capabilities existentes — coleta, avaliação,
relatório e calendário continuam com o mesmo contrato, sobre outro
endereço.

## Impact

- **Código:** novo `src/db/bootstrap.py`. `src/db/connection.py` e
  `src/config.py` permanecem como estão — `DATABASE_URL` já é lida do
  ambiente e repassada ao psycopg, e o TLS do Neon é questão de string de
  conexão, não de código.
- **Configuração:** `.env.example`; `DATABASE_URL` como secret do repositório
  no GitHub.
- **Banco:** nenhuma migração nova. `schema.sql` já é idempotente (19
  `IF NOT EXISTS`, nenhum `CREATE` desprotegido) e já contém o resultado das
  migrações 001 e 002.
- **Documentação:** `README.md` de `src/db/migrations/` (a seção "Aplicar"
  passa a citar o comando em vez do `psql`), `CLAUDE.md` (comandos e estado
  atual), e o runbook de provisionamento.
- **Ações fora do repositório, que só o usuário pode executar:** criar a
  conta e o projeto no Neon, copiar a connection string e cadastrar o secret
  no GitHub. As tarefas correspondentes estão marcadas como tais.
- **Fora de escopo:** tabela de controle de versão aplicada
  (`schema_migrations`) — a idempotência de `schema.sql` e das migrações
  torna o rerun inofensivo, e o controle de versão é escopo maior do que
  destravar o Neon exige. Também fora: adicionar ao workflow os passos de
  avaliação de estratégia e relatório, que são a pendência seguinte do
  roadmap.
