## 1. Portfolio tracking (`posicoes`)

- [x] 1.1 Criar `src/portfolio/__init__.py` e `src/portfolio/manage.py` com
      funções `add_posicao`, `close_posicao`, `list_posicoes_abertas`,
      seguindo o padrão de conexão de `src/db/connection.py`.
- [x] 1.2 Implementar validação de entrada (`quantidade != 0`,
      `preco_medio > 0`) em `add_posicao`, recusando e explicando o motivo
      quando inválida.
- [x] 1.3 Implementar interface de linha de comando (`python -m
      src.portfolio.manage add|close|list ...`) com `argparse`.
- [x] 1.4 Testes: cobrir registro de posição em ação, registro de posição
      vendida em opção, rejeição de quantidade zero, encerramento de
      posição e listagem de posições abertas.

## 2. ETL de mercado

- [x] 2.1 Ajustar `src/etl/fetch_quotes.py` (se necessário) para confirmar
      que já usa `_tickers_da_carteira()` como única fonte de tickers —
      manter comportamento de "nada a coletar" quando a carteira estiver
      vazia. (Confirmado: já era o comportamento existente, nenhuma mudança
      de código necessária.)
- [x] 2.2 Validar `fetch_quotes.py` contra a API real da Brapi
      (`GET /api/v2/stocks/quote`) usando o `BRAPI_TOKEN` do usuário;
      corrigir o mapeamento de campos conforme o formato real encontrado.
      **Concluído em 2026-08-14: a resposta real aninha os campos de
      mercado em `results[].data.*` (não no nível raiz do item, como o
      código assumia antes) — corrigido com validação defensiva explícita
      (`FormatoRespostaInvalido`) + 5 testes novos
      (`tests/test_fetch_quotes.py`).**
- [x] 2.3 Redesenhar `fetch_quotes.py` para respeitar o limite de 1 ativo
      por requisição do plano Free da Brapi (**confirmado em 2026-08-14**:
      erro `QUOTES_PER_REQUEST_EXCEEDED` ao mandar mais de 1 símbolo) — uma
      requisição por ticker, isolando falha por ticker (mesmo padrão já
      usado em `fetch_options.py`) em vez de abortar a coleta inteira
      quando um ticker falhar. **Concluído em 2026-08-15:** `fetch_um`
      (1 ticker por request) + loop com try/except isolado em `main()`;
      validado contra a API real com carteira de 2 tickers (PETR4 + VALE3)
      — 2/2 coletados com sucesso, cada um em sua própria requisição.
- [x] 2.4 Implementar orçamento de requests configurável para os ETLs de
      mercado (plano Free: 15.000/mês, meta operacional de até ~600/dia,
      compartilhado com qualquer uso do MCP pelos agentes — ver 2.11):
      contar requests já gastos no dia (derivado de `coletado_em` em
      `cotacoes`/`opcoes`) antes de rodar, coletar só o que couber no
      orçamento configurado, e logar explicitamente quais tickers ficaram
      de fora por orçamento insuficiente em vez de estourar a cota
      silenciosamente. **Concluído em 2026-08-15:** `src/etl/budget.py`
      (`requests_gastos_hoje`, `orcamento_restante_hoje`) + `Settings.
      brapi_requests_dia_maximo` (env `BRAPI_REQUESTS_DIA_MAXIMO`, default
      600) + wiring em `fetch_quotes.main()`; validado contra o banco real
      (3 requests contabilizados no dia, 597 restantes do limite de 600).
