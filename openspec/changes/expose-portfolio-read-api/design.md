## Context

Ver `proposal.md` — Why. O que importa para o desenho:

- **Tudo que a API precisa de `report/daily.py` é privado.** `_resumo_carteira`,
  `_valorizar`, `_preco_opcao`, `_sugestoes_do_dia` — as únicas funções
  públicas são `gerar_relatorio` (que escreve arquivo) e `main`.
- `src/market/valuation.py` já é público e já é a fonte única de "valor a
  mercado", mas devolve patrimônio agregado; a visão por posição (preço médio
  ao lado do preço de mercado, momento da cotação, motivo de não valorização)
  está montada dentro do relatório.
- **O desfecho da avaliação já é persistido** em `desfecho_avaliacao`
  (migração 003), agregado por (execução, ativo, motivo), com contagem por
  critério e amostra. O relatório lê de lá quando não recebe `avaliacoes` por
  argumento — a API lê da mesma fonte.
- `requirements.txt` tem 5 dependências e nenhuma web.
- O frontend está em outro repositório (`opcoes-ia-web`), com seu próprio
  ciclo de build.

## Goals / Non-Goals

**Goals:**

- Dar à interface uma fonte estruturada dos mesmos números que o relatório
  mostra.
- Garantir por construção que API e relatório não possam divergir.
- Publicar um contrato do qual o TypeScript derive tipos.

**Non-Goals:**

- Escrita (ativo, posição, data) — change seguinte.
- Autenticação, sessão, multi-tenancy — decisão registrada de uso local por
  um usuário.
- Disparar ETL, avaliação ou relatório pela API.
- Persistir qualquer coisa nova — o desfecho da avaliação já é gravado pela
  change `persist-evaluation-outcomes`; aqui ele é apenas lido.
- Deploy hospedado.

## Decisions

### 1. A visão de carteira sobe para função de domínio pública

`_resumo_carteira` e `_valorizar` saem de `report/daily.py` para uma função
pública — `src/market/valuation.py` é o lugar natural, já que é onde mora a
regra de "valor a mercado" e a decisão de o patrimônio só somar ações.
`daily.py` passa a consumi-la e mantém apenas a renderização Markdown.

Sem isso, a API reimplementaria a valorização por posição. Duas
implementações da mesma conta é literalmente o bug que a change
`value-portfolio-at-market-price` existiu para corrigir — e ele só foi
descoberto num teste manual de ponta a ponta, meses depois. Repetir o padrão
sabendo disso seria escolher o mesmo erro.

O critério de aceitação da extração é comportamental: os testes atuais de
`report/daily.py` passam sem alteração de expectativa.

*Alternativa considerada:* a API importar as funções privadas de `daily.py`.
Descartada: acopla a API à ordem interna do relatório e sinaliza que a
fronteira está no lugar errado.

### 2. FastAPI, com camada fina e Pydantic só na borda

`src/api/` com os endpoints e os modelos de resposta. Os modelos existem para
o OpenAPI sair descritivo o bastante para gerar TypeScript útil — não para
revalidar regra de domínio. Nenhum cálculo mora aqui: cada endpoint chama a
função de domínio e serializa.

FastAPI porque publica OpenAPI sem trabalho adicional, que é o que sustenta a
decisão 4.

### 3. `localhost` por padrão, CORS restrito à origem do Vite

O servidor sobe ligado a `127.0.0.1`, não a `0.0.0.0`. É a diferença entre
"acessível na minha máquina" e "acessível na rede local" — e, sem
autenticação, a segunda é exposição real.

CORS liberado só para a origem do dev server do Vite, configurável por
variável de ambiente. Um `allow_origins=["*"]` seria inofensivo em
`localhost` hoje e perigoso no dia em que alguém publicasse a API sem
lembrar de revisar.

A ausência de autenticação é decisão registrada, não esquecimento: é
ferramenta de um usuário na própria máquina. Publicá-la exige revisar isso
numa change própria.

### 4. Tipos do TypeScript gerados do OpenAPI

