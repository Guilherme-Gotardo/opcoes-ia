## Context

Ver `proposal.md` — Why. O que importa para o desenho:

- `ativos` já existe desde o `schema.sql` inicial: `ticker` (PK), `nome`,
  `tipo`, `cnpj_raiz`, `criado_em`. Nenhuma migração é necessária.
- `posicoes.ticker` **não** tem FK para `ativos` — por isso é possível hoje
  registrar posição num ticker que a coleta não consegue acompanhar. A
  validação tem de ser feita em código.
- `src/portfolio/manage.py` e `src/earnings/manage.py` estabelecem o padrão:
  exceção própria de validação (`PosicaoInvalida`, `EntradaInvalida`),
  funções de domínio puras de CLI, e `main(argv=None)` com
  `parser.exit(2, ...)` para erro de entrada.
- `CvmProvider._mapa_cnpj_para_tickers` já avisa sobre `cnpj_raiz` ausente e
  já decidiu pular em vez de falhar — só o texto do aviso muda.
- `fetch_quotes` insere direto em `cotacoes` dentro de um `try` por ticker;
  a violação de FK sobe como exceção genérica e vira "Falha ao coletar
  cotação de X: <erro cru do Postgres>".

## Goals / Non-Goals

**Goals:**

- Tornar possível preparar uma base nova sem `INSERT` manual.
- Fazer o erro de ativo não cadastrado dizer o que fazer, nos três pontos
  onde ele aparece (coleta, registro de posição, aviso da CVM).
- Deixar a função de domínio pronta para a interface chamar.

**Non-Goals:**

- Não busca nome nem CNPJ de provedor externo.
- Não remove ativo (exigiria decidir o destino do histórico que aponta para
  ele).
- Não adiciona FK de `posicoes.ticker` para `ativos` — ver decisão 3.
- Não mexe na regra de `cnpj_raiz` ser opcional.

## Decisions

### 1. Módulo próprio `src/assets/`, espelhando `src/portfolio/`

`assets/manage.py` com as funções de domínio e a CLI, no mesmo formato dos
dois `manage.py` existentes. A simetria importa mais que a economia de um
diretório: quem sabe usar `portfolio.manage` sabe usar este sem ler nada.

*Alternativa considerada:* subcomando de `portfolio.manage`. Descartada:
ativo e posição são entidades distintas — o ativo é referência, a posição é
patrimônio — e um deles existe sem o outro.

### 2. Ticker desconhecido FALHA; o ativo não é criado sozinho

Registrar posição em ticker não cadastrado levanta erro citando o comando
de cadastro.

Criar o ativo automaticamente exigiria inventar o `nome` — e "nunca estime
ou chute um valor" é a regra 1 do projeto. Um ativo chamado `PETR4` com nome
`PETR4` é dado inventado com aparência de dado bom, exatamente o que o
`EarningsEventService` inteiro existe para impedir em outro domínio.

Consequência assumida: cadastrar a carteira num banco novo passa a ter dois
passos. É o mesmo formato de "registrar não é consolidar" que a change de
earnings deixou explícito — e, como lá, a mensagem de erro carrega o segundo
passo.

### 3. Validação em código, não FK nova em `posicoes`

Poderia-se adicionar `posicoes.ticker REFERENCES ativos(ticker)` e deixar o
banco recusar. Não é o caminho por dois motivos:

1. `posicoes.ticker` guarda **código de opção** quando `tipo_ativo='OPCAO'`
   (ex.: `PETRJ380`), e códigos de opção não são — e não devem ser — linhas
   em `ativos`. Uma FK quebraria toda posição em opção.
2. A mensagem do banco é a que estamos tentando esconder do usuário.

Para posição em opção, o que precisa existir é o **ativo-objeto**. Derivá-lo
do código da opção exigiria parsear o código, o que o projeto não faz em
lugar nenhum; então a validação de ativo cadastrado se aplica a `ACAO`, e
para `OPCAO` fica registrada como limitação conhecida — a opção só entra em
`opcoes` (que tem FK real para `ativos`) pelo ETL, que já valida o
ativo-objeto.

### 4. `fetch_quotes` verifica antes de inserir, não traduz exceção

Consultar se o ticker existe antes do `INSERT` e reportar "ativo não
cadastrado" é mais direto do que capturar `ForeignKeyViolation` e adivinhar
qual FK falhou. Custa uma consulta por execução (não por ticker, se a lista
for carregada de uma vez).

Traduzir a exceção acoplaria a mensagem ao nome da constraint no Postgres —
que muda se o schema for reorganizado.

### 5. O aviso do `CvmProvider` passa a citar o comando

Trocar o `UPDATE ativos SET cnpj_raiz = ...` cru pelo comando de cadastro.
Mudança de texto, sem alteração de comportamento: continua pulando o ticker
sem CNPJ em vez de falhar, pela razão já documentada lá.

### 6. Cadastro é upsert por ticker

Registrar um ticker já cadastrado corrige os dados em vez de duplicar ou
falhar — `ON CONFLICT (ticker) DO UPDATE`, mesmo padrão de
`earnings_manual_entries`. Corrigir o nome de um ativo é operação legítima e
frequente o bastante para não merecer um comando separado; e as referências
de `cotacoes` sobrevivem porque a PK não muda.

## Risks / Trade-offs

- **Mais um passo no onboarding.** Cadastrar ativo antes de cadastrar posição
  é fricção real numa ferramenta pessoal. → Mitigado por a mensagem de erro
  trazer o comando pronto, e por ser uma vez por ativo, não por operação. A
  alternativa (inventar nome) tem custo maior e invisível.

- **Validação só para `ACAO`** (decisão 3) deixa posição em opção sem a
  mesma proteção. → Aceito e documentado: opção entra em `opcoes` pelo ETL,
  que tem FK real, e o caminho manual de posição em opção é raro. Registrado
  como limitação conhecida, não como esquecimento.

- **A interface vai querer cadastrar ativo com menos fricção** — provavelmente
  um formulário que busca o nome na Brapi. → Fora de escopo aqui de
  propósito: se a busca automática for adicionada depois, ela preenche um
  campo que o usuário confirma, o que é diferente de gravar sozinha. A função
  de domínio desta change não impede isso.

## Migration Plan

Sem migração de banco. Ordem:

1. `src/assets/manage.py` (domínio + CLI) e testes.
2. Validação em `src/portfolio/manage.py` e testes.
3. Mensagem em `src/etl/fetch_quotes.py` e testes.
4. Texto do aviso em `src/earnings/providers/cvm.py`.
5. Documentação (`CLAUDE.md`, `docs/RUNBOOK-POSTGRES.md`).
6. Validação de ponta a ponta: base limpa → cadastrar ativo → cadastrar
   posição → coletar cotação.

**Rollback:** `git revert`. Nenhum dado é reescrito; os ativos cadastrados
continuam válidos porque a tabela já existia.

## Open Questions

- Derivar o ativo-objeto a partir do código da opção (`PETRJ380` → `PETR4`)
  permitiria estender a validação a posições em opção. Deferível: exige uma
  regra de parsing de código B3 que o projeto não tem hoje, e não bloqueia
  nada desta change.
