> **NOTA (2026-08-15): esta change foi parcialmente superada.** A parte de
> "fonte manual de datas de resultado" foi substituída, com escopo maior,
> pelo Earnings Event Service já implementado em `src/earnings/` (modelo
> multi-fonte, score de confiança, resolução de conflitos e
> `EarningsRiskService`). A investigação que motivou a troca está em
> `docs/` e no artefato de comparação de fontes.
>
> **O que desta change continua válido e pendente:** os itens (2) e (3) —
> separar em `avaliar()` os campos de mercado do critério de resultado, dar
> três estados ao critério, e a política configurável em `params.yaml`.
> Nada disso foi feito: a Fase 1 do serviço deliberadamente não tocou em
> `src/strategy/covered.py`. Reescrever esta change antes de aplicá-la.

## Why

Hoje `executar_avaliacao_carteira()` **não consegue emitir nenhuma sugestão,
em nenhuma circunstância** — nem com dados de opções perfeitos. Em
`src/strategy/covered.py`, `_opcoes_call_candidatas` fixa
`dias_para_resultado = None` (não há fonte de calendário de resultados), e
`avaliar()` trata qualquer campo obrigatório nulo como "dado insuficiente"
e retorna antes de olhar IV rank, delta, prêmio ou exposição. O resultado é
que todo par posição×opção é reprovado por um critério que nunca teve como
ser avaliado.

Isso está documentado como "gap conhecido", mas a redação subestima o
efeito: o gap não remove um critério de seis, ele **curto-circuita a
avaliação inteira**. Enquanto ele existir, destravar o ETL de opções (hoje
bloqueado no plano Free da Brapi, R$ 139,99/mês para o Pro) não produziria
uma única sugestão — ou seja, o produto continuaria sem entregar sua função
principal mesmo após um gasto recorrente.

Investigação de 2026-08-15 confirmou que **não existe fonte automática
viável**: o plano Free da Brapi libera apenas o módulo `summaryProfile`
(`get_stock_income_statement` retorna 403), e mesmo o plano Pro expõe
apenas datas de balanços *publicados*, não a agenda *futura* de divulgação
de resultados. Derivar a próxima data a partir do histórico seria estimar
um valor — proibido pela regra 1 do projeto.

## What Changes

- **Nova fonte manual de datas de resultado.** Tabela `eventos_resultado` e
  CLI de gestão, no mesmo espírito do espelho manual já usado para posições
  (`src/portfolio/manage.py`): o usuário registra a data que leu no site de
  RI da empresa. Dado informado por humano, com data de registro e origem
  rastreadas — nunca inferido pelo sistema.
- **Critério de resultado deixa de abortar a avaliação.** `avaliar()` passa
  a separar dois grupos: campos de mercado que nunca podem ser assumidos
  (IV rank, delta, preço, dias até vencimento, exposição), que seguem
  abortando com "dado insuficiente"; e o critério de resultado, que ganha um
  terceiro estado `indisponivel` e é avaliado *junto com* os demais, de modo
  que o motivo real de reprovação fique visível.
- **Política configurável para data desconhecida.** Novo parâmetro
  `politica_resultado_desconhecido` em `params.yaml`, com dois valores:
  `bloquear` (padrão — preserva a postura conservadora atual: sem data
  registrada, nenhuma sugestão é emitida para aquele ativo) e `sinalizar`
  (emite a sugestão marcada como pendente de verificação manual da agenda).
  O padrão `bloquear` mantém o comportamento observável de hoje para quem
  não cadastrar nada.
- **Relatório passa a explicar o bloqueio.** Nova seção listando avaliações
  bloqueadas por falta de data de resultado, mostrando quais critérios já
  passaram e como registrar a data — em vez do atual "Nenhuma sugestão
  hoje." sem explicação.

Nenhuma mudança **BREAKING**: com `params.yaml` sem o novo parâmetro, o
default `bloquear` reproduz o comportamento atual (zero sugestões quando
não há data registrada).

## Capabilities

### New Capabilities
- `earnings-calendar`: registro manual, consulta e rastreabilidade das datas
  de divulgação de resultado trimestral dos ativos da carteira, incluindo o
  tratamento explícito do estado "data desconhecida".

### Modified Capabilities
- `covered-strategy-execution`: o critério de evento de resultado deixa de
  ser um campo obrigatório que aborta a avaliação e passa a ter três estados
  (atendido / não atendido / indisponível), com política configurável para o
  estado indisponível. Requisito "Todos os critérios precisam passar" é
  refinado para distinguir *reprovado* de *não verificável*.
- `daily-portfolio-report`: o relatório passa a reportar explicitamente as
  avaliações bloqueadas por data de resultado desconhecida, com os critérios
  já verificados e a ação necessária para destravar.

> Nota: `openspec/specs/` ainda está vazio porque a change
> `build-portfolio-mvp-flow` não foi arquivada/sincronizada. As duas
> capabilities modificadas acima existem hoje apenas como deltas dentro
> daquela change; os caminhos usados aqui seguem a mesma organização.

## Impact

- **Código**: `src/strategy/covered.py` (separação dos grupos de campos,
  terceiro estado do critério, leitura da política), `src/report/daily.py`
  (nova seção de avaliações bloqueadas), novo módulo de gestão de eventos
  de resultado.
- **Banco**: nova tabela `eventos_resultado` via
  `src/db/migrations/` (nunca editando `schema.sql` retroativamente,
  conforme regra 4 do projeto).
- **Configuração**: novo parâmetro `politica_resultado_desconhecido` em
  `skills/covered-options-strategy/params.yaml` e o critério correspondente
  documentado em `SKILL.md`.
- **Testes**: cobertura dos três estados do critério e das duas políticas;
  os testes atuais que assumem "campo nulo ⇒ dado insuficiente" para
  `dias_para_resultado` precisam ser atualizados.
- **Não afetado**: ETL de opções (segue bloqueado por plano — esta change é
  independente e não depende de upgrade), execução de ordens (continua
  inexistente por design).
