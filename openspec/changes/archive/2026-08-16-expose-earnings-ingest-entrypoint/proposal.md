## Why

`EarningsEventService.ingerir()` existe em `src/earnings/service.py:100` e
**não é chamado por nada** — nenhuma CLI, nenhum ETL, nenhum workflow. Só os
testes o exercitam.

A cadeia real é `manage add` → `earnings_manual_entries` → `ManualProvider` →
`ingerir()` → `earnings_events` → `proximo_evento()`. O elo `ingerir()` não
tem entrypoint, então a ponta que o usuário opera nunca alcança a ponta que
o motor de opções consulta: `proximo_evento()` devolve `None`, o critério de
resultado fica `INDISPONIVEL` e a política `bloquear` impede a sugestão.

Isso foi observado de ponta a ponta em 2026-08-16: com a data registrada por
`manage add` e confirmada em `earnings_manual_entries`, `earnings_events`
continuou vazia e a avaliação seguiu bloqueada. **Nenhuma sugestão de covered
call pode ser emitida enquanto isso existir**, mesmo com todos os critérios
de mercado aprovados — que é exatamente o estado de hoje, depois que a
valorização a mercado destravou o critério de exposição.

Agrava o problema o fato de o relatório diário imprimir
`→ destrave com: python -m src.earnings.manage add ...` como se fosse
suficiente. Quem seguir a instrução ao pé da letra continua sem sugestão e
sem explicação — a mensagem que existe para acabar com o silêncio produz
outro silêncio.

## What Changes

- **Novo comando de ingestão** (`python -m src.earnings.ingest`) que executa
  o ciclo coleta → resolução → persistência do serviço já implementado.
  Nenhuma regra de resolução muda: o comando é a manivela que faltava, não
  uma segunda lógica.
- **Seleção de fontes explícita.** Por padrão roda apenas o provider
  `manual` — offline, determinístico e a única autoridade para `CONFIRMED`.
  `cvm` (baixa o dump IPE) e `yahoo` (rede + `yfinance`, só `ESTIMATED`)
  entram por opção explícita. Fonte desconhecida falha alto em vez de ser
  ignorada em silêncio.
- **Escopo de tickers derivado da carteira.** Por padrão, os tickers de
  posições em aberto — os mesmos que o motor de opções avalia — com override
  explícito. Sem posição aberta e sem override, o comando avisa e não faz
  nada, em vez de varrer o banco inteiro.
- **Passo no `daily-etl.yml`**, entre a coleta e a avaliação de estratégia,
  para que a consolidação aconteça sozinha e datas de trimestres novos
  entrem sem intervenção.
- **Correção da mensagem de destravamento do relatório**, que passa a citar a
  sequência completa em vez de só o primeiro comando.

## Capabilities

### New Capabilities

Nenhuma. Toda a lógica de coleta, resolução e persistência já existe em
`src/earnings/`; esta change expõe o que está implementado.

### Modified Capabilities

- `earnings-calendar`: a data registrada manualmente passa a ter um caminho
  executável até a consulta que o motor de opções faz, com seleção de fontes
  e escopo de tickers definidos; falha de uma fonte não pode ser confundida
  com ausência de evento.
- `daily-portfolio-report`: a orientação de destravamento passa a descrever a
  sequência completa que realmente destrava a avaliação.

## Impact

- **Código:** novo módulo de entrypoint em `src/earnings/`; fábrica de
  providers em `providers/__init__.py` (hoje vazio); ajuste da mensagem em
  `src/report/daily.py` (`_renderizar_bloqueios`). Em `service.py`, um único
  parâmetro opcional em `ingerir()` para reaproveitar uma coleta já feita
  (`design.md`, decisão 3b) — nenhuma mudança em `resolution.py`,
  `confidence.py` ou nos providers, e nenhuma regra de decisão alterada.
- **Banco:** nenhuma migração. `earnings_events` e
  `earnings_manual_entries` já existem (migrações 001 e 002).
- **Automação:** `.github/workflows/daily-etl.yml` ganha um passo.
- **Documentação:** `CLAUDE.md` — a seção "Comandos úteis" passa a mostrar a
  sequência completa, e o estado atual deixa de afirmar que registrar a data
  basta para emitir sugestão.
- **Dependências:** nenhuma nova. `yfinance` e `requests` já são exigidos
  pelos providers existentes e só são exercitados quando a fonte é pedida.
- **Fora de escopo:** cobertura de novas fontes (EODHD, Twelve Data, Fase 3)
  e qualquer mudança nas regras de precedência entre providers.
