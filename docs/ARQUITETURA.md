# Arquitetura

## Princípios

1. **LLM decide contexto, regra decide número.** Agentes de IA interpretam
   notícias e sintetizam cenário; a decisão de "isso atende os critérios de
   venda coberta?" é sempre calculada por código determinístico
   (`skills/covered-options-strategy`), nunca por julgamento livre do modelo.
2. **Nunca executa ordem real.** Toda saída dos agentes é gravada em
   `sugestoes` para revisão humana.
3. **Fonte única de verdade para dados de mercado é o banco.** Nenhum agente
   deve "lembrar" um preço — sempre consulta `cotacoes`/`opcoes` atualizados
   pelo ETL.

## Fontes de dados avaliadas

| Fonte | Uso no projeto | Observações |
|---|---|---|
| OpLab | Opções: preço, gregas, IV, IV rank; possibilidade de sincronizar custódia real via Área do Investidor B3 | Melhor cobertura específica para opções no mercado BR |
| brapi.dev | Cotações de ações/FIIs/BDRs | Plano gratuito bom para prototipar; já pensado para uso por agentes (MCP) |
| Partnr (futuro) | Notícias com score de relevância, dados fundamentalistas via CVM | Avaliar quando o volume de notícias justificar o custo |

## ETL

- `src/etl/fetch_quotes.py` — cotações via brapi, só dos tickers em carteira.
- `src/etl/fetch_options.py` — opções via OpLab, gregas + IV rank. Valida o
  formato da resposta antes de gravar (`FormatoRespostaInvalido` se as
  chaves esperadas não baterem) e isola falha por ticker. **A validação
  contra a API real com token pessoal ainda está pendente** (ver
  `openspec/changes/build-portfolio-mvp-flow/tasks.md`, tarefa 2.2) — o
  formato assumido em `CHAVES_ESPERADAS` pode precisar de ajuste.
- `src/etl/fetch_news.py` — News API genérica via `NEWS_API_KEY`; grava só
  metadados (nunca o texto do artigo). Se a chave não estiver configurada,
  a etapa é pulada de forma explícita, sem bloquear o resto do fluxo.
- `src/portfolio/manage.py` — entrada/encerramento/consulta manual de
  posições (`posicoes`), o "estoque de patrimônio".
- `src/strategy/covered.py` — avaliação determinística de venda coberta
  contra dados reais, persistindo sugestões em `sugestoes`.
- `src/report/daily.py` — geração do relatório diário (`reports/<data>.md`).
- Execução: manual (`python -m src.etl...`, `python -m src.portfolio.manage`,
  `python -m src.strategy.covered`, `python -m src.report.daily`) ou
  automática via `.github/workflows/daily-etl.yml` (os passos de estratégia
  e relatório ainda precisam ser adicionados ao workflow — ver Migration
  Plan da change `build-portfolio-mvp-flow`).

## Banco de dados

Ver `src/db/schema.sql`. Resumo das tabelas:

- `ativos` — cadastro de ações/FIIs acompanhados.
- `cotacoes` — série histórica de preços.
- `opcoes` — série histórica de opções (preço, gregas, IV).
- `posicoes` — o "estoque de patrimônio": o que você realmente tem alocado.
- `noticias` — notícias resumidas (nunca texto copiado da fonte original).
- `sugestoes` — log de tudo que os agentes sugeriram, com os critérios usados.

## Agentes (Claude Code, `.claude/agents/`)

```
orchestrator
  ├── data-collector    (garante dados atualizados)
  ├── market-analyst    (contextualiza: IV rank, notícias, eventos)
  └── strategy-covered  (aplica a skill covered-options-strategy)
```

Cada agente tem escopo de ferramentas restrito ao que precisa — evita que um
agente de análise, por exemplo, tenha acesso a `Bash` irrestrito sem motivo.

## Decisões em aberto (revisitar conforme o projeto evolui)

- ~~**Banco gerenciado para o Actions**...~~ **Resolvido**: Postgres no Neon
  (`sa-east-1`, free tier), fonte da verdade da carteira. O `docker-compose`
  passou a ser banco descartável de teste. Schema aplicado por
  `python -m src.db.bootstrap`; ver `docs/RUNBOOK-POSTGRES.md`.
- **Desfecho da avaliação é persistido** (`desfecho_avaliacao`): o motivo de
  cada não-sugestão sobrevive ao processo, agregado por (execução, ativo,
  motivo). É a fonte da seção "Avaliações sem sugestão" do relatório e será
  a da interface — sem isso, "nenhuma sugestão hoje" fica indistinguível de
  "nada valia a pena".
- ~~**Dashboard**: não há UI ainda...~~ **Resolvido em duas etapas**: o
  relatório Markdown estático continua existindo, e a Fase 4 virou uma
  interface web de verdade — API de leitura em `src/api/` (FastAPI, só
  `127.0.0.1`, sem lógica de decisão) consumida pelo repositório separado
  `opcoes-ia-web` (React+TS). Separado porque a camada web tem dependências
  e cadência próprias; o domínio fica aqui e a interface o consome por API
  com tipos gerados do OpenAPI. Relatório e API leem as mesmas funções de
  domínio (`visao_carteira`, `ultima_execucao_do_dia`) — divergência entre
  os dois é impossível por construção, não por disciplina.
- **Sincronização de custódia real**: a OpLab permite sincronizar com a Área
  do Investidor B3. Avaliar se vale integrar isso diretamente ou manter
  input manual no MVP. Nesta fase, o input é manual via
  `src/portfolio/manage.py`.
- **Provedor de notícias definitivo**: `fetch_news.py` usa uma News API
  genérica (estilo NewsAPI.org) via `NEWS_API_KEY` como opção provisória.
  Partnr (ou outro provedor pago com dados fundamentalistas) segue como
  opção a avaliar quando o volume de notícias justificar o custo — a
  interface do ETL é agnóstica de provedor, então trocar não deve exigir
  mudança de comportamento observável.
- **Calendário de resultados trimestrais**: o critério "sem evento de
  resultado próximo" da skill `covered-options-strategy` não tem, ainda,
  nenhuma fonte de dados real — `src/strategy/covered.py` marca esse
  critério como "dado insuficiente" honestamente em vez de assumir "sem
  evento". Até uma fonte ser integrada, nenhuma sugestão de covered call
  será gerada automaticamente (ver gap documentado no docstring do
  módulo). Precisa de uma fonte (ex.: API de calendário de resultados B3/CVM)
  e, possivelmente, uma nova tabela via migração.
- **Caixa/garantia para covered put**: não existe, ainda, nenhuma forma de
  registrar caixa disponível na carteira (`posicoes` só modela ações e
  opções). `avaliar()` já suporta covered put via um campo
  `caixa_disponivel` opcional, mas `executar_avaliacao_carteira()` não gera
  candidatas de covered put nesta fase por falta dessa fonte de dado.
