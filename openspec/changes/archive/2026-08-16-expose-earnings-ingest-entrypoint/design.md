## Context

Ver `proposal.md` — Why. O que importa para o desenho:

- Toda a lógica já existe e é testada: `EarningsEventService.coletar()`,
  `_agrupar()`, `registrar()` e `ingerir()`, mais `resolution.aplicar` como
  portão único de escrita. Esta change **não** acrescenta regra de negócio —
  acrescenta a manivela.
- `service.coletar()` já isola falha por provider (`ProviderIndisponivel` e
  `Exception` viram log e `continue`). O que falta é essa informação chegar
  ao operador, não ao log apenas.
- `EarningsEventService.__init__` aceita `providers: list[...] | None` e cai
  em lista **vazia** quando nada é passado. Um entrypoint que instanciasse o
  serviço sem providers rodaria com sucesso e consolidaria zero eventos —
  falha silenciosa com cara de sucesso, exatamente o modo de falha que o
  serviço inteiro existe para impedir.
- `providers/__init__.py` está vazio: não há fábrica que traduza nome de
  fonte em instância. É a peça a criar.
- Os três providers têm custo muito diferente: `ManualProvider` só lê uma
  tabela local; `CvmProvider` baixa e descompacta o dump IPE; `YahooProvider`
  importa `yfinance` e sai para a rede.

## Goals / Non-Goals

**Goals:**

- Tornar executável, por CLI e por workflow, o ciclo que já está implementado.
- Deixar a falha de fonte visível para quem operou o comando, não só no log.
- Fazer a mensagem de destravamento do relatório descrever algo que funciona
  de ponta a ponta.

**Non-Goals:**

- Não muda regra de resolução, precedência, score de confiança ou modelo.
- Não adiciona provider novo (Fase 3 continua fora).
- Não resolve o bloqueio de dados de opções da Brapi: mesmo com a agenda
  consolidada, `fetch_options` continua em 403 no plano Free. Esta change
  remove um dos dois bloqueios para a primeira sugestão real, não os dois.
- Não muda a política `politica_resultado_desconhecido` nem o comportamento
  de `bloquear`.

## Decisions

### 1. Módulo próprio (`src/earnings/ingest.py`), não um subcomando de `manage`

`manage.py` é a gestão do espelho manual: fala com uma tabela local, não sai
para a rede, e todo comando dele é uma edição do que o usuário afirmou. A
consolidação é outra natureza de operação — lê fontes, resolve conflito e
escreve o consolidado.

Além disso o passo do workflow precisa de um alvo estável e sozinho; embutir
em `manage` faria o `daily-etl.yml` chamar `manage ingest`, sugerindo que a
automação faz gestão manual.

*Alternativa considerada:* auto-ingestão no fim de `manage add`. Descartada
com o usuário: tornaria a mensagem atual do relatório correta sem mudança,
mas mistura gravação local com execução de providers e não resolve a
reconsolidação diária — datas de trimestres novos continuariam sem entrar
sozinhas.

### 2. Fábrica de providers por nome, com `manual` como padrão

Um mapa nome → construtor em `providers/__init__.py`, consumido pelo
entrypoint. Padrão: `["manual"]`.

`manual` é a única fonte com autoridade para `CONFIRMED`, é determinística e
não depende de rede — o que faz dela a única candidata sensata para o padrão
de uma operação que roda dentro do pipeline diário. `cvm` e `yahoo` entram
por `--fontes`.

Nome desconhecido levanta erro nomeando o valor inválido e as fontes
válidas, **antes** de qualquer I/O. Rodar o subconjunto reconhecido
produziria "nenhum evento" por um motivo invisível — a mesma classe de falha
silenciosa que a decisão 3 trata.

*Alternativa considerada:* rodar as três por padrão. Descartada com o
usuário: baixar o dump da CVM e chamar o Yahoo a cada rodada é caro para uma
operação cujo valor principal é promover o que o usuário já digitou.

### 3. Lista de providers vazia é erro, não execução vazia

O entrypoint SHALL construir pelo menos um provider antes de instanciar o
serviço. É a consequência direta do default `providers or []` em
`EarningsEventService.__init__`: sem essa guarda, `--fontes ""` consolidaria
zero eventos e reportaria sucesso.

### 3b. `ingerir()` aceita uma coleta já feita (decidido na implementação)

`ingerir()` faz `coletar() → _agrupar() → registrar()` e devolve apenas
`list[EarningsEvent]` — o resultado por fonte morre lá dentro. Mas a decisão
4 exige saber quais fontes responderam. Chamar `coletar()` para reportar e
`ingerir()` para gravar consultaria cada fonte duas vezes, e o provider da
CVM baixa o dump IPE a cada chamada.

`ingerir()` ganha `coletado: dict | None = None`, aditivo e
retrocompatível: `None` mantém o comportamento atual. O entrypoint coleta
uma vez, reporta e passa adiante.

