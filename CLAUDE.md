# CLAUDE.md — instruções para sessões do Claude Code neste repositório

## O que é este projeto

Plataforma pessoal de acompanhamento de carteira de ações/opções na B3, com agentes
de IA para coleta de dados, análise e sugestão de estratégias de venda coberta
(covered call/put), evoluindo depois para travas e condor.

**Este projeto NUNCA executa ordens reais.** Todo output de estratégia é uma
*sugestão* registrada no banco, nunca uma ação automática numa corretora.

## Regras de trabalho nesta base

1. **Dados nunca são "lembrados" pelo agente.** Preço, grega ou IV sempre vêm de
   `src/db` (populado pelo ETL) ou de chamada direta à API configurada. Nunca estime
   ou "chute" um valor de mercado.
2. **Separação decisão vs. execução.** Regras de estratégia ficam em
   `skills/covered-options-strategy/SKILL.md` como lógica determinística
   (IV rank mínimo, delta-alvo, dias até vencimento, prêmio mínimo). Agentes de LLM
   contextualizam e explicam — não substituem a regra.
3. **Todo agente novo** vai em `.claude/agents/<nome>.md` com frontmatter
   `name`, `description`, `tools` (liste apenas o necessário) e `model`.
4. **Migrações de banco** sempre em `src/db/migrations/`, nunca editar
   `schema.sql` retroativamente depois que o schema estiver em produção pessoal.
5. **Commits pequenos e descritivos.** Use Conventional Commits
   (`feat:`, `fix:`, `chore:`, `docs:`) — facilita gerar changelog depois.

## Comandos úteis

```bash
# rodar ETL de cotações/opções
python -m src.etl.fetch_quotes
python -m src.etl.fetch_options
python -m src.etl.fetch_news

# rodar testes
pytest

# subir banco local
docker compose up -d db
```

## Onde olhar primeiro em cada tipo de tarefa

- Pedido sobre **fonte de dados / ETL** → `src/etl/`, `docs/ARQUITETURA.md#etl`
- Pedido sobre **schema / carteira** → `src/db/schema.sql`
- Pedido sobre **regra de estratégia** → `skills/covered-options-strategy/SKILL.md`
- Pedido sobre **data de resultado / risco de earnings** → `src/earnings/`.
  A ordem de leitura é `models.py` (invariantes) → `confidence.py` (tiers de
  provedor) → `resolution.py` (conflitos) → `risk.py` (o que o motor de
  opções consome). Regra que atravessa tudo: estimativa nunca sobrescreve
  confirmação
- Pedido sobre **novo agente** → `.claude/agents/`, use `orchestrator.md` como
  referência de como os agentes se conectam
- Pedido sobre **automação diária** → `.github/workflows/daily-etl.yml`

## Estado atual (atualize esta seção conforme o projeto evolui)

- [x] Scaffold inicial criado
- [x] Entrada/encerramento/consulta de posições implementado (`src/portfolio/manage.py`)
- [x] Avaliação de venda coberta implementada e testada com dados sintéticos
      (`src/strategy/covered.py`) — persiste sugestões em `sugestoes`
- [x] Relatório diário implementado (`src/report/daily.py`,
      `reports/<AAAA-MM-DD>.md`)
