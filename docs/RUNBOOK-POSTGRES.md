# Runbook — Postgres gerenciado (Neon)

Como provisionar, preparar e validar o banco que guarda a carteira. Serve
tanto para a primeira vez quanto para refazer o processo se a instância for
perdida.

## Por que existe um banco gerenciado

Lambda, Fargate e o job de migração do GitHub Actions não alcançam
`localhost:5433`. O Neon permite que runtimes efêmeros compartilhem a mesma
fonte de verdade sem manter servidor de aplicação ligado.

## Quem é quem

| Banco | Papel | Perder é grave? |
|---|---|---|
| Neon (`sa-east-1`, free tier) | **Fonte da verdade.** Posições, mercado, execuções, sugestões e relatórios. Lambda/Fargate leem e escrevem aqui. | Sim — refaça pelo runbook e recadastre as posições |
| `docker compose up -d db` | **Descartável.** Teste de integração e experimentação. | Não |

A carteira real **não** vive no banco local. Se você apontar `DATABASE_URL`
para `localhost` e vir um banco vazio, é isso: não é perda de dado.

## Provisionar do zero

1. Criar conta em https://neon.tech e um projeto, free tier, região
   `sa-east-1` (São Paulo) para menor latência.
2. Copiar as connection strings direta e pooled. Migração usa a direta sob lock
   de sessão; API e tarefas usam `-pooler` para limitar conexões serverless.
   Ambas contêm senha e não entram no repositório.
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

## Ligar aos runtimes hospedados

1. Grave a URL **direta** como `DATABASE_URL` no GitHub Environment
   `Principal`; somente o job de migração a recebe. O nome é o mesmo dos
   containers de aplicação, mas o valor não: aqui é o host **sem** `-pooler`,
   porque pelo pooler o advisory lock da migração deixa de excluir dois
   bootstraps simultâneos. `src/db/bootstrap.py` recusa o endpoint pooled.
2. Grave a URL pooled nos containers `opcoes-ia/prod/api` e
   `opcoes-ia/prod/operations` do Secrets Manager conforme
   `docs/RUNBOOK-CLOUD.md`.
3. Execute o release e depois uma task manual com schedules desabilitados.
4. **Não confie apenas no verde do workflow.** Confira no banco que a execução
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

GitHub Actions não roda cron operacional. EventBridge Scheduler e o unico
agendador de producao depois do cutover.

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
