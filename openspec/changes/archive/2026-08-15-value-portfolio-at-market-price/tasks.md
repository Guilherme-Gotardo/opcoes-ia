## 1. Módulo de valorização compartilhado

- [x] 1.1 Criar `src/market/__init__.py` e `src/market/valuation.py`, o
      único lugar do projeto que traduz `cotacoes` em valor de posição
      (`design.md`, decisão 1).
- [x] 1.2 Implementar a resolução da cotação vigente de um ticker devolvendo
      um resultado explícito — preço, `coletado_em`, `utilizavel` e `motivo`
      quando não for utilizável — no formato de
      `EarningsRiskService.avaliar()`, nunca `float | None` mudo.
- [x] 1.3 Implementar a checagem de frescor contra a janela configurada,
      informando no `motivo` a idade da cotação encontrada (spec
      `covered-strategy-execution`, requisito "Cotação ausente ou fora da
      janela de frescor é dado insuficiente").
- [x] 1.4 Implementar o cálculo do patrimônio total a mercado somando apenas
      posições em ação, devolvendo separadamente os tickers que ficaram sem
      cotação utilizável (`design.md`, decisão 4).
- [x] 1.5 Implementar a cobertura disponível em contratos: ações em carteira
      menos as já comprometidas com calls vendidas em aberto sobre o mesmo
      ativo, dividido por 100 (`design.md`, decisão 3).
- [x] 1.6 Implementar o cálculo de notional descoberto de uma operação
      (`max(0, contratos − contratos_cobertos) × strike × 100`), com o caso
      covered put derivando a cobertura de caixa/garantia informado.
- [x] 1.7 Testes de `valuation.py` sem banco (cotação injetada): cotação
      fresca, cotação fora da janela, ticker sem cotação, patrimônio parcial,
      cobertura total, cobertura parcial, lote já comprometido por call
      vendida em aberto.

## 2. Parâmetro de frescor

- [x] 2.1 Adicionar `cotacao_frescor_maximo_horas` a
      `skills/covered-options-strategy/params.yaml` com padrão 72 e
      comentário explicando por que a janela cobre um fim de semana
      (`design.md`, decisão 2).
- [x] 2.2 Implementar a leitura validada do parâmetro: ausente cai no padrão;
      valor não numérico, zero ou negativo falha alto com erro explícito, no
      mesmo formato de `PoliticaInvalida`.
- [x] 2.3 Testes em `tests/test_params.py`: padrão aplicado na ausência,
      valor válido respeitado, valor inválido levanta erro.

## 3. Avaliação de estratégia a preço de mercado

- [x] 3.1 Estender o dict `posicao` de `avaliar()` com `preco_mercado` e
      `cotacao_em`, atualizando a docstring de contrato da função
      (`design.md`, decisão 5).
- [x] 3.2 Tratar `preco_mercado is None` como pré-requisito estrutural não
      atendido, checado junto do lote mínimo e antes dos critérios de
      mercado, com motivo que nomeia o ticker e a razão da indisponibilidade.
- [x] 3.3 Trocar a base do critério de prêmio mínimo de
      `posicao["preco_medio"] * 100` para o preço de mercado × 100 (spec
      `covered-strategy-execution`, cenário "Valor de posição vem da cotação,
      não do custo").
- [x] 3.4 Reescrever `_exposicao_pct_apos_operacao` sobre `valuation.py`:
      numerador = notional descoberto da operação + notional descoberto das
      posições em opção já abertas do ativo; denominador = patrimônio a
      mercado. Remover o `SUM(ABS(quantidade) * preco_medio)` sobre posições
      em opção, que somava custo de prêmio.
- [x] 3.5 Fazer `executar_avaliacao_carteira` resolver a cotação uma vez por
      posição (não por par posição×opção) e injetar no dict, pulando a
      posição com motivo explícito quando a cotação não for utilizável.
- [x] 3.6 Incluir preço de mercado e `coletado_em` usados no snapshot de
      `criterios_json` (`design.md`, decisão 6).
- [x] 3.7 Atualizar o cabeçalho de `src/strategy/covered.py`: remover o gap
      documentado de exposição sobre custo e descrever a nova semântica.
- [x] 3.8 Atualizar `tests/test_strategy_covered.py` para informar
      `preco_mercado` e cobrir: posição sem cotação vira dado insuficiente
      antes dos critérios de mercado; prêmio mínimo calculado a mercado;
      covered call totalmente coberta com exposição zero aprovada mesmo com
      strike alto; operação parcialmente descoberta contando só a diferença;
      opção descoberta já em carteira reprovando o critério sozinha.

## 4. Relatório diário a preço de mercado

- [x] 4.1 Fazer `_resumo_carteira` valorizar cada posição pela cotação
      vigente via `valuation.py`, mantendo `preco_medio` no dict como base de
      custo (spec `daily-portfolio-report`, requisito "Carteira reportada a
      preço de mercado").
- [x] 4.2 Valorizar posições em opção pela última `opcoes.preco`, mantendo-as
      fora do denominador do percentual de exposição e deixando essa
      distinção visível no texto do relatório (`design.md`, decisão 4).
- [x] 4.3 Calcular a exposição percentual por ativo-objeto sobre valores a
      mercado, no numerador e no denominador.
- [x] 4.4 Adicionar coluna de preço de mercado e do momento da cotação à
      tabela de posições, ao lado do preço médio, e trocar o rótulo
      "Patrimônio total (proxy, a preço médio de entrada)" pelo valor a
      mercado.
- [x] 4.5 Sinalizar cada posição sem cotação utilizável com ticker e idade da
      última cotação, sem exibir valor de mercado estimado para ela.
- [x] 4.6 Declarar o patrimônio como parcial quando alguma posição ficar sem
      valorização, identificando quais ficaram de fora, e omitir a ressalva
      quando a carteira inteira for valorizada.
- [x] 4.7 Atualizar `tests/test_report_daily.py`: patrimônio a mercado
      diferente do custo, preço médio ainda visível, ativo sem cotação
      sinalizado, patrimônio parcial declarado, carteira completa sem
      ressalva, exposição percentual consistente com a da avaliação.

## 5. Documentação

- [x] 5.1 Atualizar `skills/covered-options-strategy/SKILL.md`: explicitar
      que `exposicao_maxima_pct_ativo` limita opção **descoberta** por ativo,
      não concentração da carteira, e documentar
      `cotacao_frescor_maximo_horas`.
- [x] 5.2 Remover de `CLAUDE.md` os dois gaps fechados por esta change
      (contagem dupla em `exposicao_maxima_pct_ativo` e relatório a preço
      médio), e registrar o guardrail que sobra: concentração da carteira é
      visível no relatório, não barrada por critério.

## 6. Validação de ponta a ponta

- [x] 6.1 Rodar `pytest` completo e confirmar que a suíte existente de
      earnings e portfólio segue verde.
- [x] 6.2 Com o banco local, rodar `python -m src.etl.fetch_quotes`,
      `python -m src.strategy.covered` e `python -m src.report.daily`, e
      conferir o patrimônio do relatório contra a soma manual
      quantidade × cotação real de cada posição.
- [x] 6.3 Reproduzir o cenário que motivou a change: com posição real de
      PETR4 e uma call de strike acima do patrimônio, confirmar que o
      critério de exposição agora aprova em vez de reprovar por contagem
      dupla.
- [x] 6.4 Simular cotação fora da janela (envelhecendo `coletado_em` no banco
      local) e confirmar que a avaliação para com motivo explícito e que o
      relatório nomeia o ticker, a idade e o patrimônio parcial.
