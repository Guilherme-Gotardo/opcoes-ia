## Why

**Nada no projeto insere em `ativos`.** Não existe `INSERT INTO ativos` em
nenhum módulo, nem seed em `schema.sql`, nem nas migrações. Mas três tabelas
dependem dela por chave estrangeira: `cotacoes.ticker`,
`opcoes.ticker_objeto` e `noticias.ticker`.

O efeito é que **o ETL não funciona numa base nova**. Comprovado no Neon em
2026-08-16, logo após o bootstrap do schema:

```
Falha ao coletar cotação de VALE3: violates foreign key constraint
"cotacoes_ticker_fkey"
DETAIL: Key (ticker)=(VALE3) is not present in table "ativos".
Cotações atualizadas: 0/2 tickers.
```

O banco local nunca expôs isso porque as linhas foram inseridas à mão em
alguma sessão anterior — a mesma razão pela qual `cnpj_raiz` já estava
preenchido para cinco tickers. Ou seja: **o caminho de onboarding do projeto
está quebrado desde o início** e só não aparecia porque ninguém tinha subido
um banco do zero.

A única orientação existente sobre como popular a tabela é uma mensagem de
aviso dentro do `CvmProvider`, sugerindo
`UPDATE ativos SET cnpj_raiz = '33000167' WHERE ticker = 'PETR4';` — um
`UPDATE` cru numa linha que o próprio projeto não sabe criar.

Além do ETL, `cnpj_raiz` é o que permite ao `CvmProvider` mapear o dump da
CVM para os tickers da carteira. Sem cadastro, o provider avisa e pula, e o
sintoma final é "esse ativo nunca tem resultado" — indistinguível de
cobertura real.

## What Changes

- **Função de domínio para registrar um ativo** (ticker, nome, tipo e
  `cnpj_raiz` opcional), com validação explícita e correção idempotente de um
  ativo já cadastrado.
- **CLI `python -m src.assets.manage`** (`add` / `list`), no padrão de
  `src/portfolio/manage.py` e `src/earnings/manage.py`.
- **Erro acionável quando o ticker não está cadastrado.** Registrar posição
  em ticker desconhecido passa a falhar nomeando o comando que resolve, em
  vez de gravar uma posição que o ETL não consegue acompanhar. A coleta de
  cotações passa a reportar "ativo não cadastrado" em vez de vazar a violação
  de chave estrangeira do Postgres.
- **A orientação de `cnpj_raiz` deixa de ser um `UPDATE` cru** — o aviso do
  `CvmProvider` passa a citar o comando.
- **Nenhum nome de ativo é inventado.** Cadastrar exige o nome informado por
  quem cadastra; o sistema não deriva nome a partir do ticker nem consulta
  provedor para preencher sozinho (regra 1 do projeto).

## Capabilities

### New Capabilities

- `asset-registry`: cadastro dos ativos que a carteira acompanha — a entidade
  de referência de que cotações, opções e notícias dependem, incluindo o
  identificador que liga o ativo ao dump da CVM.

### Modified Capabilities

- `portfolio-tracking`: registrar posição passa a exigir que o ativo exista,
  falhando com orientação acionável quando não existir.
- `market-data-collection`: a coleta passa a reportar ativo não cadastrado
  como causa nomeada, em vez de deixar vazar o erro de integridade do banco.

## Impact

- **Código:** novo `src/assets/` (domínio + CLI); `src/portfolio/manage.py`
  (validação de ativo existente); `src/etl/fetch_quotes.py` (mensagem de
  erro); `src/earnings/providers/cvm.py` (texto do aviso).
- **Banco:** nenhuma migração. `ativos` já existe desde o `schema.sql`
  inicial e ganhou `cnpj_raiz` na migração 002.
- **Documentação:** `CLAUDE.md` (comandos e a pendência de `cnpj_raiz`, hoje
  registrada como item aberto), `docs/RUNBOOK-POSTGRES.md` (o passo de
  cadastrar a carteira precisa vir depois de cadastrar os ativos).
- **Dependente:** a interface planejada em seguida vai chamar a mesma função
  de domínio; é por isso que esta change vem antes.
- **Fora de escopo:** buscar nome ou CNPJ automaticamente de um provedor
  (a Brapi expõe `get_stock_profile`, mas preencher sozinho seria assumir que
  o ticker digitado é o pretendido); e remoção de ativo, que exigiria decidir
  o que fazer com o histórico de cotações que aponta para ele.
