# Runbook — Postgres gerenciado (Neon)

Como provisionar, preparar e validar o banco que guarda a carteira. Serve
tanto para a primeira vez quanto para refazer o processo se a instância for
perdida.

## Por que existe um banco gerenciado

O `daily-etl.yml` roda no GitHub Actions, que não alcança `localhost:5433`.
Sem um banco acessível pela internet, todo passo do workflow falha na
conexão — o cron existia desde o início do projeto e nunca produziu efeito.

## Quem é quem

| Banco | Papel | Perder é grave? |
|---|---|---|
| Neon (`sa-east-1`, free tier) | **Fonte da verdade.** Posições, cotações, sugestões, eventos de resultado. É o que o Actions escreve. | Sim — refaça pelo runbook e recadastre as posições |
| `docker compose up -d db` | **Descartável.** Teste de integração e experimentação. | Não |

A carteira real **não** vive no banco local. Se você apontar `DATABASE_URL`
para `localhost` e vir um banco vazio, é isso: não é perda de dado.

## Provisionar do zero

1. Criar conta em https://neon.tech e um projeto, free tier, região
   `sa-east-1` (São Paulo) para menor latência.
2. Copiar a **connection string do endpoint direto** (não a do pooler — o
   pipeline é um processo só, por execução diária, e o direto basta). Ela
   contém a senha e não é exibida de novo.
3. Conferir que a URL termina com `?sslmode=require`. Acrescente se o painel
   não incluir: o `psycopg` usa `sslmode=prefer` por padrão, que aceita
   conexão sem TLS. Contra o Neon funciona por acidente, e o dia em que não
   funcionar o erro será obscuro.
4. Colar em `DATABASE_URL` no `.env` local (veja `.env.example`).
5. Preparar o schema:

   ```bash
   python -m src.db.bootstrap --dry-run   # confira o alvo primeiro
   python -m src.db.bootstrap
   ```

   O comando imprime host e base antes de escrever qualquer coisa — é a
   última chance de perceber que a variável aponta para o banco errado. É
   idempotente: rodar de novo é inofensivo.

6. Conferir que as tabelas subiram e que o banco está vazio:

   ```bash
   python -c "
   from src.db.connection import get_connection
   with get_connection() as c, c.cursor() as cur:
       cur.execute(\"SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1\")
       print([r[0] for r in cur.fetchall()])
   "
   ```

## Ligar ao GitHub Actions

1. Repositório → Settings → Secrets and variables → Actions → New repository
   secret.
2. Nome `DATABASE_URL`, valor igual ao do `.env`. Os outros secrets
   (`BRAPI_TOKEN`, `OPLAB_TOKEN`) já devem estar lá.
3. Actions → "ETL diário" → **Run workflow** (`workflow_dispatch`).
4. **Não confie no verde do workflow.** Confira no banco que a execução
   gravou:

   ```bash
   python -c "
   from src.db.connection import get_connection
   with get_connection() as c, c.cursor() as cur:
       cur.execute('SELECT ticker, preco, coletado_em FROM cotacoes ORDER BY coletado_em DESC LIMIT 5')
       print(cur.fetchall())
   "
   ```

   Sem posição cadastrada não há o que coletar, e a execução passa sem
   gravar nada — cadastre pelo menos uma posição antes de validar.

O `workflow_dispatch` existe justamente para isto: o cron roda uma vez por
dia útil, e descobrir um secret errado por ele custaria um dia por
tentativa.

## Cadastrar a carteira

A instância sobe vazia por decisão — nada foi migrado do banco local, para
não carregar resíduo de experimentação.

**A ordem importa.** `cotacoes`, `opcoes` e `noticias` têm chave estrangeira
para `ativos`: sem cadastrar o ativo primeiro, o registro de posição é
recusado e a coleta de cotações não grava nada.

```bash
# 1. o ativo (o nome é seu; o sistema não deriva do ticker)
python -m src.assets.manage add PETR4 "Petrobras PN" acao --cnpj-raiz 33000167

# 2. a posição
python -m src.portfolio.manage add PETR4 ACAO 100 32.50

# 3. a data de resultado, se quiser destravar o critério de earnings
python -m src.earnings.manage add PETR4 AAAA-MM-DD --sessao AFTER_CLOSE --origem <url do RI>
python -m src.earnings.ingest --tickers PETR4   # registrar não é consolidar
```

`--cnpj-raiz` é opcional para a coleta de cotações, mas é o que permite ao
`CvmProvider` mapear o dump da CVM para o ticker. Sem ele, aquele provider
avisa e pula o ativo.

## Rodar os testes sem tocar na carteira

Os testes de integração escrevem no banco de `DATABASE_URL`. Eles se
protegem (tickers com prefixo `ZZ`, limpeza no fixture), mas não há razão
para exercitar isso na base real:

```bash
docker compose up -d db
DATABASE_URL=postgresql://opcoes_ia:opcoes_ia@localhost:5433/opcoes_ia pytest
```

Se o banco local estiver zerado, prepare-o com o mesmo comando de bootstrap
apontando para ele.

## Se a instância for perdida

Refaça "Provisionar do zero" e "Cadastrar a carteira". O histórico de
cotações se reconstrói na próxima coleta; as sugestões antigas não voltam,
e isso é aceitável — sugestão é registro de decisão de um dia, não estado
da carteira.

## Voltar atrás

Apontar `DATABASE_URL` para o `docker-compose`. Nada foi apagado do banco
local durante a transição, então ele continua utilizável como rede de
segurança — mas lembre que ele não recebe o que o Actions grava.
