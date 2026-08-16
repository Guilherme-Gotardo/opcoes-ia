> **Tarefas marcadas `[usuário]` só podem ser executadas por você** — criar
> conta, copiar credencial e cadastrar secret acontecem fora do repositório.
> O agente para nelas e aguarda confirmação.

## 1. Provisionar a instância

- [x] 1.1 **[usuário]** Criar conta no Neon (https://neon.tech) e um projeto
      para este sistema, na região mais próxima (`aws-us-east-1` ou
      `aws-sa-east-1`), no free tier.
- [x] 1.2 **[usuário]** Copiar a connection string do endpoint direto e
      guardá-la — ela contém a senha e não será exibida de novo.
- [x] 1.3 **[usuário]** Confirmar que a URL traz `sslmode=require`;
      acrescentar se o painel não incluir (`design.md`, decisão 4: o
      `psycopg` usa `prefer` por padrão, que aceita conexão sem TLS).

## 2. Comando de bootstrap de schema

- [x] 2.1 Criar `src/db/bootstrap.py` com CLI no padrão dos demais módulos
      executáveis do projeto (`argparse`, `main(argv=None)`, código de saída
      explícito).
- [x] 2.2 Implementar a identificação do alvo (host e nome da base) impressa
      **antes** de aplicar qualquer arquivo, com a senha removida (spec
      `database-bootstrap`, requisito "Alvo da operação é confirmado antes de
      aplicar").
- [x] 2.3 Implementar a aplicação de `src/db/schema.sql` seguida das
      migrações de `src/db/migrations/` em ordem crescente de número,
      relatando cada arquivo aplicado (`design.md`, decisão 1).
- [x] 2.4 Aplicar cada arquivo em sua própria transação, para que um `.sql`
      que falhe não deixe metade de si mesmo aplicado (`design.md`,
      decisão 2).
- [x] 2.5 Implementar a falha explícita com código diferente de zero para:
      `DATABASE_URL` ausente, destino inacessível e erro ao aplicar um
      arquivo — nomeando a causa e, no último caso, o arquivo (spec,
      requisito "Falha explícita quando o alvo não é alcançável").
- [x] 2.6 Garantir que a senha não apareça em nenhuma linha de relato nem em
      mensagem de erro (spec, cenário "Credencial não aparece no relato").
- [x] 2.7 Testes sem banco: ordenação numérica das migrações (incluindo que
      `010` vem depois de `009`), extração de host/base a partir da URL,
      senha ausente do relato, `DATABASE_URL` ausente falhando com código
      não zero.
- [x] 2.8 Teste de integração contra o Postgres local (pulado sem banco, no
      padrão de `tests/test_earnings_integration.py`): bootstrap sobre banco
      preparado conclui sem erro e preserva uma linha previamente inserida
      (spec, cenários de idempotência e preservação de dado).

## 3. Preparar o banco gerenciado

- [x] 3.1 **[usuário]** Apontar `DATABASE_URL` do `.env` local para o Neon.
- [x] 3.2 Rodar `python -m src.db.bootstrap` contra a instância nova e
      conferir no relato que o alvo é o host do Neon, não `localhost`.
- [x] 3.3 Conferir que todas as tabelas do `schema.sql` existem na instância
      e que ela está vazia de dado de carteira (decisão do usuário: começar
      do zero).
- [x] 3.4 Rodar o bootstrap uma segunda vez e confirmar que conclui sem erro
      e sem alterar nada (spec, cenário "Segunda execução não altera nada").

## 4. Automação

- [ ] 4.1 **[usuário]** Cadastrar `DATABASE_URL` em Settings > Secrets and
      variables > Actions do repositório, com a connection string do Neon.
- [ ] 4.2 **[usuário]** Disparar o `daily-etl.yml` por `workflow_dispatch` e
      acompanhar a execução.
- [ ] 4.3 Conferir no banco gerenciado que a execução gravou de fato —
      cotações coletadas e o passo de consolidação concluído — em vez de
      confiar no verde do workflow (`design.md`, decisão 6).
- [x] 4.4 Atualizar o comentário de pré-requisito no rodapé do
      `daily-etl.yml`, que hoje descreve o banco gerenciado como pendência
      em aberto ("ex: Supabase/Neon/RDS").

## 5. Documentação

- [x] 5.1 Atualizar `.env.example`: URL do Neon como configuração principal
      com `sslmode=require` explícito, e a local comentada, identificada como
      banco descartável (`design.md`, decisão 4).
- [x] 5.2 Atualizar a seção "Aplicar" do `src/db/migrations/README.md` para
      citar o comando de bootstrap, substituindo o `psql` manual e a nota
      "ainda não há runner automático".
- [x] 5.3 Registrar no README de migrações que a idempotência deixou de ser
      só convenção e virou pré-requisito do comando — e que o dia em que uma
      migração não puder ser idempotente é o gatilho para criar controle de
      versão aplicada (`design.md`, riscos).
- [x] 5.4 Atualizar `CLAUDE.md`: comando de bootstrap em "Comandos úteis",
      e o estado atual registrando que o Neon é a fonte da verdade e que o
      `docker compose` passou a ser banco descartável de teste.
- [x] 5.5 Documentar em `CLAUDE.md` que os testes de integração devem apontar
      para o banco descartável, não para o gerenciado (`design.md`,
      decisão 5) — convenção documentada, não trava no código.
- [x] 5.6 Escrever o runbook de provisionamento em `docs/`, com os passos do
      usuário e como refazer o processo se a instância for perdida.

## 6. Validação de ponta a ponta

- [x] 6.1 Rodar `pytest` completo apontando para o banco local descartável e
      confirmar que a suíte segue verde, incluindo os testes de integração.
- [x] 6.2 Com `DATABASE_URL` no Neon, cadastrar uma posição por
      `python -m src.portfolio.manage`, rodar `fetch_quotes`, `ingest` e o
      relatório, e confirmar que o fluxo funciona igual ao local.
- [x] 6.3 Confirmar que o banco local continua intacto e utilizável após a
      troca — é a rede de segurança do rollback (`design.md`, Migration
      Plan).
