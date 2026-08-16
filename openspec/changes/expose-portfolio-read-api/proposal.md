## Why

Todo dado da carteira só existe hoje em dois lugares: linha de comando e um
arquivo Markdown por dia. Para a interface web (`opcoes-ia-web`, React+TS)
mostrar carteira, cotações e sugestões, precisa existir uma superfície HTTP —
não há nenhuma.

O relatório diário resolve o caso "olhar o dia", mas não serve de fonte para
uma UI: é texto formatado para leitura humana, um arquivo por dia, e a única
função pública que o produz (`gerar_relatorio`) **escreve arquivo** em vez de
devolver dado. Fazer a interface consumir Markdown seria parsear a
apresentação para recuperar a informação que a camada de baixo já tinha
estruturada.

Há um agravante que esta change precisa resolver junto: **tudo que a
interface quer de `report/daily.py` é privado** — `_resumo_carteira`,
`_valorizar`, `_sugestoes_do_dia`. Uma API que reimplementasse a valorização
da carteira criaria uma segunda implementação da mesma conta, que é
exatamente o formato do bug corrigido na change
`value-portfolio-at-market-price`: relatório e motor de estratégia tinham
cada um a sua noção de "valor da carteira", e as duas divergiram do mercado
ao mesmo tempo sem ninguém notar.

## What Changes

- **Nova superfície HTTP de leitura** com FastAPI, no repositório principal,
  servindo carteira valorizada a mercado, cotações vigentes e sugestões
  registradas.
- **A visão de carteira vira função de domínio pública**, extraída de
  `report/daily.py` e consumida tanto pelo relatório quanto pela API. Nenhuma
  regra muda de comportamento — o que muda é onde ela mora, para não haver
  duas.
- **Contrato TypeScript gerado do OpenAPI** que o FastAPI publica, com
  `openapi-typescript`, versionado no repositório do frontend. O contrato
  passa a ter uma fonte só: mudar um campo no Python quebra o build do front.
- **Servidor só em `localhost`**, sem autenticação. É uso de um usuário na
  própria máquina; o que protege os dados é não haver porta aberta para a
  internet. CORS liberado apenas para a origem do dev server do Vite.
- **A API não dispara nada.** Não roda ETL, não avalia estratégia, não gera
  relatório. Só lê o que já está no banco — quem escreve continua sendo o
  workflow diário e as CLIs.
- **Nenhuma lógica de decisão na API.** Todo critério continua determinístico
  em `src/strategy/`; a API transporta resultado e justificativa numérica.

## Capabilities

### New Capabilities

- `portfolio-read-api`: superfície HTTP de leitura sobre a carteira, as
  cotações e as sugestões, para consumo por interface própria.

### Modified Capabilities

Nenhuma. A extração da visão de carteira para função pública é reorganização
interna — `daily-portfolio-report` continua com exatamente o mesmo contrato
de comportamento, e é isso que os testes existentes do relatório devem
provar.

## Impact

- **Código:** novo `src/api/`; extração da visão de carteira de
  `src/report/daily.py` para uma função de domínio pública, com `daily.py`
  passando a consumi-la.
- **Dependências:** `fastapi` e `uvicorn` entram em `requirements.txt`.
  Nenhuma delas é usada pelo pipeline diário, que continua rodando sem servir
  HTTP.
- **Banco:** nenhuma migração. A API só lê.
- **Repositório `opcoes-ia-web`:** script de geração de tipos e o arquivo
  gerado; o README de lá já aponta para esta change.
- **Documentação:** `CLAUDE.md` (como subir a API e onde ela mora),
  `docs/ARQUITETURA.md` (a Fase 4 deixa de ser só relatório estático).
- **Fora de escopo — escrita.** Cadastro de ativo, posição e data de
  resultado vêm na change seguinte; aqui a API é somente leitura.
- **Avaliações sem sugestão — limitação removida.** Esta change declarava,
  na sua redação original, que não teria como servir os motivos de
  não-sugestão, porque eles não eram persistidos. A change
  `persist-evaluation-outcomes` resolveu isso: o desfecho de cada execução
  passou a ser gravado em `desfecho_avaliacao`, agregado por (execução,
  ativo, motivo). A API **deve** expor esse registro — sem ele a interface
  mostraria "nenhuma sugestão" sem poder explicar o porquê, que é justamente
  o silêncio que o relatório Markdown resolve.
