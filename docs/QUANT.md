# Enriquecimento quantitativo

Contexto numérico por opção avaliada: gregas de modelo, preço teórico,
probabilidade de exercício, percentil de IV e skew contra a cadeia.

## A fronteira, antes de qualquer outra coisa

| | `criterios_json` (gate) | `enriquecimento_quant` (contexto) |
|---|---|---|
| Responde | aprovou ou reprovou, e por quê | quão perto estava, e sob que premissas |
| Mora em | `sugestoes` | tabela própria |
| Sai para | só as elegíveis | **toda** opção avaliada |
| Muda a postura de risco | sim | não |
| Configurado por | `skills/covered-options-strategy/params.yaml` | `src/quant/modelo.yaml` |

**Nada daqui volta para o gate.** `strategy/covered.py` não importa
`src.quant` no topo do módulo — o import é adiado, depois do commit da
decisão, e há um teste que falha se alguém subir esse import
(`test_motor_de_decisao_nao_depende_do_modelo_quantitativo`). Sem isso, um
`modelo.yaml` quebrado ou uma QuantLib ausente derrubariam a avaliação, e o
enriquecimento deixaria de ser opcional sem ninguém decidir isso.

Se um dia `prob_exercicio_vencimento` virar critério de verdade, ele entra em
`_CAMPOS_MERCADO_OBRIGATORIOS` e em `params.yaml` seguindo o padrão de três
estados que já existe — não por esta porta.

## Estilo de exercício: por contrato, não global

O plano de automação assumia "opções B3 são de estilo americano" para
justificar a árvore binomial. Isso vale para as **calls**; a convenção nas
**puts** sobre ações da B3 é europeia.

A diferença não é acadêmica. Apreçando uma put europeia como americana:

| moneyness | europeia | americana | viés |
|---:|---:|---:|---:|
| 0.85 | 0,0955 | 0,0977 | +2,2% |
| 1.00 | 1,4572 | 1,5191 | +4,3% |
| 1.10 | 3,9246 | 4,1829 | +6,6% |
| 1.20 | 7,3371 | 8,0000 | +9,0% |

(spot 40, 45 dias, vol 32%, Selic 13,9%.)

O excedente é o valor de exercício antecipado — que numa put europeia
simplesmente não existe. Como venda de put coberta é uma das duas
estratégias do projeto, o viés cairia exatamente onde mais importa.

O estilo fica em `src/quant/modelo.yaml`, por tipo de contrato, e o estilo
**usado** é gravado em cada linha: corrigir a premissa depois não reescreve
a história. **Confira com sua corretora antes de confiar** — é premissa que
pode variar por série e por emissor.

Efeito colateral registrado: com dividend yield zero (não há fonte de
proventos coletada), o valor de exercício antecipado de uma call americana é
nulo por construção, e o preço teórico coincide com o europeu. Sai como
ressalva em toda linha de call, para "americana" não sugerir que algo foi
considerado quando não foi.

## Taxa livre de risco

Vem do **BCB/SGS série 1178** (Selic anualizada base 252) — API pública, sem
chave. Não é parâmetro em arquivo de propósito: um número chumbado é
exatamente o que a regra 1 do projeto proíbe, e a Fase 5 do plano já listava
"taxa desatualizada nos parâmetros do CRR" como risco de deriva.

```bash
python -m src.quant.taxa   # imprime a taxa vigente e sua idade
```

Se o BCB não responder, o pipeline reusa a última taxa gravada em
`enriquecimento_quant`, com a idade declarada numa ressalva. Não é cache
escondido: a taxa usada fica em cada linha, então "de quando era a taxa" é
sempre respondível. Acima de 7 dias sai ressalva — a Selic só muda em
reunião do Copom, e uma taxa de semanas atrás pode ter atravessado uma.

Não usamos a série 432 (Meta Selic): ela carrega a data de **vigência** da
meta, que pode ser futura, e um `observada_em` no futuro tornaria a auditoria
da idade sem sentido.

## Unidades (a fonte de erro mais provável)

| Campo | Unidade | Observação |
|---|---|---|
| `volatilidade_usada`, `taxa_livre_risco` | fração a.a. | 0,32 = 32% |
| `theta_dia` | por **dia corrido** | a QuantLib devolve por ano; divide-se por 365 uma vez só |
| `vega_pp`, `rho_pp` | por **ponto percentual** | diferença finita central — a engine binomial não fornece vega nem rho |
| `prob_exercicio_vencimento` | 0 a 1 | risco-neutra, **só no vencimento** |
| `skew_vs_cadeia` | pontos de fração | 0,03 = 3 p.p. acima da média da cadeia |

`delta_modelo` não se chama `delta`: `opcoes.delta` vem do provedor e é o que
o critério de gate consome. Nomes iguais convidariam a trocar um pelo outro
numa consulta, e a troca só apareceria como sugestão estranha meses depois.

## Validação

A árvore é cobrada contra **referência analítica**, não contra o número que
saiu na primeira vez:

- CRR europeia converge para Black-Scholes (erro ~5e-4 com 1024 passos)
- call americana com q=0 vale exatamente o mesmo que a europeia
- P(call ITM) + P(put ITM) = 1
- P(ITM) < delta na call (N(d2) < N(d1))
- delta cai monotonicamente conforme o strike sobe
- vega bate com a diferença finita explícita de 1 p.p.

## O que ainda não está coberto

- **`prob_exercicio_vencimento` não inclui exercício antecipado.** Mede a
  probabilidade risco-neutra de terminar dentro do dinheiro no vencimento.
  Para quem vende call coberta, "vou ser exercido?" num contrato americano é
  uma pergunta maior que essa. Sai como ressalva em toda linha americana.
- **Dividend yield é zero**, porque não há fonte de proventos coletada.
  Subestima levemente o exercício antecipado de calls americanas.
- **Nada disso aparece na tela ainda.** Está no banco e na API só via
  consulta direta. Enquanto `opcoes` estiver vazia (403 do plano Free), não
  haveria o que mostrar de qualquer forma.
- **O percentil de IV é do ATIVO, não da série.** "IV alta para este papel" é
  a leitura pretendida; "IV alta para esta opção específica" exigiria
  histórico por código, que a coleta ainda não separa.
