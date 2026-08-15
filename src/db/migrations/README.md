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
2. **Nunca destrua dado numa migração.** `DROP`/`ALTER ... TYPE` que
   perdem informação exigem uma migração de cópia antes, e uma decisão
   registrada na change correspondente.
3. **`schema.sql` acompanha, para bancos novos.** Toda tabela criada aqui
   também entra em `schema.sql`, para que um banco criado do zero saia
   igual a um migrado. O `schema.sql` descreve o estado final; este
   diretório descreve o caminho.

## Aplicar

```bash
docker compose up -d db
psql "$DATABASE_URL" -f src/db/migrations/001_earnings_events.sql
```

Ainda não há runner automático: a carteira é pessoal e as migrações são
poucas. Se isso mudar, o runner entra aqui e passa a ler a ordem dos
nomes.
