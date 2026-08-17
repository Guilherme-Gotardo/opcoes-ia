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

# velas OHLC para o gráfico (tabela `candles`, separada de `cotacoes`).
# O intervalo é coluna: 1h e 1d convivem, e a interface desenha o que houver.
python -m src.etl.fetch_candles --intervalo 1h    # janela padrão: 5d
python -m src.etl.fetch_candles --intervalo 1d    # janela padrão: 3mo

# cadastro de ativos — PRÉ-REQUISITO de tudo: `cotacoes`, `opcoes` e
# `noticias` têm FK para `ativos`. Sem cadastrar, o ETL recusa o ticker e
# registrar posição falha. O nome nunca é derivado do ticker.
python -m src.assets.manage add PETR4 "Petrobras PN" acao --cnpj-raiz 33000167
python -m src.assets.manage list

# posições (só depois do ativo cadastrado)
python -m src.portfolio.manage add PETR4 ACAO 100 32.50

# watchlist — vigiar ativo SEM ter posição, para procurar oportunidade nele.
# O universo de coleta e de varredura é CARTEIRA ∪ VIGIADOS. Não é de graça:
# cada vigiado consome ~4 requests/dia do orçamento (cotação + 2 janelas de
# vela + opções), então 600/dia comportam ~150 tickers no total.
python -m src.assets.manage vigiar ITUB4 --motivo "liquidez alta em opções"
python -m src.assets.manage parar-de-vigiar ITUB4

# caixa/garantia — o que torna uma PUT coberta, coberta. `avaliar()` exige
# `caixa_disponivel`; sem lançamento, o saldo é zero e a put é recusada.
# São LANÇAMENTOS, não saldo: o saldo é a soma, e o sinal preserva o que
# aconteceu (positivo aporta, negativo retira).
python -m src.caixa.manage add 20000 --descricao "aporte para garantia"
python -m src.caixa.manage saldo
python -m src.caixa.manage extrato

# datas de divulgação de resultado (espelho manual — leia no site de RI)
# REGISTRAR NÃO É CONSOLIDAR: `manage add` grava o que você leu; só o
# `ingest` promove aquilo para a tabela que o motor de opções consulta.
# Sem o passo 2 a data existe no banco e a avaliação segue bloqueada.
python -m src.earnings.manage add PETR4 2026-11-06 --sessao AFTER_CLOSE \
    --origem https://petrobras.com.br/ri/calendario   # 1. registrar
python -m src.earnings.ingest --tickers PETR4                # 2. consolidar
python -m src.earnings.manage list
python -m src.earnings.manage remove PETR4 2026Q3

# consolidação completa (padrão: fonte `manual`, tickers da carteira aberta)
python -m src.earnings.ingest
python -m src.earnings.ingest --fontes manual,cvm

# API de leitura para a interface web (repositório opcoes-ia-web).
# Três limites, por construção: NÃO decide (critério é determinístico em
# src/strategy/), NÃO dispara (nenhum endpoint roda ETL/avaliação), NÃO
# escreve. Sobe só em 127.0.0.1; sem autenticação por decisão registrada
# (uso local de um usuário) — publicar exige rever isso em change própria.
python -m src.api
python -m src.api --schema openapi.json   # exporta o contrato p/ gerar os
                                          # tipos TS (npm run gerar-tipos
                                          # no opcoes-ia-web)

# execução automática em pregão — um disparo do pipeline (cotação +
# avaliação, nesta ordem). A cotação vai junto de propósito: sem ela, uma
# avaliação intradiária leria o fechamento anterior, que tem menos de 72h e
# PASSA na janela de frescor — sugestão sobre o preço de ontem, em silêncio.
# Fora da janela de pregão, registra o motivo e sai. Ver docs/PREGAO.md.
python -m scripts.rodar_pregao              # respeita a janela
python -m scripts.rodar_pregao --forcar     # ignora (fica marcado no detalhe)

# calendário de pregão. Data FORA da vigência levanta CalendarioVencido —
# nunca "não é feriado": responder False emudeceria o pipeline em dia útil,
# e responder True o faria avaliar num feriado sobre cotação de outro dia.
python -m src.pregao.derivar 2026 2029 > src/pregao/feriados_b3.yaml