- [x] Brapi (https://brapi.dev) adotada como único provedor de mercado deste
      MVP; OpLab adiada para change futura (ver decisão 2 do `design.md` da
      change `build-portfolio-mvp-flow`)
- [x] ETL de cotações testado com credenciais reais (`BRAPI_TOKEN`) em
      2026-08-14 — corrigido bug real de mapeamento (`fetch_quotes.py`
      assumia campos no nível raiz do item; a API real aninha em `data`)
- [x] `fetch_quotes.py` redesenhado em 2026-08-15 para 1 request por ticker
      (plano Free só permite 1 ativo por requisição, confirmado contra a
      API real) com isolamento de falha por ticker; validado com carteira
      de 2 tickers reais
- [x] Orçamento diário de requests da Brapi implementado
      (`src/etl/budget.py`, `BRAPI_REQUESTS_DIA_MAXIMO`, default 600/dia
      dentro do limite de 15.000/mês do plano Free) — validado contra o
      banco real
- [x] MCP da Brapi (`https://brapi.dev/api/mcp/mcp`) configurado em
      `.mcp.json` e disponível para o `market-analyst` com uma lista
      restrita de tools (perfil, dividendos, ticker lookup, dados macro —
      deliberadamente sem cotação/opções); conexão validada diretamente
      contra a API, mas o carregamento pelo agente dentro do Claude Code
      ainda não foi exercido de ponta a ponta (normalmente exige nova
      sessão)
- [ ] **Metade das tools do `market-analyst` não funciona no plano Free**
      (testado tool a tool em 2026-08-15): `get_stock_dividends`,
      `get_macro_series`, `get_macro_series_latest`, `get_inflation_data`
      e `get_prime_rate_data` retornam `403` exigindo o plano Startup
      (R$119,99/mês). Só `get_stock_profile` e os lookups de ticker
      respondem 200 (1 ativo por requisição, mesma restrição do
      `fetch_quotes`). A lista de tools em
      `.claude/agents/market-analyst.md` precisa ser podada ou o agente
      precisa tratar 403 como "dado indisponível" explícito
- [x] Banco local (`docker compose up -d db` + `schema.sql`) validado de
      ponta a ponta em 2026-08-14 com posição de teste, cotação real,
      avaliação de estratégia e relatório diário — ver tarefa 6.1 da change
      `build-portfolio-mvp-flow` para detalhes e o bug de fuso horário
      (UTC vs. local) corrigido em `report/daily.py`
- [ ] `fetch_options.py` ainda não trocado de OpLab para os endpoints reais
      de opções da Brapi — bloqueado no plano Free do usuário: `403
      FEATURE_NOT_AVAILABLE` em **todos** os endpoints de opções
      (`expirations`, `chain`, `strikes`, `analytics`), **inclusive para
      `PETR4`**. Reconfirmado em 2026-08-15 via REST (token na query e
      header Bearer) e via MCP. **Não existe mais sandbox de opções** — a
      anotação anterior de que `PETR4` era sandbox público está errada e
      foi corrigida; o único dado aberto é um teaser de 1 série dentro do
      corpo do próprio 403 (sem delta, sem `iv_rank`), inútil para montar
      cadeia. Precisa de upgrade para o plano Pro (R$139,99/mês). Achado
      adicional: o endpoint de analytics da Brapi não retorna `iv_rank`
      pronto (só gregas + IV), precisaria ser calculado a partir do
      histórico — ver tarefa 2.5 da change `build-portfolio-mvp-flow`
- [ ] `fetch_news.py` ainda não exercido contra um provedor real —
      `NEWS_API_KEY` não configurada
- [x] **Earnings Event Service (Fase 1) implementado** em `src/earnings/`:
      modelo (`models.py`), score de confiança (`confidence.py`), resolução
      de conflitos (`resolution.py`), repositório, serviço e
      `EarningsRiskService` (`risk.py`). Migração `001_earnings_events.sql`
      aplicada e idempotente; `schema.sql` acompanha. 99 testes só desta
      camada, incluindo integração contra o Postgres real (pulada
      automaticamente sem banco). **Ainda não integrado ao
      `strategy/covered.py`** — Fase 1 não toca na análise de opções por
      decisão do escopo
- [ ] Providers de earnings (Fase 2) ainda não implementados — só a
      interface `EarningsProvider` existe. Ordem decidida após prova real
      em 2026-08-15: `manual` → `cvm` → `yfinance`
- [ ] Fonte de calendário de resultados trimestrais ainda não integrada ao
      fluxo de estratégia — o critério da skill continua resultando em
      "dado insuficiente" até a Fase 2 + integração
- [ ] Não há, ainda, forma de registrar caixa/garantia disponível — covered
      put não é avaliado automaticamente contra a carteira real por isso
- [ ] **`report/daily.py` nunca lê preço de mercado.** `cotacoes` só é
      consultada em `_ultima_coleta` (frescor); `_resumo_carteira` valoriza
      tudo por `preco_medio` (custo de entrada). No teste de fluxo de
      2026-08-15 o relatório mostrou R$ 14.250 contra R$ 18.469 a mercado
      (~30% abaixo). Consequência: hoje o `fetch_quotes` é o único passo
      com dado real e não influencia nenhuma saída além de suprimir um
      alerta. Mesmo problema em `_exposicao_pct_apos_operacao`
      (`strategy/covered.py`), que roda o critério de risco
      `exposicao_maxima_pct_ativo` sobre custo, não sobre mercado
- [ ] **`executar_avaliacao_carteira()` não consegue emitir sugestão nem
      com dados de opções perfeitos**: `_opcoes_call_candidatas` fixa
      `dias_para_resultado = None` (gap do calendário de resultados), e
      `avaliar()` trata qualquer campo obrigatório nulo como "dado
      insuficiente" — todo par posição×opção é reprovado antes de olhar
      IV rank ou delta. O gap do calendário curto-circuita a avaliação
      inteira, não é só um critério a menos
- [ ] `python-dotenv` está em `requirements.txt` mas nenhum módulo chama
      `load_dotenv()` — hoje é preciso exportar as variáveis de `.env` no
      shell manualmente antes de rodar qualquer comando (`python -m
      src.etl.fetch_quotes` etc. falham com "Variáveis de ambiente
      ausentes" caso contrário); considerar corrigir antes do próximo
      onboarding
- [ ] Agente `strategy-covered` validado contra o fluxo real de ponta a
      ponta (posições, cotações Brapi, relatório); ainda falta validar com
      dados reais de opções (depende de `fetch_options.py`/Brapi Pro acima)
