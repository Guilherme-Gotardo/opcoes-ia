## Context

Ver `proposal.md — Why` para a motivação. O que importa para o desenho:

- `avaliar()` em `src/strategy/covered.py` já é uma função pura, testável sem
  banco (decisão 4 da change `build-portfolio-mvp-flow`). Essa separação é
  preservada aqui: a política e os três estados vivem na função pura; a
  origem da data vive na camada de persistência.
- Hoje `_CAMPOS_MERCADO_OBRIGATORIOS` mistura, num único tuple, dados que
  vêm de provedor de mercado com `dias_para_resultado`, que não vem de
  provedor nenhum. É essa mistura que produz o curto-circuito.
- `src/db/migrations/` é exigido pela regra 4 do projeto mas **ainda não
  existe** — nenhuma migração foi escrita até hoje, o schema foi aplicado
  direto de `schema.sql`. Esta change cria o diretório e a primeira
  migração, estabelecendo o padrão.
- A carteira é um espelho manual: posições já são digitadas pelo usuário.
  Uma fonte manual de datas de resultado é consistente com isso, não uma
  concessão nova.

## Goals / Non-Goals

**Goals:**
- Tornar possível emitir uma sugestão, hoje impossível por construção.
- Manter o comportamento observável inalterado para quem não configurar
  nada (default `bloquear`, sem datas registradas ⇒ zero sugestões).
- Tornar visível a diferença entre "reprovado" e "não verificável", tanto na
  avaliação quanto no relatório.

**Non-Goals:**
- Integrar qualquer fonte automática de calendário de resultados (nenhuma
  viável foi encontrada — ver `proposal.md`).
- Destravar o ETL de opções ou qualquer coisa dependente do plano Pro da
  Brapi. Esta change é independente e entrega valor sem gasto.
- Cobrir covered put (segue bloqueado pela ausência de registro de
  caixa/garantia, gap separado).
- Corrigir a valorização a preço médio em `report/daily.py` (gap separado,
  registrado no `CLAUDE.md`).

## Decisions

### 1. Fonte manual em tabela própria, não coluna em `ativos`

Uma tabela `eventos_resultado` (uma linha por evento) em vez de uma coluna
`proxima_data_resultado` em `ativos`.

**Por quê:** empresas divulgam trimestralmente, então o dado é uma série, não
um valor único. Uma coluna exigiria sobrescrever a cada trimestre, perdendo
o histórico e impossibilitando o requisito de rastreabilidade da correção.
Com uma tabela, "próxima data" é uma consulta (`MIN(data) WHERE data >=
referência`), e a correção vira um novo registro ou uma atualização
auditável.

**Alternativa considerada:** coluna em `ativos`. Descartada pelo acima.

### 2. Três estados como valor explícito, não `None` sobrecarregado

O critério de resultado passa a ter um estado próprio (`aprovado`,
`reprovado`, `indisponivel`) em vez de depender de `None` significando
"ausente".

**Por quê:** `None` já significa "dado de mercado ausente" e dispara o
caminho de aborto. Reusá-lo para um caso que **não** deve abortar é
exatamente o bug atual, em outra forma. Um estado explícito torna o
`CriterioAvaliado` autodescritivo e permite o relatório distinguir os casos
sem reinterpretar semântica.

**Impacto no dataclass:** `CriterioAvaliado.aprovado: bool` não consegue
representar três estados. Ele passa a carregar o estado; o campo booleano
é derivado ou substituído. Os testes atuais que leem `.aprovado` precisam
acompanhar — previsto em `tasks.md`.

### 3. `_CAMPOS_MERCADO_OBRIGATORIOS` perde `dias_para_resultado`

`dias_para_resultado` sai do tuple de campos que abortam a avaliação e passa
a ser tratado depois, junto dos demais critérios.

**Por quê:** é a correção mínima e direta do curto-circuito. Os outros cinco
campos continuam abortando, porque para eles a regra 1 do projeto se aplica
integralmente: não há como avaliar IV rank sem IV rank. Já a ausência de
data de resultado é uma informação em si — "não sabemos" — que o usuário
pode querer ver acompanhada do resto.

