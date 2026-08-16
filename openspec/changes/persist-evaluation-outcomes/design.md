## Context

Ver `proposal.md` — Why. O que importa para o desenho:

- `executar_avaliacao_carteira()` já produz tudo: um `ResultadoAvaliacao` por
  par posição×opção, com `elegivel`, `motivo_nao_elegivel`,
  `bloqueado_por_resultado`, a lista de `CriterioAvaliado` com três estados, e
  `preco_mercado`/`cotacao_em`. Nada precisa ser recalculado — só gravado.
- `_opcoes_call_candidatas` avalia **todas** as calls do ticker. Hoje são
  zero (Brapi Free bloqueia opções); com cadeia real, 100+ séries por ativo.
- O bloqueio por data de resultado é **por ticker**: `_dias_para_resultado` é
  resolvido uma vez por posição e injetado em todas as candidatas daquele
  ativo. Se a data falta, todas as opções caem no mesmo motivo.
- `gerar_relatorio(data, avaliacoes)` recebe os resultados por argumento e
  filtra `bloqueado_por_resultado`. Só funciona no mesmo processo.
- Migrações 001 e 002 existem; a próxima é a 003. A regra do
  `README.md` de migrações é aditiva e idempotente.

## Goals / Non-Goals

**Goals:**

- Fazer o motivo de cada não-sugestão sobreviver ao fim do processo.
- Manter o volume proporcional à informação, não ao tamanho da cadeia.
- Desacoplar o relatório da execução que o alimentou.

**Non-Goals:**

- Nenhuma mudança de regra de decisão, limiar ou política.
- Endpoint da API — pertence à change da API, que passa a ter o que servir.
- Política de retenção/expurgo — ver riscos.
- Persistir a avaliação individual de cada opção.

## Decisions

### 1. Uma linha por (execução, ativo, motivo)

A chave do registro é o trio. `quantidade` diz quantas opções caíram ali, e
uma amostra representativa acompanha.

O dimensionamento é a razão. Com 2 ativos e cadeia real de ~100 séries, uma
linha por opção daria ~200 linhas por execução — e, no caso mais comum
(falta a data do ativo), as 100 linhas de um ticker seriam idênticas exceto
pelo código da opção. O conteúdo informativo é "falta a data da PETR4, e 100
opções seriam afetadas". A forma agregada grava exatamente isso.

Ordem de grandeza resultante: poucas linhas por ativo por execução — algo
como centenas de linhas por ano, contra dezenas de milhares.

*Alternativa considerada:* linha por opção. Descartada com o usuário: a tela
viraria uma lista repetitiva com um motivo só, e o custo de armazenamento
cresceria com o tamanho da cadeia em vez de com a informação.

### 2. Motivo é código normalizado, não a string livre

`motivo_nao_elegivel` hoje é texto montado para leitura
(`"critério(s) não atendido(s): iv_rank, delta"`). Agrupar por ele seria
agrupar por frase — quebraria ao primeiro ajuste de redação.

O registro usa um conjunto fechado de códigos, derivado do que a avaliação já
distingue:

| Código | Origem no `ResultadoAvaliacao` |
|---|---|
| `sugerida` | `elegivel = True` |
| `bloqueio_data_resultado` | `bloqueado_por_resultado = True` |
| `criterio_reprovado` | há critério em estado `REPROVADO` |
| `dado_insuficiente` | motivo começa com "dado insuficiente" |
| `pre_requisito` | lote insuficiente ou caixa insuficiente |

A ordem de classificação importa e é a mesma que `avaliar()` usa: reprovação
no mérito tem precedência sobre bloqueio por dado faltante. Um resultado cai
em exatamente um código.

### 3. Contagem por critério é sobreposta, e isso é correto

Para `criterio_reprovado`, o registro guarda `{"iv_rank": 8, "delta": 5}`.
Uma opção que reprova em ambos é contada nas duas.

