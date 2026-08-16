## Context

Ver `proposal.md` — Why. O que importa para o desenho:

- `src/config.py` já exige `DATABASE_URL` no ambiente e falha alto quando
  falta; `src/db/connection.py` repassa a string ao `psycopg.connect` sem
  interpretá-la. TLS do Neon é parâmetro da URL (`sslmode=require`), então
  **nenhum código de conexão precisa mudar**.
- `schema.sql` é integralmente idempotente: 19 `IF NOT EXISTS` e nenhum
  `CREATE` desprotegido. As migrações 001 e 002 seguem a mesma regra, fixada
  no `README.md` de `src/db/migrations/`. Isso é o que torna desnecessária
  uma tabela de controle de versão nesta etapa.
- `schema.sql` descreve o estado final e já inclui o que as migrações 001 e
  002 criaram. Num banco vazio, `schema.sql` sozinho basta; rodar as
  migrações depois é inofensivo e mantém o comando correto também para um
  banco antigo.
- Os testes de integração leem `DATABASE_URL` do ambiente, pulam quando o
  banco não responde, usam tickers com prefixo `ZZ` e limpam o que criaram.
- O provisionamento em si (conta, projeto, connection string, secret no
  GitHub) acontece fora do repositório e fora do meu alcance.

## Goals / Non-Goals

**Goals:**

- Dar ao `daily-etl.yml` um banco que ele consiga alcançar.
- Tornar "preparar um banco" um comando reproduzível, igual para a instância
  gerenciada e para o local descartável.
- Deixar claro, no runbook e nos artefatos, quais passos são do usuário.

**Non-Goals:**

- Não migra dado do banco local (decisão do usuário: começar do zero).
- Não cria tabela de controle de versão de migração.
- Não acrescenta ao workflow os passos de avaliação de estratégia e
  relatório — é a pendência seguinte, e misturá-la aqui confundiria a
  validação do banco com a validação do pipeline.
- Não muda `connection.py` nem `config.py`.
- Não automatiza a criação do projeto no Neon por API/Terraform: é uma
  instância só, criada uma vez.

## Decisions

### 1. `schema.sql` primeiro, migrações depois — ambos sempre

O comando aplica `schema.sql` e então cada migração em ordem numérica, sem
verificar o que já existe. É seguro porque tudo é idempotente, e é o que
mantém um único caminho de código para os dois casos que importam: banco
novo (o Neon, agora) e banco existente (o local, ao ser recriado).

*Alternativa considerada:* detectar se o banco está vazio e escolher entre
`schema.sql` e migrações. Descartada: duas trilhas de execução, sendo que a
mais rara — banco parcialmente migrado — seria a menos testada.

*Alternativa considerada:* tabela `schema_migrations`. Descartada com o
usuário: escopo maior do que destravar o Neon exige, e a idempotência já
torna o rerun inofensivo. Vira necessária no dia em que uma migração deixar
de ser idempotente — e aí é uma change própria, com o motivo registrado.

### 2. Falha é total, nunca parcial

Qualquer erro ao aplicar um arquivo interrompe o comando com código não
zero, nomeando o arquivo. Um bootstrap que aplica metade do schema e reporta
sucesso deixaria o banco num estado que ninguém consegue descrever — e o
sintoma apareceria muito depois, como coluna faltando em produção.

Cada arquivo é aplicado em sua própria transação: um `.sql` que falha não
deixa metade de si mesmo aplicado. Não há transação englobando todos os
arquivos, porque o objetivo é diagnóstico ("parou em 003"), não atomicidade
do conjunto — e a idempotência permite corrigir e rodar de novo.

### 3. O relato identifica o alvo, sem a senha

Antes de aplicar qualquer coisa, o comando imprime host e nome da base,
extraídos da URL com o parser da própria `psycopg`/`urllib` — sem a senha.

A razão é operacional: o mesmo comando prepara a instância gerenciada e o
banco descartável, e o modo de falha previsível é rodar no ambiente errado.
Ver o destino antes de aplicar é o que permite abortar a tempo.

Senha fora do relato vale também para a mensagem de erro: string de conexão
completa em log de CI é vazamento de credencial.