*Alternativa considerada:* o entrypoint replicar o corpo de `ingerir()`
chamando o `_agrupar()` privado. Descartada: duplica orquestração e faz o
comando divergir em silêncio se `service.py` mudar.

*Alternativa considerada:* `ingerir()` devolver coleta e eventos juntos.
Descartada: quebra os chamadores existentes por um problema menor que isso.

Isto revisa o "nenhuma mudança em `service.py`" declarado no Impact do
`proposal.md`: a mudança existe, é de uma linha e não toca regra de
resolução nem precedência.

### 4. Falha de fonte sobe ao código de saída quando é total

`coletar()` já isola falha por provider. O entrypoint compara quantas fontes
foram pedidas com quantas responderam:

- Todas responderam → sucesso.
- Algumas falharam → sucesso, com as falhas nomeadas na saída (fonte e
  motivo). O dado que veio é bom e a avaliação deve prosseguir.
- **Todas falharam** → código de saída diferente de zero.

O último caso importa porque "consolidei 0 eventos" e "não consegui falar
com fonte nenhuma" levam a ações opostas do usuário, e no workflow diário a
diferença entre passo verde e passo vermelho é a única coisa que ele vai
ver.

### 5. Escopo de tickers vem de `posicoes`, não de `ativos`

Consulta os tickers de posições em ação em aberto — o mesmo conjunto que
`executar_avaliacao_carteira` percorre. Manter os dois alinhados por
construção evita o caso em que a agenda é consolidada para um ativo que
ninguém avalia, ou pior, não é consolidada para um que é avaliado.

Sem posição aberta e sem `--tickers`, encerra com aviso e sem consultar
fonte alguma.

*Alternativa considerada:* varrer `ativos`. Descartada com o usuário: gasta
chamada de provider em ativo sem posição.

### 6. Posição do passo no `daily-etl.yml`

Entre a coleta e a avaliação de estratégia. A consolidação depende de
`posicoes` (que é entrada manual, sempre presente) e não depende de cotação
nem de opção; a avaliação depende da consolidação. Rodar depois da avaliação
só teria efeito no dia seguinte.

Sem `continue-on-error`: uma agenda desatualizada bloqueia sugestão de forma
silenciosa, que é justamente o que esta change existe para acabar. A exceção
é o caso "nada a consolidar" da decisão 5, que é sucesso.

## Risks / Trade-offs

- **O padrão `manual` faz o passo do workflow não descobrir nada sozinho.**
  Consolidar só o que o usuário digitou significa que o pipeline diário não
  traz datas novas por conta própria. → Aceito e explícito: é o padrão
  conservador, e `--fontes manual,cvm` no workflow é uma linha de mudança
  quando a cobertura da CVM for considerada confiável o bastante. A
  alternativa — rede por padrão — troca previsibilidade por cobertura numa
  operação que precisa ser confiável.

- **Dois caminhos de escrita conceituais em `earnings_events`** (o comando e,
  no futuro, qualquer outro chamador de `ingerir`). → Mitigado por
  construção: `registrar()` sempre passa por `resolution.aplicar`, que é o
  portão único de precedência. O entrypoint não escreve direto.

- **A change não produz sugestão sozinha.** Depois dela, o critério de
  resultado passa a ser verificável, mas `fetch_options` continua em 403. →
  Declarado como não-objetivo. A validação usa opção sintética, como já foi
  feito na change de valorização a mercado.

- **`--tickers` pode divergir da carteira num workflow de outro repositório
  ou fork.** → Mitigado por o padrão ser derivado da carteira; a lista
  explícita é override consciente.

## Migration Plan

Sem migração de banco. `earnings_events` e `earnings_manual_entries` já
existem (migrações 001 e 002) e nenhuma coluna muda.

1. Fábrica de providers em `providers/__init__.py` + testes.
2. `src/earnings/ingest.py` com a CLI e os códigos de saída + testes.
3. Mensagem de destravamento em `report/daily.py` + teste.
4. Passo no `daily-etl.yml`.
5. `CLAUDE.md`: sequência completa em "Comandos úteis" e correção do estado
   atual.
6. Validação de ponta a ponta no banco local: registrar data, consolidar,
   confirmar que `proximo_evento()` devolve a data e que a avaliação sai de
   `INDISPONIVEL`.

**Rollback:** `git revert`. O único efeito colateral no banco são linhas em
`earnings_events`, que já eram esperadas pelo schema e são reconstruíveis
rodando a consolidação de novo.

## Open Questions

- Quando a cobertura da CVM for validada em produção pessoal, vale promover
  `cvm` ao conjunto padrão do workflow? Deferível: é trocar o valor de um
  argumento, não muda requisito nem quebra nada desta change.
- Consolidar automaticamente ao registrar (`manage add`) continua sendo uma
  conveniência possível no futuro. Fica de fora aqui por decisão 1, e
  adicioná-la depois não invalida nada — o comando continua sendo o caminho
  do workflow.
