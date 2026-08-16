# Migrações de banco

Convenção deste diretório (regra 4 do `CLAUDE.md`: migrações sempre aqui,
nunca editando `schema.sql` retroativamente depois que o schema já está em
produção pessoal).

## Nomes

```
NNN_descricao_curta.sql
```

`NNN` é um contador de três dígitos, sequencial e nunca reaproveitado.
A ordem de aplicação é a ordem numérica dos arquivos.

## Regras

1. **Toda migração é aditiva e idempotente.** Use `CREATE TABLE IF NOT
   EXISTS`, `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`.
   Rodar duas vezes precisa ser inofensivo.

   Isto deixou de ser só convenção: `src/db/bootstrap.py` aplica
   `schema.sql` e **todas** as migrações a cada execução, sem verificar o
   que já foi aplicado. É a idempotência que torna isso seguro, e o comando
   não tem como conferi-la — é disciplina, não garantia. O dia em que uma
   migração não puder ser idempotente é o gatilho para criar controle de
   versão aplicada (`schema_migrations`), numa change própria com o motivo
   registrado.
2. **Nunca destrua dado numa migração.** `DROP`/`ALTER ... TYPE` que
   perdem informação exigem uma migração de cópia antes, e uma decisão
   registrada na change correspondente.
3. **`schema.sql` acompanha, para bancos novos.** Toda tabela criada aqui
   também entra em `schema.sql`, para que um banco criado do zero saia
   igual a um migrado. O `schema.sql` descreve o estado final; este
   diretório descreve o caminho.

## Aplicar

```bash
# mostra o alvo e os arquivos, sem escrever nada
python -m src.db.bootstrap --dry-run

# aplica schema.sql + migrações, em ordem, no banco de DATABASE_URL
python -m src.db.bootstrap
```

O comando imprime host e base **antes** de aplicar qualquer arquivo (sem a
senha): o modo de falha previsível é rodar no banco errado, e ver o destino
a tempo é o que permite abortar. Falha em qualquer arquivo interrompe com
código não zero, nomeando o arquivo — nunca sucesso parcial.

Serve tanto para o Postgres gerenciado quanto para recriar o banco local
descartável (`docker compose up -d db`). Ver `docs/RUNBOOK-POSTGRES.md`.