`openapi-typescript` lê o schema que o FastAPI publica e gera um `.d.ts`
versionado no repositório do frontend. Um script npm regenera; o arquivo
gerado entra no versionamento para que o build não dependa da API estar no ar.

O ponto é ter uma fonte só para o contrato: renomear um campo no Python passa
a quebrar o `tsc` do frontend, que é quando você quer descobrir. Tipos
escritos à mão criariam a segunda definição — mesmo padrão de divergência
silenciosa da decisão 1, agora atravessando repositórios, onde é ainda menos
visível.

### 5. Avaliações sem sugestão passaram a ser servíveis

Na redação original desta change, os motivos de não-sugestão não eram
persistidos: só `sugestoes` ia para o banco, e os bloqueios existiam apenas
em memória durante `executar_avaliacao_carteira()`. Servi-los exigiria fazer
a API rodar a avaliação, contrariando a decisão de ela não disparar nada — e
a consequência declarada era uma regressão de informação na interface em
relação ao relatório Markdown.

A change `persist-evaluation-outcomes` resolveu a causa: o desfecho de cada
execução é gravado em `desfecho_avaliacao`, agregado por (execução, ativo,
motivo), com contagem por critério e uma amostra representativa. O relatório
já lê de lá.

A API portanto **expõe** esse registro, lendo da mesma fonte que o relatório
— o que também satisfaz, para esta seção, o requisito de os números
coincidirem entre os dois. Continua valendo que a API não roda a avaliação:
ela lê o desfecho que a execução anterior gravou.

### 6. A API lê o banco diretamente, sem cache

Cada requisição abre conexão e consulta. Para um usuário, numa carteira de
poucas posições, contra Postgres gerenciado, não há problema de desempenho a
resolver — e cache seria uma segunda cópia do estado, com invalidação a
manter.

## Risks / Trade-offs

- **Mover código de `daily.py` pode alterar o relatório sem querer.** →
  Mitigação: a extração é considerada correta apenas se os testes atuais de
  `report/daily.py` passarem sem mudança de expectativa. Se algum precisar
  mudar, é sinal de que a extração alterou comportamento e deve ser revista.

- **Duas dependências novas** (`fastapi`, `uvicorn`) num projeto que hoje tem
  cinco. → O pipeline diário não as importa; o workflow segue instalando o
  mesmo `requirements.txt`, com custo de instalação um pouco maior e nenhum
  custo de execução.

- **A interface mostra o desfecho da última execução, não do instante.** Se
  a avaliação não rodou hoje, o registro mais recente é de outro dia. → A
  resposta precisa carregar o momento da execução, para a interface poder
  dizer de quando é o que está mostrando — mesma disciplina da idade da
  cotação.

- **Dois repositórios podem sair de sincronia.** → É o custo aceito ao
  separar o frontend. O contrato gerado (decisão 4) transforma divergência em
  erro de build em vez de erro em produção, que é a melhor mitigação
  disponível sem juntar os repos.

## Migration Plan

Sem migração de banco. Ordem:

1. Extrair a visão de carteira para função de domínio pública; `daily.py`
   passa a consumi-la; testes do relatório inalterados.
2. `fastapi` e `uvicorn` em `requirements.txt`.
3. `src/api/` com os endpoints de leitura e os modelos de resposta.
4. Testes da API com cliente de teste, sem banco onde possível.
5. Geração dos tipos no `opcoes-ia-web` e verificação de que o `tsc` aceita.
6. Documentação nos dois repositórios.

**Rollback:** `git revert`. A API é aditiva — nada no pipeline diário passa a
depender dela.

## Open Questions

- Paginação das sugestões: hoje o volume é de unidades por dia, então uma
  lista simples basta. Deferível — adicionar paginação depois não muda os
  requisitos desta change.
- Se a interface algum dia precisar disparar uma análise, o caminho previsto
  no roadmap é `workflow_dispatch` pela API do GitHub, não um endpoint que
  executa. Fora de escopo e registrado para não ser reaberto por engano.
