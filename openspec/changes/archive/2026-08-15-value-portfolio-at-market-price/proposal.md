## Why

O sistema hoje decide e reporta sobre uma carteira que **não existe**: tanto
`report/daily.py` quanto `strategy/covered.py` valorizam posição por
`preco_medio` (custo de entrada), nunca por preço de mercado. No teste de
fluxo de 2026-08-15 o relatório mostrou R$ 14.250 contra R$ 18.469 a
mercado — 30% abaixo. A tabela `cotacoes` é lida em um único lugar
(`_ultima_coleta`, só para checar frescor), então o `fetch_quotes` — o único
passo do pipeline com dado real validado contra a API — não influencia
nenhuma saída além de suprimir um alerta.

Sobre esse número errado roda um critério errado:
`_exposicao_pct_apos_operacao` soma o notional cheio da opção
(`strike × 100`) como exposição **nova**, mas numa covered call esse notional
já está coberto pelas ações que a carteira possui — é contagem dupla. Com
patrimônio de R$ 14.250 e limite de 20%, o strike máximo que passa é
R$ 28,50, enquanto PETR4 negocia a R$ 42. Nenhuma covered call de PETR4 pode
passar, em nenhuma circunstância. Depois que o critério de resultado deixou
de curto-circuitar a avaliação (change anterior, já aplicada), este virou o
próximo bloqueio estrutural: destravar o ETL de opções da Brapi (R$ 139,99/mês
para o plano Pro) não produziria uma única sugestão enquanto ele existir.

## What Changes

- **Valorização a preço de mercado.** `report/daily.py` e `strategy/covered.py`
  passam a valorizar posição pela última cotação de `cotacoes`, não por
  `preco_medio`. O preço médio continua exibido no relatório, ao lado do
  preço de mercado, como base de custo — mas deixa de ser proxy de valor.
- **Ausência de cotação fresca vira "dado insuficiente", não fallback.**
  Sem cotação dentro da janela de frescor configurada, a avaliação daquela
  posição para por falta de dado e o relatório nomeia o ticker e a idade da
  última cotação. O sistema **SHALL NOT** cair silenciosamente para
  `preco_medio` — isso violaria a regra 1 do projeto (nunca estimar valor de
  mercado) misturando custo e mercado na mesma conta.
- **Janela de frescor configurável.** Novo parâmetro em `params.yaml` para a
  idade máxima aceitável de uma cotação, em vez do implícito "coletada hoje" —
  fim de semana e feriado não têm cotação nova e não devem parar a avaliação.
- **Exposição de operação coberta conta só a parte descoberta.**
  `_exposicao_pct_apos_operacao` passa a descontar do notional da opção a
  cobertura já existente na carteira (ações para covered call, caixa/garantia
  para covered put), com piso em zero. Uma covered call totalmente coberta
  adiciona exposição zero. O critério passa a medir o que o nome de
  `exposicao_maxima_pct_ativo` diz — opção descoberta por ativo — sem
  afrouxar nada para operação a descoberto no futuro.
- **BREAKING (semântica, não API):** o percentual de exposição gravado em
  `criterios_json` das sugestões muda de significado. Sugestões antigas
  permanecem legíveis, mas o número não é comparável ao novo.

## Capabilities

### New Capabilities

Nenhuma. Esta change corrige a semântica de capabilities existentes; não
introduz superfície nova.

### Modified Capabilities

- `covered-strategy-execution`: valorização a mercado no cálculo de prêmio
  mínimo e de exposição; cotação ausente/velha vira dado insuficiente
  explícito; exposição de operação coberta passa a ser líquida da cobertura
  já existente.
- `daily-portfolio-report`: patrimônio, valor de posição e exposição por
  ativo passam a ser reportados a preço de mercado, com preço médio ao lado
  como base de custo, e com alerta explícito quando faltar cotação.

## Impact

- **Código:** `src/strategy/covered.py` (`avaliar`, `_posicoes_acao_abertas`,
  `_exposicao_pct_apos_operacao`, `executar_avaliacao_carteira`),
  `src/report/daily.py` (`_posicoes_abertas`, `_resumo_carteira`,
  `_alertas`, `_renderizar_markdown`).
- **Configuração:** `skills/covered-options-strategy/params.yaml` ganha o
  parâmetro de frescor de cotação. `SKILL.md` precisa acompanhar a nova
  semântica de `exposicao_maxima_pct_ativo`.
- **Banco:** nenhuma migração. `cotacoes` já tem o que é preciso
  (`preco`, `coletado_em`, índice por `(ticker, coletado_em DESC)`).
- **Testes:** os testes de `avaliar()` que hoje passam `preco_medio` como
  base implícita de valor precisam passar a informar preço de mercado.
- **Documentação:** os dois gaps correspondentes em `CLAUDE.md` saem da
  lista de pendências.
- **Fora de escopo:** covered put continua sem fonte de caixa/garantia
  registrada; esta change define como a cobertura entra na conta, não de
  onde o saldo de caixa vem.
