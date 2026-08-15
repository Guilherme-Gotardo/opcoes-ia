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
- [x] Banco local (`docker compose up -d db` + `schema.sql`) validado de
      ponta a ponta em 2026-08-14 com posição de teste, cotação real,
      avaliação de estratégia e relatório diário — ver tarefa 6.1 da change
      `build-portfolio-mvp-flow` para detalhes e o bug de fuso horário
      (UTC vs. local) corrigido em `report/daily.py`
- [ ] `fetch_options.py` ainda não trocado de OpLab para os endpoints reais
      de opções da Brapi — bloqueado no plano Free do usuário (confirmado:
      `403 FEATURE_NOT_AVAILABLE` para qualquer ticker além do sandbox
      `PETR4`); precisa de upgrade para o plano Pro (R$139,99/mês). Achado
      adicional: o endpoint de analytics da Brapi não retorna `iv_rank`
      pronto (só gregas + IV), precisaria ser calculado a partir do
      histórico — ver tarefa 2.5 da change `build-portfolio-mvp-flow`
- [ ] `fetch_news.py` ainda não exercido contra um provedor real —
      `NEWS_API_KEY` não configurada
- [ ] Fonte de calendário de resultados trimestrais ainda não integrada —
      critério correspondente da skill sempre resulta em "dado insuficiente"
- [ ] Não há, ainda, forma de registrar caixa/garantia disponível — covered
      put não é avaliado automaticamente contra a carteira real por isso
- [ ] `python-dotenv` está em `requirements.txt` mas nenhum módulo chama
      `load_dotenv()` — hoje é preciso exportar as variáveis de `.env` no
      shell manualmente antes de rodar qualquer comando (`python -m
      src.etl.fetch_quotes` etc. falham com "Variáveis de ambiente
      ausentes" caso contrário); considerar corrigir antes do próximo
      onboarding
- [ ] Agente `strategy-covered` validado contra o fluxo real de ponta a
      ponta (posições, cotações Brapi, relatório); ainda falta validar com
      dados reais de opções (depende de `fetch_options.py`/Brapi Pro acima)
