## Context

Ver `proposal.md` — Why para a motivação. O que importa para o desenho:

- `avaliar()` é uma função pura, sem I/O (decisão 4 do `design.md` da change
  `build-portfolio-mvp-flow`). Todo dado que ela consome chega pelos dicts
  `posicao`/`opcao`. Preço de mercado precisa entrar por aí, não por uma
  consulta dentro dela.
- `report/daily.py` e `strategy/covered.py` hoje montam cada um a sua própria
  noção de "valor da carteira", ambas a `preco_medio`. Esse é o formato do
  bug: duas implementações independentes da mesma conta, que divergiram do
  dado real ao mesmo tempo.
- `cotacoes` já tem tudo o que é preciso (`preco`, `coletado_em`, índice em
  `(ticker, coletado_em DESC)`). Nenhuma migração é necessária.
- O projeto já tem um padrão para "dado existe mas não é confiável o
  bastante": `EarningsRiskService` devolve `reliable` + `reason` em vez de
  `None` mudo. Frescor de cotação é o mesmo problema e merece a mesma forma.
- Não existe `openspec/specs/` neste repositório ainda — os deltas nunca
  foram sincronizados para specs principais. Os requisitos MODIFIED deste
  delta foram copiados da versão mais recente em
  `changes/unblock-earnings-calendar-criterion/`, que é a que corresponde ao
  código realmente em `master` (commit `02badbc`).

## Goals / Non-Goals

**Goals:**

- Uma única fonte de "valor a mercado de um ticker", consumida por relatório
  e estratégia, para que os dois números nunca mais divirjam.
- Ausência de cotação utilizável vira uma parada explícita e diagnosticável,
  com ticker e idade do dado — nunca um número plausível e errado.
- O critério de exposição volta a medir o que o nome diz, sem afrouxar o
  limite para operação genuinamente descoberta.

**Non-Goals:**

- Não introduz fonte de caixa/garantia da carteira. A fórmula de exposição
  passa a aceitar cobertura por caixa para covered put, mas o valor continua
  vindo de fora; `executar_avaliacao_carteira` segue sem gerar candidatas de
  put.
- Não muda de onde vêm as cotações (Brapi, `fetch_quotes`), nem a frequência
  de coleta.
- Não recalcula sugestões já persistidas. O histórico fica com a semântica
  antiga de exposição, e isso é registrado, não corrigido retroativamente.
- Não mexe em `_CAMPOS_MERCADO_OBRIGATORIOS` no que diz respeito ao critério
  de resultado — a semântica de três estados da change anterior fica intacta.

## Decisions

### 1. Um módulo de valorização compartilhado, não duas consultas parecidas

Criar `src/market/valuation.py` com a resolução de cotação vigente e as
contas de patrimônio/cobertura, consumido tanto por `report/daily.py` quanto
por `strategy/covered.py`.

A função de cotação devolve um resultado explícito — preço, momento da
coleta, `utilizavel: bool` e `motivo: str` quando não for — em vez de
`float | None`. Isso segue o formato de `EarningsRiskService.avaliar()`, e é
o que permite o relatório dizer "PETR4: cotação de 4 dias atrás" em vez de
"sem dado".

*Alternativa considerada:* consulta local em cada módulo, como hoje.
Rejeitada porque é exatamente a estrutura que produziu o bug — a divergência
entre relatório e critério de exposição só foi notada num teste manual de
ponta a ponta.

*Alternativa considerada:* uma view SQL de valorização. Rejeitada: a regra de
frescor vem de `params.yaml` e mudaria a view a cada ajuste de parâmetro,
além de tirar do Python a mensagem de erro que o usuário precisa ler.

### 2. Frescor em horas, com padrão que cobre um fim de semana

Novo parâmetro `cotacao_frescor_maximo_horas` em `params.yaml`, padrão **72**.
72 horas cobre a janela sexta-fechamento → segunda-abertura sem cotação nova,
que não é dado velho e sim ausência de pregão. Um feriado prolongado estoura
a janela, e nesse caso parar é o comportamento correto: ninguém deveria
decidir com preço de quatro dias sem ser avisado.

Valor ausente cai no padrão; valor inválido (não numérico, zero ou negativo)
falha alto, no mesmo formato de `PoliticaInvalida` — mudar postura de risco
por digitação errada é justamente o que o projeto evita.

*Alternativa considerada:* contar pregões em vez de horas. Mais correto em
teoria, mas exige um calendário de feriados da B3 que o projeto não tem e
que seria uma fonte de dado nova só para isso. Registrado em Open Questions.

*Alternativa considerada:* manter o implícito "coletada hoje" de
`_ultima_coleta`. Rejeitada: falha em toda segunda-feira antes da coleta e em
todo feriado, sem que nada esteja errado.

### 3. Exposição = notional descoberto, com cobertura medida em contratos

Fórmula da exposição nova de uma operação:

```
contratos_cobertos  = min(contratos, cobertura_disponivel_em_contratos)
notional_descoberto = (contratos - contratos_cobertos) * strike * 100
```

Para covered call, `cobertura_disponivel_em_contratos` = ações livres ÷ 100,
onde **ações livres** = ações em carteira menos as já comprometidas com calls
vendidas em aberto sobre o mesmo ativo. Sem esse desconto, duas calls
sucessivas sobre o mesmo lote de 100 ações apareceriam ambas como cobertas —
a segunda é descoberta e precisa contar.

Para covered put, a cobertura vem do caixa/garantia informado, convertido em
contratos por `caixa ÷ (strike × 100)`.

A comparação é feita em contratos, não em reais, porque cobertura de covered
call é entrega de ação: 100 ações cobrem 1 contrato independentemente da
relação entre preço de mercado e strike. Misturar valor de mercado das ações
com notional no strike reintroduziria uma diferença que não é risco.