# ferramentas do agente de relatório (Fase 3). O primeiro só MOSTRA o que
# seria enviado, com o token mascarado; o segundo faz uma chamada real e
# cobra o critério da fase (buscou e citou a fonte?).
python -m src.agente.ferramentas
ANTHROPIC_API_KEY=sk-ant-... python -m src.agente.verificar

# relatório do dia composto pelo agente (Fase 4). O `--seco` mostra o prompt
# e para, sem chamar a API — é como se confere um guarda-corpo sem gastar.
# Insumo vazio (nada avaliado) sai sem gastar chamada.
python -m src.agente.relatorio --seco
python -m src.agente.relatorio

# taxa livre de risco (BCB/SGS 1178, Selic anualizada). Insumo do modelo de
# precificação — vem de FONTE, não de parâmetro chumbado.
python -m src.quant.taxa

# preparar um banco (schema + migrações, idempotente)
python -m src.db.bootstrap --dry-run   # mostra o alvo, sem escrever
python -m src.db.bootstrap

# rodar testes — APONTE PARA O BANCO DESCARTÁVEL, não para o Neon.
# Os testes de integração escrevem e apagam linhas no banco de DATABASE_URL;
# eles se protegem (tickers com prefixo ZZ, limpeza no fixture), mas não há
# razão para fazer isso na base que guarda a carteira real.
DATABASE_URL=postgresql://opcoes_ia:opcoes_ia@localhost:5433/opcoes_ia pytest

# subir banco local descartável
docker compose up -d db
```

## Onde olhar primeiro em cada tipo de tarefa

- Pedido sobre **fonte de dados / ETL** → `src/etl/`, `docs/ARQUITETURA.md#etl`
- Pedido sobre **schema / carteira** → `src/db/schema.sql`
- Pedido sobre **regra de estratégia** → `skills/covered-options-strategy/SKILL.md`
- Pedido sobre **data de resultado / risco de earnings** → `src/earnings/`.
  A ordem de leitura é `models.py` (invariantes) → `confidence.py` (tiers de
  provedor) → `resolution.py` (conflitos) → `risk.py` (o que o motor de
  opções consome). Para o caminho do dado até a decisão, `manage.py` (o que
  o usuário afirma) → `ingest.py` (o que promove aquilo para
  `earnings_events`). Duas regras que atravessam tudo: estimativa nunca
  sobrescreve confirmação, e registrar não é consolidar
- Pedido sobre **por que não saiu sugestão** → `src/strategy/outcome.py`
  (classificação e agregação) e `outcome_repository.py` (tabela
  `desfecho_avaliacao`). Registro agregado por (execução, ativo, motivo) —
  não uma linha por opção, porque o bloqueio por data de resultado é por
  ativo. Atenção: a contagem por critério **pode somar mais que o total**,
  já que uma opção reprovada em dois critérios conta nos dois
- Pedido sobre **valor de posição / patrimônio / exposição** →
  `src/market/valuation.py`. É o único lugar que traduz `cotacoes` em valor;
  `report/daily.py` e `strategy/covered.py` consomem de lá. Regra que
  atravessa tudo: `preco_medio` é custo e nunca vira valor de mercado
- Pedido sobre **novo agente** → `.claude/agents/`, use `orchestrator.md` como
  referência de como os agentes se conectam
- Pedido sobre **automação diária** → `.github/workflows/daily-etl.yml`
- Pedido sobre **agente de IA, MCP, busca web, relatório** →
  `docs/AGENTE.md`. A ordem de leitura é `dados.py` (o insumo) → `prompt.py`
  (os guarda-corpos) → `relatorio.py` (a única peça com LLM) → `entrega.py`.
  Quatro regras: `mcp_servers` sozinho é 400 (a API exige também
  `tools[{type: mcp_toolset}]` e o beta); busca web é ferramenta NATIVA e não
  precisa de MCP; envio de notificação NÃO é ferramenta do agente; e o agente
  recebe o VEREDITO de cada critério, nunca o dado cru que permitiria
  reavaliar