É deliberado: a pergunta que a UI faz é "quantas foram barradas por este
critério", não "como as opções se dividem". Particionar exigiria eleger um
critério principal, o que seria inventar uma hierarquia que a regra de
negócio não tem — `avaliar()` trata todos os critérios como igualmente
obrigatórios.

A soma das contagens pode exceder `quantidade`, e isso precisa estar
documentado na coluna para não parecer inconsistência.

### 4. `sugestoes` não ganha status novo

Uma avaliação bloqueada não é uma sugestão. Além da semântica, o requisito
"Nenhuma execução automática" exige que toda sugestão persistida permaneça
`pendente` — introduzir `bloqueada` ali forçaria reinterpretar esse
requisito para acomodar algo que não é sugestão.

O registro do desfecho é tabela própria; `sugestoes` continua sendo o
conjunto do que passou. Quem quiser o total de uma execução cruza as duas
pela janela de tempo.

### 5. O relatório passa a ler do banco, mantendo o argumento

`gerar_relatorio` continua aceitando `avaliacoes`, mas deixa de depender
dele: sem o argumento, monta a seção a partir do registro persistido da
execução mais recente do dia.

Manter o argumento evita quebrar o chamador atual e os testes que o exercem.
Deixar de depender dele é o que permite gerar relatório num processo
separado — e é o que garante que relatório e API mostrem a mesma coisa, já
que passam a ler a mesma fonte.

*Alternativa considerada:* remover o argumento. Descartada: quebraria testes
existentes por um ganho de limpeza, num momento em que a prioridade é não
alterar o comportamento do relatório.

### 6. Gravação na mesma transação da avaliação

O desfecho é gravado dentro do mesmo `with get_connection()` que persiste as
sugestões, antes do `commit`. Uma execução que gravasse sugestões e falhasse
ao gravar o desfecho deixaria um estado em que a UI mostra sugestões sem
saber o que mais aconteceu.

## Risks / Trade-offs

- **Sem política de retenção, a tabela cresce para sempre.** → Aceito por
  ora: a forma agregada mantém o crescimento em ordem de centenas de linhas
  por ano, e decidir expurgo antes de ter histórico seria otimizar sem dado.
  Quando o volume justificar, é uma change própria — e a decisão vai ser
  melhor com o histórico real na mão.

- **A amostra representativa envelhece.** A "melhor candidata" gravada é a de
  uma execução específica; a série pode nem existir mais. → É amostra para
  leitura, não referência para operar. O registro precisa deixar isso claro,
  do mesmo modo que o relatório deixa claro que sugestão é para revisão
  humana.

- **A soma das contagens por critério pode passar do total** (decisão 3). →
  Documentado na coluna e no registro. Uma leitura ingênua poderia estranhar;
  o alternativo seria inventar uma hierarquia entre critérios.

- **Mais escrita no caminho da avaliação.** → Poucas linhas por execução,
  numa operação que já abre conexão e grava. Irrelevante frente ao custo de
  avaliar.

## Migration Plan

1. Migração `003`, aditiva e idempotente (`CREATE TABLE IF NOT EXISTS`), mais
   a mesma tabela em `schema.sql` — regras 3 e 4 do `README.md` de migrações.
2. Aplicar com `python -m src.db.bootstrap` no banco descartável e no Neon.
3. Repositório do registro + classificação de motivo, com testes sem banco.
4. `executar_avaliacao_carteira` passa a gravar o desfecho na mesma transação.
5. `report/daily.py` passa a ler do banco, mantendo o argumento.
6. Documentação, incluindo remover a limitação declarada na change da API.

**Rollback:** `git revert` do código. A tabela criada pode permanecer vazia
sem efeito — nenhuma outra parte do sistema passa a depender dela para
funcionar.

## Open Questions

- Quando a API expuser esse registro, vale agregar por janela (ex.: "há N
  dias reprovado por IV rank") no servidor ou no cliente? Deferível: não muda
  o que é persistido, só quem faz a conta.