A exposição **já existente** em opção do mesmo ativo passa a ser calculada
pela mesma fórmula (notional descoberto das posições em opção abertas), em
vez do atual `SUM(ABS(quantidade) * preco_medio)`, que somava custo de prêmio
— outra grandeza, na mesma conta.

*Alternativa considerada:* exposição total ao ativo (ações + opções) a
mercado. Descartada com o usuário: numa carteira de R$ 14 mil onde o ativo já
é a maior posição, o limite de 20% continua reprovando tudo — trocaria um
bloqueio por outro.

*Alternativa considerada:* contar só o prêmio recebido. Descartada: o número
é sempre pequeno, o critério nunca reprovaria e viraria decorativo.

### 4. Denominador do percentual: só posições em ação, a mercado

Patrimônio total = soma das posições em **ação** valorizadas a mercado.
Posições em opção ficam fora do denominador porque seu valor é derivado das
mesmas ações já contadas — incluí-las é a mesma contagem dupla que esta
change existe para remover, só que no denominador.

O relatório continua listando as posições em opção e seu valor a mercado
(pela última `opcoes.preco`); elas simplesmente não inflam o patrimônio
usado como base do percentual. Essa distinção precisa estar visível no
relatório, senão as colunas não somam e parece erro.

### 5. Preço de mercado entra em `avaliar()` pelo dict, mantendo a pureza

`posicao` ganha `preco_mercado: float | None` e `cotacao_em`. `avaliar()`
trata `preco_mercado is None` como pré-requisito estrutural não atendido —
checado junto do lote mínimo, **antes** dos critérios de mercado — devolvendo
motivo "dado insuficiente: sem cotação utilizável para <ticker>".

Fica antes porque sem preço de mercado nem o prêmio mínimo nem a exposição
podem ser calculados: não é um critério entre seis, é a base de dois deles.
Diferente do critério de resultado, aqui não há terceiro estado a oferecer —
não existe "avaliar os demais critérios mesmo assim".

`executar_avaliacao_carteira` resolve a cotação uma vez por posição (não por
par posição×opção) e injeta no dict.

### 6. `criterios_json` registra a base de valorização

O snapshot de critérios passa a gravar o preço de mercado e o `coletado_em`
usados. Sem isso, uma sugestão auditada meses depois não permite reconstruir
a conta — e o próprio motivo desta change é que o número exibido não dizia
sobre o que fora calculado.

## Risks / Trade-offs

- **O critério de exposição passa a aprovar toda covered call totalmente
  coberta, ficando efetivamente inerte no único tipo de operação que o MVP
  gera hoje.** → É o comportamento correto (a operação não adiciona risco
  direcional), mas remove um freio de concentração que o usuário podia
  imaginar que existia. Mitigação: a seção de exposição por ativo do
  relatório, agora a mercado, é o lugar honesto para ver concentração; e
  `SKILL.md` passa a dizer explicitamente que `exposicao_maxima_pct_ativo`
  limita opção **descoberta**, não concentração da carteira.

- **Tirar o fallback para `preco_medio` pode zerar as sugestões quando o
  `fetch_quotes` falhar.** → Trocar "nenhuma sugestão, sem explicação" por
  "nenhuma sugestão porque PETR4 está sem cotação há 4 dias" é o ponto: a
  parada é diagnosticável e o alerta nomeia o ticker e a idade. O modo de
  falha anterior — decidir sobre número errado — não era visível.

- **Janela de 72h aceita preço de sexta numa segunda de manhã.** → Aceito: é
  o último preço negociado, não uma estimativa. O `coletado_em` vai no
  relatório e no `criterios_json`, então a idade nunca fica implícita.

- **A mudança de semântica de exposição quebra a comparabilidade do
  histórico de `criterios_json`.** → Nenhuma sugestão foi emitida antes de
  2026-08-15 e a única existente é sintética, então o histórico afetado é
  desprezível. Registrado no proposal como BREAKING semântico.

- **Posições em opção fora do denominador mudam os percentuais do relatório
  em relação ao que o usuário viu ontem.** → Mitigação: o relatório declara a
  base do percentual junto do número.

## Migration Plan

Sem migração de banco. A ordem importa porque os dois consumidores precisam
da mesma base:

1. `src/market/valuation.py` + testes unitários (sem banco, cotação injetada).
2. `params.yaml`: `cotacao_frescor_maximo_horas`, com validação e padrão.
3. `strategy/covered.py`: `preco_mercado` no dict, pré-requisito estrutural,
   prêmio mínimo e exposição a mercado, nova fórmula de exposição.
4. `report/daily.py`: valorização, exposição, coluna de preço de mercado,
   alerta de cotação ausente/velha, patrimônio parcial declarado.
5. `SKILL.md` + `CLAUDE.md`.
6. Validação de ponta a ponta contra o banco local, comparando o patrimônio
   do relatório com a soma manual das cotações reais.

**Rollback:** a change é reversível por `git revert` — nenhum dado é
reescrito e nenhum schema muda. O único estado novo é o parâmetro em
`params.yaml`, ignorado por código antigo.

## Open Questions

- Frescor por pregão em vez de horas exigiria um calendário de feriados da
  B3. Deferível: o parâmetro em horas resolve o caso comum, e trocar a
  unidade depois não muda nenhum requisito desta change, só a implementação
  interna de `valuation.py`.
- Se o dashboard somente leitura (P2 do roadmap) precisar da mesma
  valorização, ele deve consumir `src/market/valuation.py` ou uma view? Não
  bloqueia nada aqui — a decisão pertence à change do dashboard.
