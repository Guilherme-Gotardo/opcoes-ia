# opcoes-ia

Plataforma pessoal de acompanhamento de carteira (ações + opções, B3) com agentes de IA
para coleta de dados, análise de mercado e sugestão de estratégias (venda coberta de
call/put como estratégia inicial; travas e condor planejados para fases futuras).

> **Escopo do MVP:** espelho de carteira (sem execução real de ordens). O objetivo é
> refletir com precisão o que você tem alocado e sugerir ações, nunca executá-las
> automaticamente.

## Visão geral

```
S3 privado -> CloudFront -> Cognito -> API Gateway -> Lambda/FastAPI -> Neon pooled
                                                  |
EventBridge Scheduler -> ECS Fargate operations --+
                         |-> ETL / earnings / estratégia determinística
                         |-> QuantLib / relatório Anthropic / notificação
                         +-> CloudWatch EMF + SNS
```

Produção usa imagens imutáveis no ECR, Terraform em state S3 e segredos
injetados pelo AWS Secrets Manager. Os schedules nascem desabilitados e o
cutover exige retirar timers locais. Veja `docs/RUNBOOK-CLOUD.md`.

Veja `docs/ARQUITETURA.md` para o detalhamento de cada componente e as decisões de design.

## Como continuar este projeto

Este repositório foi pensado para ser desenvolvido com o **Claude Code**, rodando os
agentes definidos em `.claude/agents/`. Um `CLAUDE.md` na raiz orienta qualquer sessão
do Claude Code sobre convenções, comandos e estado do projeto.

### Setup local

```bash
# 1. Clonar e entrar no projeto
git clone <seu-repo> opcoes-ia && cd opcoes-ia

# 2. Ambiente Python
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Variáveis de ambiente (chaves de API)
cp .env.example .env
# edite .env com suas chaves: OPLAB_TOKEN, BRAPI_TOKEN, DATABASE_URL etc.

# 4. Banco de dados local
docker compose up -d db
psql "$DATABASE_URL" -f src/db/schema.sql

# 5. Rodar o primeiro ETL manualmente
python -m src.etl.fetch_quotes
python -m src.etl.fetch_options

# 6. Abrir com Claude Code para orquestrar os agentes
claude
```

`requirements.txt` instala o lock completo de desenvolvimento. Os runtimes de
produção são separados e reproduzíveis em Python 3.12/Linux amd64:

```bash
pip install --require-hashes -r requirements/api.lock
pip install --require-hashes -r requirements/operations.lock
```

Os arquivos `.in` em `requirements/` registram somente dependências diretas. Os
`.lock` incluem toda a árvore transitiva, versões exatas e hashes, gerados com
`uv pip compile` para a plataforma dos containers. `pytest`, `uvicorn` e o
`httpx` usado diretamente pelo `TestClient` ficam no lock de desenvolvimento;
o lock operacional ainda contém `httpx` transitivamente porque o SDK Anthropic
o usa em runtime. O procedimento exato de atualização está em
`requirements/README.md`.

### Estrutura

```
opcoes-ia/
├── CLAUDE.md                  # instruções para o Claude Code nesta base
├── .claude/agents/            # subagentes (Claude Code)
├── skills/                    # skills reutilizáveis (regras de estratégia)
├── src/etl/                   # coleta de cotações, opções e notícias
├── src/db/                    # schema e models
├── .github/workflows/         # CI, plano Terraform e release
├── infra/                     # AWS serverless declarada em Terraform
└── docs/ARQUITETURA.md        # decisões de arquitetura
```

## Roadmap

- [x] Fase 0 — Scaffold do projeto, schema de dados, agentes iniciais
- [ ] Fase 1 — ETL de cotações/opções + espelho de carteira (input manual ou via OpLab)
- [ ] Fase 2 — Agente de análise (IV rank, notícias) + relatório diário
- [ ] Fase 3 — Agente de estratégia: venda coberta (call/put)
- [x] Fase 4 — Dashboard e API autenticada (leitura + escrituração de carteira)
- [ ] Fase 5 — Travas e condor