### 4. Política lida de `params.yaml`, validada na carga

`politica_resultado_desconhecido` entra em `params.yaml` junto dos demais
limiares, e um valor inválido falha alto na carga.

**Por quê:** consistente com a regra 2 do projeto (regra determinística fora
do LLM, limiares fora do código). Falhar alto em valor inválido segue o
padrão já usado em `_validar_formato` no ETL: erro explícito em vez de
fallback silencioso, porque um fallback silencioso aqui mudaria a postura de
risco sem o usuário perceber.

**Alternativa considerada:** variável de ambiente. Descartada — é parâmetro
de perfil de risco, e o projeto já concentra esses em `params.yaml`.

### 5. Default `bloquear`, decidido explicitamente

Sem data registrada e sem parâmetro, nada é sugerido.

**Por quê:** é o comportamento de hoje, então quem atualizar o código sem
mexer em configuração não vê mudança de postura de risco — só passa a
entender *por que* não há sugestão. A diferença em relação ao estado atual
não é o veredito, é a legibilidade: o relatório passa a dizer o que está
bloqueando e como destravar.

**Trade-off aceito:** o usuário não vê sugestões até cadastrar datas. Foi a
escolha explícita do usuário nesta change, sobre a alternativa `sinalizar`.

### 6. Seção de bloqueios no relatório, não alerta

Os bloqueios viram uma seção própria com os critérios verificados, em vez de
mais uma linha na seção `## Alertas`.

**Por quê:** os alertas atuais são de higiene de dado (cotação velha, ETL não
rodado) e são one-liners. Um bloqueio de resultado carrega o detalhamento de
cinco critérios com seus valores — é conteúdo de decisão, não de higiene, e
misturá-lo diluiria as duas coisas.

## Risks / Trade-offs

- **Data registrada errada leva a uma sugestão que deveria ser bloqueada** →
  A sugestão nunca é ordem: segue `pendente` e sob revisão humana (requisito
  "Nenhuma execução automática", inalterado). O registro guarda origem e
  momento, então uma sugestão suspeita é auditável até a entrada que a
  originou.
- **Data registrada envelhece silenciosamente** (empresa muda a agenda e o
  usuário não atualiza) → Só datas iguais ou posteriores à referência contam;
  uma data vencida faz o ativo voltar a "desconhecida" e reentrar no fluxo de
  bloqueio, em vez de continuar aprovando o critério com um valor obsoleto.
- **Cadastro manual não escala** para uma carteira grande → Aceito nesta
  fase: a carteira é pessoal e as posições já são digitadas manualmente. Se
  virar atrito real, a tabela já é o ponto de integração natural para uma
  fonte automática futura, sem retrabalho na lógica de avaliação.
- **`sinalizar` pode ser ligado e esquecido**, virando sugestão rotineira sem
  verificação → O aviso acompanha a sugestão persistida (não só o relatório
  do dia), então o rastro fica no banco; e o default nunca é `sinalizar`.
- **Mudar `CriterioAvaliado` quebra os testes atuais** → São 44 testes
  passando hoje; a atualização é mecânica e está explicitada em `tasks.md`
  em vez de aparecer como surpresa na implementação.

## Migration Plan

1. Criar `src/db/migrations/` e a primeira migração (`eventos_resultado`).
   Como o projeto nunca teve migração, a migração é aditiva e idempotente
   (`CREATE TABLE IF NOT EXISTS`), aplicável sobre o banco pessoal existente
   sem recriar nada.
2. `schema.sql` recebe a tabela para bancos novos, mas **não é reescrito
   retroativamente** de forma incompatível — regra 4 do projeto.
3. Código e `params.yaml` podem subir juntos: sem o parâmetro, o default
   `bloquear` reproduz o comportamento atual, então não há janela em que o
   sistema fique mais permissivo do que hoje.
4. **Rollback:** reverter o código restaura o comportamento anterior; a
   tabela pode ficar (é aditiva e inofensiva sem o código que a lê).
   Nenhum dado existente é modificado ou removido por esta change.