- [ ] 2.5 Trocar `fetch_options.py` de OpLab para os endpoints reais de
      opções da Brapi (`/api/v2/options/expirations|strikes|chain|
      historical|analytics|analytics/history`, ver
      https://brapi.dev/docs/opcoes), com validação defensiva das chaves
      esperadas antes do insert (erro explícito em vez de gravar `NULL`s) e
      isolamento de falha por ticker no resumo final — mesmos princípios já
      usados na implementação original contra OpLab, reaplicados ao novo
      formato de resposta. **BLOQUEADO: confirmado em 2026-08-14 que o
      plano Free do usuário recebe `403 FEATURE_NOT_AVAILABLE`
      (`canAccessOptionsData`) — só destrava com upgrade para o plano Pro
      (R$139,99/mês). Endpoint e formato de bloqueio já confirmados;
      integração com OpLab fica adiada para uma change futura.
      **CORREÇÃO (2026-08-15, reteste ao vivo):** a afirmação anterior de
      que `PETR4` era um sandbox público liberado NÃO se sustenta. Os
      quatro endpoints (`expirations`, `chain`, `strikes`, `analytics`)
      retornam 403 para `PETR4` também, tanto via REST (token na query e
      via header `Authorization: Bearer`) quanto via MCP. O controle
      `/api/quote/PETR4` retorna 200, confirmando que o token é válido e
      que o bloqueio é de entitlement, não de credencial. O único dado
      aberto é um `preview` de 1 série embutido no corpo do 403
      (`PETRH412`, strike 41, venc. 2026-08-21, IV 0.3184) — sem delta e
      sem `iv_rank`, insuficiente para montar cadeia ou alimentar a skill.
      **Achado adicional (registrado antes via PETR4, segue válido):** o
      endpoint `/api/v2/options/analytics` da
      Brapi retorna `delta/gamma/theta/vega/rho/impliedVolatility`, mas
      NÃO retorna `iv_rank` (percentil da IV atual vs. histórico) — a
      skill `covered-options-strategy` exige `iv_rank` como critério.
      `iv_rank` precisaria ser calculado a partir de
      `/api/v2/options/analytics/history` (série histórica de IV), o que é
      trabalho adicional não coberto por esta tarefa. Decisão de como
      calcular fica para quando este item for destravado.**
- [ ] 2.6 Testes: mock de resposta válida/inválida da Brapi para opções,
      isolamento de falha por ticker (substituindo os testes que hoje
      cobrem o formato antigo da OpLab).
- [x] 2.7 Implementar `fetch_news.py` contra um provedor de News API
      genérico usando `NEWS_API_KEY`, com resumo em texto próprio (nunca
      copiar o texto da fonte), restrito aos tickers em carteira. (O ETL
      grava só metadados — título/url/data/fonte; o resumo em texto
      próprio é responsabilidade do `market-analyst` ao consumir a
      notícia, nunca do ETL — ver docstring do módulo.)
- [x] 2.8 Em `fetch_news.py`, quando `NEWS_API_KEY` não estiver definida,
      reportar explicitamente "não configurado" (log + retorno) sem lançar
      erro e sem seguir em frente como se tivesse coletado.
- [x] 2.9 Implementar deduplicação de notícia por `url` já existente para o
      mesmo ticker antes de inserir.
- [x] 2.10 Testes: comportamento de `fetch_news` configurado e não
      configurado, deduplicação por `url`.
- [x] 2.11 Disponibilizar o MCP da Brapi (`https://brapi.dev/api/mcp/mcp`)
      como ferramenta ad-hoc para o agente `market-analyst`
      (`Authorization: Bearer <BRAPI_TOKEN>`, protocolo MCP/JSON-RPC;
      **confirmado funcionando no plano Free em 2026-08-14**, 69 tools
      catalogadas, cada uma respeitando a mesma restrição de plano da REST)
      — atualizar `.claude/agents/market-analyst.md` para referenciar o MCP
      como fonte de contexto exploratório, deixando explícito que nunca
      substitui o dado persistido em `src/db` usado pela avaliação de
      estratégia. **Concluído em 2026-08-15:** `.mcp.json` criado na raiz
      do projeto (servidor `brapi`, token via `${BRAPI_TOKEN}` do
      ambiente, nunca hardcoded); `market-analyst.md` ganhou uma lista
      restrita de tools (`mcp__brapi__get_stock_profile`,
      `get_stock_dividends`, `get_tickers`, `resolve_tickers`,
      `get_ticker_coverage`, `get_macro_series*`, `get_inflation_data`,
      `get_prime_rate_data`) — deliberadamente SEM `get_stock_quote` nem
      `get_option_*`, para que preço/grega/IV usados numa decisão só
      possam vir do banco, por permissão, não só por instrução em prosa.
      **Ressalva:** a conexão MCP em si (HTTP + JSON-RPC, autenticação,
      catálogo de 69 tools, bloqueio de opções por plano) foi validada
      diretamente contra a API nesta sessão; o carregamento do
      `.mcp.json` pelo agente dentro do Claude Code ainda não foi
      exercido de ponta a ponta (normalmente exige nova sessão) — validar
      na próxima vez que o `market-analyst` for invocado.

## 3. Avaliação da estratégia de venda coberta

- [x] 3.1 Criar `src/strategy/__init__.py` e `src/strategy/covered.py` com
      a função pura `avaliar(posicao, dados_mercado, params) ->
      ResultadoAvaliacao`, carregando os limiares de
      `skills/covered-options-strategy/params.yaml` (nunca hardcoded).
- [x] 3.2 Implementar o pré-requisito de elegibilidade (lote completo para
      covered call; caixa/garantia suficiente para covered put) como
      primeira checagem, antes dos critérios de mercado.
- [x] 3.3 Implementar os seis critérios de mercado da skill (IV rank,
      delta, dias até vencimento, prêmio mínimo, exposição máxima por
      ativo, ausência de evento de resultado em N dias) — todos precisam
      passar para gerar sugestão. **Nota:** não existe ainda fonte de dados
      de calendário de resultados nem de caixa/garantia disponível — ver
      gap documentado no docstring de `covered.py` e no resumo final desta
      sessão.
- [x] 3.4 Implementar `executar_avaliacao_carteira()`: busca posições
      abertas elegíveis e dados de mercado reais do banco, chama `avaliar`
      para cada uma, e marca como "dado insuficiente" quando faltar IV
      rank/gregas necessárias em vez de assumir um valor.
- [x] 3.5 Persistir em `sugestoes` apenas as avaliações que passaram em
      todos os critérios, com `criterios_json` contendo o snapshot completo
      dos valores avaliados e `status = 'pendente'`.
- [x] 3.6 Evitar sugestão duplicada: checar se já existe uma sugestão
      `pendente` para o mesmo `codigo_opcao` gerada no mesmo dia antes de
      inserir novamente.
- [x] 3.7 Testes: função `avaliar` cobrindo caso "todos os critérios
      passam", "um critério falha" (não gera sugestão), pré-requisito de
      lote não atendido, e dado de mercado insuficiente.

## 4. Relatório diário

- [x] 4.1 Criar `src/report/__init__.py` e `src/report/daily.py` com
      `gerar_relatorio(data) -> caminho_do_arquivo`, escrevendo em
      `reports/<AAAA-MM-DD>.md`.
- [x] 4.2 Consolidar no relatório: resumo da carteira atual (posições e
      exposição por ativo), alertas coletados na execução do dia (dado
      desatualizado/ausente, notícias não configuradas) e as sugestões
      geradas por `executar_avaliacao_carteira()` no mesmo dia.
- [x] 4.3 Garantir que o relatório nunca sobrescreve o de um dia anterior
      (um arquivo por data) e que cada sugestão listada traz o texto de
      "pendente de revisão humana".
- [x] 4.4 Adicionar `reports/` ao `.gitignore`.
- [x] 4.5 Testes: geração de relatório com e sem sugestões, inclusão de
      alerta quando há dado desatualizado, não sobrescrita ao gerar em dois
      dias diferentes (usar datas mockadas).

## 5. Wiring dos agentes e documentação

- [x] 5.1 Atualizar `.claude/agents/data-collector.md` para referenciar
      `python -m src.portfolio.manage`, o `fetch_options.py` validado e o
      novo comportamento explícito de `fetch_news.py`.
- [x] 5.2 Atualizar `.claude/agents/strategy-covered.md` para invocar
      `python -m src.strategy.covered` (ou a função equivalente) em vez de
      descrever a avaliação apenas em prosa.
- [x] 5.3 Atualizar `.claude/agents/orchestrator.md` para invocar `python -m
      src.report.daily` ao final do fluxo e referenciar o arquivo gerado em
      vez de produzir só texto de chat.
- [x] 5.4 Atualizar `docs/ARQUITETURA.md`: marcar a decisão de "relatório
      Markdown estático" como resolvida e documentar o provedor de
      notícias escolhido (ou seu estado "a definir" de forma explícita).
- [x] 5.5 Atualizar o checklist "Estado atual" do `CLAUDE.md` conforme cada
      item desta change for concluído.

## 6. Validação de ponta a ponta

- [ ] 6.1 Rodar `docker compose up -d db` local, aplicar `schema.sql`,
      cadastrar uma posição de teste via `src.portfolio.manage`, e rodar o
      fluxo completo (`fetch_quotes` → `fetch_options` → `fetch_news` →
      avaliação de estratégia → relatório) manualmente, confirmando que o
      relatório gerado reflete a posição de teste. **PARCIALMENTE VALIDADO
      em 2026-08-14: `docker compose up -d db` + `schema.sql` +
      `src.portfolio.manage add/close` + `fetch_quotes` (Brapi, com
      `BRAPI_TOKEN` real) + avaliação de estratégia + relatório rodaram de
      ponta a ponta com sucesso (posição de teste registrada e encerrada
      após validar; ver commits desta sessão para os dois bugs reais
      encontrados e corrigidos: mapeamento de campos da Brapi em
      `fetch_quotes.py` e comparação de data em UTC vs. local em
      `report/daily.py`). `fetch_options` (OpLab) e `fetch_news`
      (News API) continuam pulados/não exercidos — segue BLOQUEADO por
      falta de `OPLAB_TOKEN`/`NEWS_API_KEY` reais. Tarefa permanece aberta
      até essa parte também ser validada.**
- [x] 6.2 Rodar `pytest` e confirmar que toda a suíte passa, incluindo os
      testes novos desta change. (34/34 testes passando, incluindo os 26
      novos desta change.)