### 4. `.env.example` passa a mostrar as duas configurações

Com o Neon como fonte da verdade, o `.env.example` mostrando só
`localhost:5433` induz ao erro. Ele passa a trazer a URL gerenciada como
configuração principal, com `sslmode=require` explícito, e a local comentada
como banco descartável.

`sslmode=require` explícito importa: o `psycopg` usa `prefer` por padrão,
que aceita conexão sem TLS se o servidor oferecer. Contra o Neon isso
funciona por acidente, e o dia em que não funcionar o erro será obscuro.

### 5. Testes de integração continuam apontando para o banco descartável

Eles já se protegem (prefixo `ZZ`, limpeza no fixture, skip quando o banco
não responde), então rodar contra o Neon não corromperia a carteira. Ainda
assim, a recomendação documentada é apontar para o local: escrever e apagar
linhas na base que guarda a carteira real, a cada `pytest`, é risco sem
contrapartida.

Isto fica como convenção documentada, não como trava no código — uma trava
exigiria uma segunda variável de ambiente e um caminho de configuração novo,
desproporcional para uma carteira pessoal.

### 6. Validação por `workflow_dispatch` antes de confiar no cron

O `daily-etl.yml` já expõe `workflow_dispatch`. A validação é rodá-lo à mão
e conferir no banco que a coleta gravou — antes de esperar o cron. O cron
roda uma vez por dia útil; descobrir um erro de secret por ele custaria um
dia por tentativa.

## Risks / Trade-offs

- **O free tier do Neon suspende a instância por inatividade**, e a primeira
  conexão depois disso paga o tempo de religar. → Para um cron diário e uso
  interativo esporádico é irrelevante; o `connect_timeout` que já existe nos
  testes de integração é de 3s e pode precisar de folga no bootstrap. Anotado
  como ponto de atenção na validação, não como bloqueio.

- **Credencial de banco passa a existir em dois lugares** (`.env` local e
  secret do GitHub). → É o mínimo necessário para o Actions escrever.
  Mitigação: a senha nunca aparece em relato nem em erro (decisão 3), e o
  `.env` já está fora do versionamento.

- **Sem controle de versão de migração, uma migração não idempotente
  quebraria o comando em silêncio.** → A regra de idempotência está escrita
  no `README.md` de migrações e vale desde a primeira. O comando não
  consegue verificá-la, então esta é uma disciplina, não uma garantia.
  Registrado como o gatilho para criar `schema_migrations` no futuro.

- **"Começar do zero" significa que a primeira execução do pipeline não terá
  posição nenhuma**, e o relatório sairá vazio até o usuário cadastrar a
  carteira. → Esperado e desejado; o relatório já trata carteira vazia
  explicitamente ("Nenhuma posição aberta").

## Migration Plan

Nenhuma migração de banco nova. A ordem existe porque metade dos passos é do
usuário e a outra metade depende deles:

1. **[usuário]** Criar conta e projeto no Neon; copiar a connection string.
2. Implementar `src/db/bootstrap.py` e seus testes (não dependem do Neon).
3. **[usuário]** Preencher `DATABASE_URL` no `.env` local apontando para o
   Neon e rodar o bootstrap contra a instância nova.
4. **[usuário]** Cadastrar `DATABASE_URL` como secret do repositório.
5. **[usuário]** Disparar o `daily-etl.yml` por `workflow_dispatch` e
   conferir no banco que a coleta gravou.
6. Documentação (`.env.example`, README de migrações, `CLAUDE.md`, runbook).

**Rollback:** apontar `DATABASE_URL` de volta para o `docker-compose`. Como
nada é migrado nem apagado, o banco local continua exatamente como está — o
que também significa que ele permanece disponível como rede de segurança
durante a transição.

## Open Questions

- Neon oferece endpoint com pool de conexões além do direto. Para um cron
  diário de processo único, o direto basta. Deferível: trocar a URL não muda
  requisito nem código.
- Se o dashboard somente leitura (P2 do roadmap) for construído, ele vai
  querer credencial de leitura separada. Não bloqueia nada aqui — pertence à
  change do dashboard.