- Pedido sobre **grega, preço teórico, probabilidade de exercício** →
  `docs/QUANT.md`, depois `src/quant/enrichment.py` (puro) e
  `src/quant/pipeline.py` (o que tem I/O). Regra que atravessa tudo: isto é
  CONTEXTO, não gate — `strategy/covered.py` não importa `src.quant` no topo
  e há teste que falha se alguém subir esse import
- Pedido sobre **execução em pregão / agendamento** → `docs/PREGAO.md` é o
  ponto de entrada; depois `src/pregao/calendario.py` (há pregão agora?),
  `src/pregao/execucao.py` (o log) e `scripts/rodar_pregao.py` (o disparo).
  Duas regras atravessam tudo: o calendário **falha alto** quando não sabe, e
  a linha de execução **abre antes** do trabalho para um crash deixar rastro

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
- [x] **Postgres gerenciado no Neon é a FONTE DA VERDADE** da carteira
      (região `sa-east-1`, free tier, `sslmode=require` na URL). É o que o
      GitHub Actions escreve e o que você opera. O Postgres do
      `docker-compose` virou **banco descartável** de teste e
      experimentação — pode ser derrubado e recriado sem perda, e não
      guarda carteira real. A instância subiu vazia por decisão ("começar
      do zero"): as posições precisam ser cadastradas por
      `python -m src.portfolio.manage`. Schema aplicado por
      `python -m src.db.bootstrap`, que é idempotente e imprime o alvo
      antes de escrever. Runbook em `docs/RUNBOOK-POSTGRES.md`
- [ ] **Os testes de integração escrevem no banco de `DATABASE_URL`.** Com
      o `.env` apontando para o Neon, rodar `pytest` grava e apaga linhas
      na base real a cada execução. Eles se protegem (tickers `ZZ`, limpeza
      no fixture), mas a convenção é rodar a suíte contra o banco
      descartável — ver "Comandos úteis". É convenção documentada, não
      trava no código
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
- [x] **Providers de earnings (Fase 2) implementados**: `manual` (única
      fonte com autoridade para `CONFIRMED`, alimentada por
      `python -m src.earnings.manage`), `cvm` (dump IPE, só `RELEASED`) e
      `yahoo` (secundária, `ESTIMATED`). Migração 002 criou
      `earnings_manual_entries` e `ativos.cnpj_raiz`. Validados contra as
      fontes reais em 2026-08-15: a CVM devolveu 4/5 divulgações do 2T26
      (BBAS3 fora por causa da latência do dump) e o Yahoo 3/5 datas
      futuras — exatamente o que a investigação previu
- [x] **API de leitura implementada** (`src/api/`, FastAPI) com a interface
      web em repositório próprio (`opcoes-ia-web`, React+TS). A visão de
      carteira saiu de `report/daily.py` para `visao_carteira()` em
      `src/market/valuation.py` — relatório e API leem a MESMA função, por
      construção. O contrato TS é gerado do OpenAPI
      (`python -m src.api --schema` → `npm run gerar-tipos`), nunca escrito
      à mão. A interface mostra o desfecho da ÚLTIMA execução, não do
      instante — a data da execução acompanha a resposta
- [x] **Superfície de leitura ampliada para 7 endpoints** (2026-08-16):
      `/resultados`, `/operacao` e `/parametros` somaram-se aos quatro
      originais, todos GET e sem escrita. `/resultados` expõe
      `earnings_events` com as fontes que sustentam cada data E, separado,
      o que está em `earnings_manual_entries` sem evento correspondente —
      "registrar não é consolidar" virou estado consultável em vez de
      armadilha silenciosa, com o comando do `ingest` junto. `/parametros`
      publica `cotacao_frescor_maximo_horas` e
      `politica_resultado_desconhecido` porque a interface estava
      DUPLICANDO os dois: mudá-los em `params.yaml` não mudava a tela, que
      passava a mentir sem avisar. `/operacao` deriva saúde de coleta dos
      carimbos que já existem (`coletado_em` por fonte, `retrieved_at` por
      provider de earnings, `MAX(executado_em)` do desfecho) e reusa
      `etl/budget.py` para o orçamento. **Não é log de execução**: nada no
      projeto grava tentativa, erro ou duração, e a resposta declara isso
      em `rastreia_falhas: false` para a interface não vender silêncio como
      saúde. Uma timeline por agente exige instrumentar os ETLs primeiro —
      é change própria, não endpoint. Achado do caminho: o guardrail
      `_sem_escrita` de `tests/test_api_read.py` casava substring e
      reprovava um SELECT legítimo por causa da coluna `updated_at`
      (contém "UPDATE"); passou a casar palavra inteira
- [x] **Revisão do `strategy/covered.py`** (2026-08-16, change
      `harden-covered-evaluation-inputs`): cinco achados, três deles bugs
      reais. `strike` não era campo obrigatório e era usado sem proteção —
      `opcao["strike"] * 100` no ramo covered put estourava `TypeError`
      com strike nulo (que o ETL grava quando o provedor não devolve), e no
      covered call o orquestrador fazia `strike or 0.0`, transformando dado
      ausente em exposição ZERO e **aprovando** o critério que deveria
      barrar. A janela de frescor valia só para a cotação da ação: delta e
      IV rank de dias atrás entravam como se fossem de agora (`DISTINCT ON`
      traz a linha mais recente, o que não é o mesmo que recente) — agora há
      `opcao_frescor_maximo_horas`, que herda a da cotação quando omitida.
      Os outros dois eram falta de VISIBILIDADE, corrigidos sem mexer na
      postura de risco: `premio_minimo_pct` não desconta prazo e favorece
      vencimentos longos (o equivalente mensal passou a aparecer no detalhe,
      e há um critério opcional `premio_minimo_pct_ao_mes` desligado por
      padrão); e patrimônio parcial subestima o denominador da exposição de
      TODAS as posições, não só a do ticker sem cotação — a ressalva agora
      viaja no detalhe do critério, não só num `log.warning` que ninguém que
      lê o desfecho encontraria
- [x] **A API ganhou escrita de carteira** (2026-08-16, `src/api/escrita.py`):
      `POST /ativos`, `POST /posicoes` e `POST /posicoes/{id}/encerrar`,
      reusando `add_ativo`/`add_posicao`/`close_posicao` — nenhuma validação
      foi reescrita, para não criar uma segunda verdade sobre o que é
      posição válida. O invariante "a API não escreve" foi **revisado**, não
      abandonado: registrar posição é escrituração do que já está na
      corretora, não ordem, e substituir as CLIs de entrada por telas é o
      propósito declarado do `opcoes-ia-web`. Fica em módulo separado para
      o guardrail `_sem_escrita` continuar provando que a LEITURA não
      escreve. CORS passou a liberar POST; segue sem DELETE, porque
      encerrar posição é UPDATE em `fechada_em`
- [x] **Candles OHLC** (migração 004, `src/etl/fetch_candles.py`,
      `GET /candles`): tabela nova em vez de colunas em `cotacoes`, porque
      são coisas diferentes — cotação é preço num instante (o que a
      valorização consome), vela é resumo de um período. `intervalo` é
      COLUNA, então 1d, 1h e um futuro 15m convivem sem migração nova, e a
      interface desenha o que houver. CHECK de coerência OHLC no banco
      (máxima é teto, mínima é piso): um mapeamento trocado no provedor —
      que já aconteceu aqui com `fetch_quotes` em 2026-08-14 — passaria
      despercebido e só apareceria como vela invertida meses depois.
      Confirmado contra a API real: `range=5d&interval=1h` devolve 28 velas,
      `range=1mo&interval=1d` devolve 21. Uma execução DIÁRIA basta para a
      série de 1h (a janela de 5d vem numa requisição só), e o workflow
      ganhou os dois passos
- [x] **Motivo de cada não-sugestão é persistido** (`desfecho_avaliacao`,
      migração 003). Antes, só as sugestões elegíveis iam para `sugestoes`;
      bloqueio por data de resultado, reprovação em critério, dado
      insuficiente e pré-requisito viviam em memória e morriam com o
      processo — o relatório só enxergava porque recebia por argumento, no
      mesmo processo. Agora o relatório lê do banco quando `avaliacoes` não
      é informado, e a seção cobre **todos** os motivos, não só earnings.
      Isso destrava a interface: "nenhuma sugestão hoje" deixa de ser
      silêncio. Dívida conhecida: `covered.py` importa `outcome.py` de forma
      adiada dentro da função para quebrar um ciclo de import — a correção
      é extrair `ResultadoAvaliacao`/`EstadoCriterio` para um módulo de
      modelos
- [x] **Cadastro de ativos implementado** (`src/assets/manage.py`).
      `ativos` é a entidade de referência — `cotacoes.ticker`,
      `opcoes.ticker_objeto` e `noticias.ticker` têm FK para ela — e até
      2026-08-16 **nada no projeto inseria nessa tabela**: numa base nova o
      `fetch_quotes` falhava em todo ticker com violação de chave
      estrangeira. Hoje o ETL e o registro de posição recusam ticker não
      cadastrado com mensagem que cita o comando, e `--cnpj-raiz` (que o
      `CvmProvider` usa para mapear o dump da CVM) deixou de exigir
      `UPDATE` na mão. Cadastrados: PETR4, VALE3, ITUB4, BBAS3, ABEV3.
      Limitação conhecida: a validação vale para `ACAO`; em `OPCAO`,
      `posicoes.ticker` guarda o código da opção, que não é linha em
      `ativos`
- [ ] Providers da Fase 3 (EODHD, Twelve Data) não implementados —
      dependem de prova de cobertura B3 com plano pago
- [x] **Critério de resultado integrado ao `strategy/covered.py`**: o
      critério tem três estados (`aprovado`/`reprovado`/`indisponivel`) e
      deixou de curto-circuitar a avaliação. Política configurável em
      `politica_resultado_desconhecido` (`bloquear` padrão | `sinalizar`).
      Reprovação no mérito sempre vence a política. O relatório ganhou a
      seção "Avaliações bloqueadas por data de resultado", com os critérios
      já verificados e os comandos que destravam. Validado com opção
      sintética (`fonte='sintetico'`): sem data registrada o relatório
      mostra o bloqueio. **Correção de 2026-08-16: a anotação anterior
      dizia que registrar a data bastava para emitir sugestão — não
      bastava.** `manage add` grava em `earnings_manual_entries` e, até a
      change `expose-earnings-ingest-entrypoint`, nada promovia aquilo para
      `earnings_events`; `proximo_evento()` devolvia `None`
- [x] **Carteira valorizada a preço de mercado e exposição só da parte
      descoberta** (`src/market/valuation.py`, o único lugar que traduz
      `cotacoes` em valor). `exposicao_maxima_pct_ativo` passou a medir
      opção **descoberta** por ativo: o notional da operação menos a
      cobertura já em carteira (ações para call, caixa para put), com piso
      em zero — covered call totalmente coberta adiciona zero. O denominador
      é o patrimônio a mercado, só de posições em ação. Sem cotação dentro
      de `cotacao_frescor_maximo_horas` (padrão 72h) a avaliação para como
      "dado insuficiente" nomeando ticker e idade; **não existe fallback
      para `preco_medio`**
- [x] **Caixa/garantia registrável** (`src/caixa/manage.py`, migração 006),
      o que destrava a avaliação de covered put contra a carteira real —
      `avaliar()` já exigia `caixa_disponivel` e não havia onde gravá-lo.
      São LANÇAMENTOS, não saldo único: um saldo sobrescrito perde como se
      chegou até ele, e é esse "como" que explica meses depois por que uma
      avaliação aceitou ou recusou a operação
- [x] **Watchlist** (migração 006): `ativos.vigiado` marca ativo a ser
      observado SEM ter posição, e o universo de coleta/varredura virou
      CARTEIRA ∪ VIGIADOS nos três ETLs. Até então tudo partia de `posicoes`
      abertas, o que estava certo para venda coberta ("coberta" = as ações
      já são suas) mas fechava a porta para procurar oportunidade em ativo
      que ainda não se tem. É coluna em `ativos` e não tabela nova porque
      vigiar é atributo do cadastro — só se vigia o que já é alvo das FKs.
      **O orçamento continua sendo o teto real**: ~4 requests/dia por
      ticker, 600/dia, ~150 tickers no total — varrer a bolsa inteira não
      cabe, e por isso a escolha é explícita
- [ ] **Concentração da carteira não é barrada por nenhum critério** — e
      isso é deliberado. `exposicao_maxima_pct_ativo` limita opção
      descoberta, não o quanto do patrimônio está num único ativo. Quem
      mostra concentração é a seção "Exposição por ativo-objeto" do
      relatório diário (agora a mercado), para decisão humana. Se um dia
      um teto de concentração for desejado, é critério novo, não
      reinterpretação deste
- [ ] **`executar_avaliacao_carteira()` não consegue emitir sugestão nem
      com dados de opções perfeitos**: `_opcoes_call_candidatas` fixa
      `dias_para_resultado = None` (gap do calendário de resultados), e
      `avaliar()` trata qualquer campo obrigatório nulo como "dado
      insuficiente" — todo par posição×opção é reprovado antes de olhar
      IV rank ou delta. O gap do calendário curto-circuita a avaliação
      inteira, não é só um critério a menos
- [x] **`.env` é carregado automaticamente** (`load_dotenv` em
      `src/config.py` e em `src/db/bootstrap.py`, que não importa config de
      propósito). A pendência mordeu de verdade em 2026-08-16: `python -m
      src.api` falhava com "Variáveis de ambiente ausentes" mesmo com o
      `.env` preenchido. Variável exportada no shell tem precedência sobre o
      arquivo. Efeito colateral documentado: um `pytest` sem `DATABASE_URL`
      explícito agora encontra o Neon pelo `.env` — a convenção de rodar a
      suíte contra o banco descartável (ver "Comandos úteis") ficou mais
      importante, não menos
- [ ] Agente `strategy-covered` validado contra o fluxo real de ponta a
      ponta (posições, cotações Brapi, relatório); ainda falta validar com
      dados reais de opções (depende de `fetch_options.py`/Brapi Pro acima)
- [x] **Execução automática em pregão** (Fase 1 do plano de automação,
      2026-08-16): `src/pregao/` + `scripts/rodar_pregao.py` + migração 007 +
      unidades systemd em `deploy/systemd/`. Ver `docs/PREGAO.md`.
      Três decisões que valem mais que o código: (a) o **ETL de cotação entra
      no disparo**, porque o plano previa chamar só a avaliação e isso leria
      o fechamento anterior — que tem menos de 72h e portanto PASSA na janela
      de frescor, virando sugestão sobre o preço de ontem sem nada na tela
      dizer isso; (b) o calendário **levanta `CalendarioVencido`** para data
      fora da vigência, nunca "não é feriado", porque as duas alternativas
      falham em silêncio nas duas direções; (c) a linha de `execucao_pipeline`
      **abre antes do trabalho e commita na hora**, então um processo morto no
      meio deixa `status='executando'` órfão — que é o rastro de "crashou", e
      um INSERT só no fim não registraria esse caso.
      Bug encontrado ao rodar: `status VARCHAR(20)` não comportava
      `'pulado_fora_de_pregao'` (21 caracteres) — o CHECK listava um valor que
      o tipo recusava, e o caminho MAIS percorrido (a maior parte das horas do
      ano não é pregão) estourava. Corrigido com `ALTER` na própria migração,
      que ainda não tinha ido a lugar nenhum
- [x] **`/saude-coleta` ganhou `automacao`** e a tela de Mercado ganhou o
      cartão "Execução automática". `rastreia_falhas` continua `false` e isso
      NÃO é esquecimento: ele fala das COLETAS, onde falha por fonte segue sem
      registro. A EXECUÇÃO, essa sim, passou a ser rastreada. Trocar os dois
      escopos faria a tela vender silêncio de coleta como saúde
- [ ] **A cadência de pregão encolhe o teto da watchlist**, e o número de
      ~150 tickers citado acima vale só para o regime de uma coleta diária.
      Com disparo de 30 em 30 minutos são ~18 requests/ticker/dia e o teto cai
      para **~33**. Cadência e tamanho da watchlist são o mesmo botão — tabela
      em `docs/PREGAO.md`. Nada no código impede estourar: o sintoma é o
      `fetch_quotes` cortando a lista pelo fim, e os últimos tickers em ordem
      alfabética param de ter preço
- [x] **Migrações 001 a 010 aplicadas no Neon** em 2026-08-17 durante o
      primeiro deploy serverless. Watchlist, caixa, execução por etapa,
      relatórios duráveis e idempotência estão no banco real
- [x] **Alerta independente de "não rodou hoje" implementado** em
      `scripts/alertar_pregao.py` + `opcoes-ia-alerta.timer`. Depois do
      fechamento, consulta o log de execução e envia por SMTP se não houve
      execução, houve falha/órfã ou o banco não respondeu. Não depende do
      agente de IA; sem SMTP configurado falha explicitamente no journal
- [x] **Enriquecimento quantitativo** (Fase 2 do plano, 2026-08-16):
      `src/quant/` + migração 008. Gregas, preço teórico, probabilidade de
      exercício, percentil de IV e skew, por árvore binomial CRR (QuantLib,
      dependência OPCIONAL). Ver `docs/QUANT.md`.
      É CONTEXTO, não gate, e isso é verificado: `strategy/covered.py` não
      importa `src.quant` no topo (o import é adiado, depois do commit da
      decisão) e a gravação vai em TRANSAÇÃO PRÓPRIA — se fosse junto, um
      erro de banco aqui abortaria a transação e levaria embora sugestões e
      desfecho já calculados. Há teste que falha se alguém subir o import.
      Achado do caminho: o plano assumia "opções B3 são americanas" para as
      duas pontas. A convenção da B3 é call americana e **put europeia**, e
      apreçar put europeia como americana superestima o prêmio em 2% a 9%
      conforme o moneyness — justamente na estratégia de put coberta. O
      estilo virou parâmetro POR CONTRATO em `src/quant/modelo.yaml`, e o
      estilo usado é gravado por linha
- [x] **Taxa livre de risco vem de fonte** (`src/quant/taxa.py`, BCB/SGS
      série 1178 — pública, sem chave). O plano previa parâmetro
      configurável; um número chumbado é exatamente o que a regra 1 proíbe, e
      a própria Fase 5 já listava "taxa desatualizada" como risco de deriva.
      BCB fora do ar reusa a última taxa gravada com a idade declarada em
      ressalva. Não usa a série 432 (Meta Selic): ela carrega data de
      VIGÊNCIA, que pode ser futura, e um `observada_em` no futuro tornaria a
      auditoria da idade sem sentido
- [ ] **O enriquecimento não aparece em tela nenhuma.** Está no banco e só é
      consultável direto. Enquanto `opcoes` estiver vazia não haveria o que
      mostrar, mas quando houver, isso é o que falta para o número servir a
      uma decisão humana
- [x] **Camada de ferramentas do agente** (Fase 3 do plano, 2026-08-16):
      `src/agente/ferramentas.py` + `ferramentas.yaml`. Ver `docs/AGENTE.md`.
      Três correções ao plano: (a) `mcp_servers` sozinho é **erro de
      validação** — a API exige também uma entrada
      `tools[{type: mcp_toolset, mcp_server_name}]` por servidor mais o beta
      `mcp-client-2025-11-20`, e um servidor sem toolset faz a requisição
      INTEIRA ser rejeitada com 400 genérico; as duas listas passaram a sair
      do mesmo laço, e `validar()` cobra a invariante; (b) **busca web não
      precisa de MCP** — é ferramenta nativa (`web_search_20260209`), sem
      servidor para hospedar, sem credencial e com citação de fonte
      embutida, que é literalmente o critério de pronto da fase; (c) **envio
      de notificação NÃO é ferramenta do agente** — dar ao modelo uma
      ferramenta de envio transfere a ele a decisão de mandar, para quem e
      quantas vezes; o envio fica determinístico no script, depois de o
      agente compor o texto
- [x] **Agente de relatório** (Fase 4 do plano, 2026-08-16): `src/agente/`
      (`dados` → `prompt` → `relatorio` → `entrega`) + migração 009 +
      `GET /relatorio` + cartão "Leitura do dia" na tela de Carteira. Ver
      `docs/AGENTE.md`.
      O guarda-corpo central é o que o agente **não** recebe: entra o
      VEREDITO de cada critério (aprovado/reprovado, com o valor comparado e
      o limiar), nunca o dado de mercado cru. Com IV rank, delta e preço
      soltos o modelo poderia reavaliar — e um modelo que pode reavaliar
      eventualmente discorda e escreve "esta parece elegível apesar de
      reprovada". As seis proibições do prompt são cobradas por teste,
      TRECHO A TRECHO (`GUARDA_CORPOS`): ideia some em paráfrase, trecho não.
      Regra nova que a busca web criou: o agente não usa busca para NÚMERO.
      Se procurasse "cotação de PETR4" acharia, e passaria a existir um
      terceiro preço competindo com o do ETL e o do modelo, sem procedência
      no banco
- [x] **Timer próprio para o relatório** (`opcoes-ia-relatorio.timer`, 17h30):
      o timer de pregão dispara 14x por dia útil, e encadear o agente ali
      seria 14 chamadas de LLM para resumir o mesmo dia. Diferença deliberada
      entre os dois: o do relatório tem `Persistent=true` e o do pregão não —
      avaliação intradiária perdida não deve rodar de madrugada sobre preço
      velho, mas relatório perdido ainda vale, porque descreve um dia que já
      aconteceu
- [x] **Entrega determinística e alerta independente**: `src/agente/notificar.py`
      envia o relatório por SMTP depois de ele ser gravado, sem dar ferramenta
      de envio ao modelo; `scripts/alertar_pregao.py` +
      `opcoes-ia-alerta.timer` alertam ausência, falha, órfão ou banco fora do
      ar por caminho separado. Sem SMTP configurado, ambos deixam erro
      explícito no journal
- [x] **`OPLAB_TOKEN` deixou de ser obrigatório por `config.py`**: o provedor
      foi abandonado e só a implementação legada de `fetch_options.py` o
      consome. Se esse ETL for invocado sem token, falha explicitamente; API,
      pipeline e bootstrap não são mais bloqueados por uma integração fora de
      uso
- [x] **Messages API validada em runtime Fargate** em 2026-08-17: a etapa
      `relatorio_anthropic` da execução diária
      `73c34ae4-aa50-4db7-a882-861d793da7dc` recebeu HTTP 200 e persistiu o
      relatório no Neon. Isso valida a viagem da composição diária; o CLI
      isolado `src.agente.verificar` continua útil para exercitar busca/citação
- [x] **Infraestrutura híbrida serverless provisionada** em `sa-east-1`:
      Lambda/API Gateway, Cognito, ECR, Fargate, EventBridge, CloudWatch,
      SNS/Budget, Secrets Manager, frontend S3 privado/CloudFront e state S3.
      Smokes reais de Lambda,
      `intraday`, `daily` e `alert` foram executados em 2026-08-17. Depois do
      corte que confirmou ausência de timers locais, os três schedules foram
      habilitados. Ver `docs/RUNBOOK-CLOUD.md`
- [x] **Cutover serverless validado**: quota Lambda
      efetiva subiu para 1000 e reserved concurrency 20 foi aplicada após o
      smoke com 2 produzir 20 throttles/5xx. SMTP não está configurado e ainda
      falta observar uma rodada agendada completa. Frontend CloudFront,
      subscription SNS e login Cognito/PKCE foram validados; timers systemd
      permanecem apenas como fallback. Um intraday EventBridge real concluiu
      com exit 0; por decisão do titular, daily/alert naturais não foram
      aguardados porque ambos já tinham smoke manual na mesma task definition
- [ ] **Custo AWS precisa de observação no primeiro mês**: em 2026-08-17 o
      Budget mostrava USD 1,387 atual e USD 2,527 projetado contra teto USD 5.
      Há 20 alarmes CloudWatch ainda sem custo observado; Brapi, Anthropic e
      Neon não entram nesse orçamento
- [ ] **Scan da imagem operacional tem risco residual sem correção**: a base
      Trixie atual reduziu para 4 CRITICAL e 8 HIGH, todos sem
      `fixed_in_version` no ECR em 2026-08-17. O release bloqueia severidade
      corrigível e reporta unfixed, alinhado ao `ignore-unfixed` do Trivy
- [ ] **`prob_exercicio_vencimento` não inclui exercício antecipado** — mede
      só o vencimento. Para quem vende call coberta num contrato americano, a
      pergunta real é maior que essa. Sai como ressalva em toda linha
      americana, mas segue sendo limite do número, não do texto
