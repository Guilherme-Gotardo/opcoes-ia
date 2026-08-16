## Why

A avaliação de estratégia sabe exatamente por que não sugeriu nada — e joga
essa informação fora. `executar_avaliacao_carteira()` devolve um
`ResultadoAvaliacao` por par posição×opção, com o veredito de cada critério,
mas **só as elegíveis são persistidas**. Todo o resto — bloqueio por data de
resultado, reprovação por IV rank, delta, prêmio, exposição, dado
insuficiente — vive em memória durante a execução e morre quando o processo
termina.

Hoje isso é contornado por um argumento: `gerar_relatorio(avaliacoes=...)`
recebe os resultados na mesma execução e renderiza a seção de bloqueios. Só
funciona porque relatório e avaliação rodam no mesmo processo. Qualquer outro
consumidor fica sem nada:

- A **API de leitura** planejada (`expose-portfolio-read-api`) não tem o que
  servir. A interface mostraria "nenhuma sugestão" sem poder explicar o
  porquê — o silêncio que a change `unblock-earnings-calendar-criterion`
  combateu no relatório voltaria pela UI.
- **Nada é comparável ao longo do tempo.** "Faz três semanas que PETR4 é
  reprovada por IV rank" é a informação que diz se vale esperar ou revisar o
  parâmetro, e ela não existe.

Distinguir "nada valia a pena" de "faltou um dado" exige ações opostas do
usuário. É a mesma distinção que motivou os três estados do critério de
resultado — só que agora ela precisa sobreviver ao fim do processo.

## What Changes

- **Nova tabela de registro do desfecho de cada execução da avaliação**,
  gravada por `executar_avaliacao_carteira()` junto com as sugestões.
- **Granularidade agregada por (execução, ticker, motivo)**, não uma linha por
  opção. O bloqueio por data de resultado é por ticker: com uma cadeia real
  de 100+ séries, uma linha por opção gravaria centenas de registros para
  expressar um fato só — "falta a data da PETR4". Cada linha guarda quantas
  opções caíram naquele motivo e a melhor candidata como amostra.
- **Cobre toda não-elegibilidade**, não só earnings: reprovação em critério
  (com a contagem por critério), dado insuficiente e pré-requisito estrutural
  entram no mesmo registro.
- **O relatório passa a ler do banco** em vez de depender do argumento
  `avaliacoes`, para que relatório e API vejam exatamente a mesma coisa. O
  argumento continua aceito para não quebrar quem já chama assim.
- **`sugestoes` não muda.** Continua sendo apenas o que passou, com status
  `pendente` — poluí-la com um status "bloqueada" conflitaria com o requisito
  de que toda sugestão persistida permaneça pendente, e uma avaliação
  bloqueada não é uma sugestão.
- **Nenhuma regra de decisão muda.** Isto é registro do que a avaliação já
  concluiu; nenhum critério, limiar ou política é tocado.

## Capabilities

### New Capabilities

- `evaluation-outcome-log`: registro persistido e comparável ao longo do
  tempo do desfecho de cada execução da avaliação de estratégia, incluindo os
  motivos de não-sugestão.

### Modified Capabilities

- `covered-strategy-execution`: a execução da avaliação passa a persistir seu
  desfecho completo, não apenas as sugestões geradas.
- `daily-portfolio-report`: a seção de avaliações não-sugeridas passa a ser
  montada a partir do registro persistido e a cobrir todos os motivos, não só
  data de resultado desconhecida.

## Impact

- **Código:** `src/strategy/covered.py` (persistir o desfecho ao final da
  execução); `src/report/daily.py` (ler do banco); provável módulo novo para
  o repositório desse registro.
- **Banco:** migração `003`, aditiva e idempotente, mais a tabela em
  `schema.sql` (regras 3 e 4 do `README.md` de migrações).
- **Consumidores:** destrava a limitação declarada na change
  `expose-portfolio-read-api`, que hoje registra explicitamente não poder
  servir avaliações bloqueadas.
- **Documentação:** `CLAUDE.md` (a limitação registrada deixa de valer),
  `docs/ARQUITETURA.md`.
- **Fora de escopo:** política de retenção/expurgo — o volume agregado é de
  poucas linhas por dia útil por ativo, e decidir descarte antes de ter
  histórico seria otimizar sem dado. Também fora: endpoint da API para esse
  registro, que pertence à change da API.
