---
name: covered-options-strategy
description: Regras determinísticas para avaliar e sugerir operações de venda coberta (covered call/put) na carteira. Use sempre que precisar decidir SE uma posição é elegível para uma operação de venda coberta, ou explicar POR QUE uma sugestão foi ou não gerada. Contém os critérios de delta, IV rank, dias até vencimento, prêmio mínimo e teto de exposição. Não cobre travas nem condor (fases futuras).
---

# Estratégia: Venda Coberta (Covered Call / Covered Put)

Esta skill define os critérios objetivos para considerar uma operação de venda
coberta elegível. O objetivo é ter uma régua consistente — os parâmetros abaixo
são o ponto de partida e devem ser ajustados pelo usuário conforme o perfil de
risco desejado (editar as constantes em `params.yaml`, não hardcode no código).

## Pré-requisito de elegibilidade

- **Covered call**: a posição precisa ter o lote de 100 ações (ou múltiplo)
  do ativo-objeto já em carteira, sem estar comprometido em outra operação.
- **Covered put**: precisa haver caixa/garantia suficiente reservada para
  honrar o exercício ao strike, caso seja exercida.

- **Preço de mercado disponível**: precisa haver cotação do ativo dentro da
  janela de `cotacao_frescor_maximo_horas` (padrão 72h, o bastante para
  cobrir sexta → segunda sem pregão). Sem ela não há como calcular prêmio
  mínimo nem exposição.

- **Dado da opção fresco**: preço, delta e IV rank da opção também precisam
  estar dentro de uma janela (`opcao_frescor_maximo_horas`, que herda a da
  cotação quando não configurada). "Mais recente" não é o mesmo que
  "recente": a consulta traz a última linha coletada, e ela pode ser de dias
  atrás. Opção sem data de coleta é dado insuficiente — não saber a idade não
  autoriza o uso.

- **Strike registrado**: sem strike não há garantia a calcular no covered put
  nem notional descoberto no covered call. Ausente, a avaliação para como
  dado insuficiente; nunca é substituído por zero.

Se o pré-requisito não for atendido, a posição é descartada antes mesmo de
avaliar os critérios de mercado — não gerar sugestão nesse caso.

## Todo valor é a preço de mercado

O valor de uma posição vem sempre da última cotação coletada, nunca do preço
médio de entrada. `preco_medio` é base de custo e não entra em critério
nenhum. Quando não houver cotação dentro da janela de frescor, a resposta é
"dado insuficiente" com o ticker e a idade do dado — **nunca** valorizar pelo
custo: isso seria estimar um valor de mercado, o que a regra 1 do projeto
proíbe.

## Critérios de mercado (todos precisam ser satisfeitos)

| Critério | Regra padrão | Racional |
|---|---|---|
| IV Rank | ≥ 50 | Prêmio mais gordo; vender opção com volatilidade implícita historicamente alta favorece o vendedor |
| Delta do strike | entre 0.20 e 0.35 (em módulo) | Equilíbrio entre prêmio recebido e probabilidade de exercício |
| Dias até o vencimento | entre 20 e 45 dias | Janela que maximiza o decaimento temporal (theta) por operação |
| Prêmio mínimo | ≥ 0.5% do valor da posição coberta **a mercado** | Evita operações com retorno desprezível frente ao risco/custo |
| Prêmio mínimo ao mês (opcional) | desligado por padrão (`premio_minimo_pct_ao_mes`) | Normaliza o prêmio pelo prazo; ver o viés abaixo |
| Exposição máxima por ativo | ≤ 20% do patrimônio a mercado em opção **descoberta** | Limite de risco assumido sem cobertura |
| Evento de resultado próximo | Nenhum resultado trimestral nos próximos 7 dias | Evita vender opção véspera de evento com risco de gap |

### O limiar de prêmio não desconta o prazo

`premio_minimo_pct` compara o percentual BRUTO. Uma opção de 45 dias e uma
de 10 — ambas dentro da faixa permitida — disputam o mesmo mínimo, e o
prêmio tende a crescer com o tempo: na prática isso favorece os vencimentos
mais longos da faixa.

Isso é escolha registrada, não descuido. Para o viés não ficar invisível, o
detalhe do critério mostra o equivalente mensal ao lado do valor bruto. Quem
quiser barrar por rendimento normalizado configura
`premio_minimo_pct_ao_mes`, que entra como critério ADICIONAL — não
substitui o bruto.

### Exposição sobre patrimônio incompleto

O denominador do critério de exposição é o patrimônio a mercado da carteira
inteira — um só para todas as posições. Quando algum ticker fica sem cotação
utilizável, esse denominador é subestimado e a exposição de **todas** as
posições aparece maior do que é, não só a do ticker sem cotação.

O efeito é conservador (bloqueia mais, nunca menos), mas conservador em
silêncio é bloqueio sem explicação. Por isso o detalhe do critério declara
que o denominador está parcial e nomeia os tickers que faltaram.

### O que "exposição máxima por ativo" limita — e o que não limita

O critério mede opção **descoberta** por ativo, não concentração da carteira.
A exposição que uma operação adiciona é o notional da opção menos a cobertura
já presente na carteira (ações do ativo-objeto para covered call, caixa para
covered put), com piso em zero — então uma covered call totalmente coberta
adiciona **zero**.

Contar o notional cheio seria contagem dupla: as ações que cobrem a operação
já estão na carteira, e a call vendida contra elas não adiciona risco
direcional novo. Enquanto essa contagem existiu, nenhuma covered call de um
ativo cujo strike fosse alto em relação ao patrimônio podia passar.

**Consequência a ter em mente:** este critério não é um freio de
concentração. Se metade do patrimônio estiver num único ativo, quem mostra
isso é a seção "Exposição por ativo-objeto" do relatório diário — a
concentração é reportada para decisão humana, não barrada por critério.

## O que fazer quando um critério falha

Nunca "arredondar" um critério para forçar uma sugestão. Se 4 de 5 critérios
passarem, a resposta correta é **não sugerir a operação** e explicar qual
critério não foi atendido e por quanto (ex.: "IV rank em 42, abaixo do mínimo
de 50 — aguardar").

## Formato de output esperado de quem consome esta skill

```
Ativo: PETR4
Operação: Covered Call
Strike sugerido: R$ 38,50
Vencimento: 21/09/2026 (32 dias)
Prêmio estimado: R$ 0,85 (2,0% da posição a mercado)
Base de valorização: R$ 42,00 (cotação de 2026-08-15)
Critérios atendidos:
  - IV Rank: 61 (mínimo 50) ✅
  - Delta: 0.28 (faixa 0.20–0.35) ✅
  - Dias até vencimento: 32 (faixa 20–45) ✅
  - Prêmio: 2,0% (mínimo 0,5%, sobre preço de mercado 42.0) ✅
  - Exposição descoberta no ativo após operação: 0% (limite 20%) ✅
  - Resultado trimestral: nenhum nos próximos 7 dias ✅
```

## Fases futuras (não implementadas ainda)

- Travas (bull call spread, bear put spread): exigirá critérios de correlação
  entre dois strikes e cálculo de risco/retorno da trava como um todo.
- Condor: exigirá lógica de 4 pernas e gestão de margem mais sofisticada.

Quando essas fases forem iniciadas, criar skills separadas
(`iron-condor-strategy`, `spread-strategy`) em vez de sobrecarregar esta.
