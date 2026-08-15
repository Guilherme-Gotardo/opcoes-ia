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

Se o pré-requisito não for atendido, a posição é descartada antes mesmo de
avaliar os critérios de mercado — não gerar sugestão nesse caso.

## Critérios de mercado (todos precisam ser satisfeitos)

| Critério | Regra padrão | Racional |
|---|---|---|
| IV Rank | ≥ 50 | Prêmio mais gordo; vender opção com volatilidade implícita historicamente alta favorece o vendedor |
| Delta do strike | entre 0.20 e 0.35 (em módulo) | Equilíbrio entre prêmio recebido e probabilidade de exercício |
| Dias até o vencimento | entre 20 e 45 dias | Janela que maximiza o decaimento temporal (theta) por operação |
| Prêmio mínimo | ≥ 0.5% do valor da posição coberta | Evita operações com retorno desprezível frente ao risco/custo |
| Exposição máxima por ativo | ≤ 20% do patrimônio em opções | Limite de concentração de risco |
| Evento de resultado próximo | Nenhum resultado trimestral nos próximos 7 dias | Evita vender opção véspera de evento com risco de gap |

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
Prêmio estimado: R$ 0,85 (2,2% da posição)
Critérios atendidos:
  - IV Rank: 61 (mínimo 50) ✅
  - Delta: 0.28 (faixa 0.20–0.35) ✅
  - Dias até vencimento: 32 (faixa 20–45) ✅
  - Prêmio: 2,2% (mínimo 0,5%) ✅
  - Exposição no ativo após operação: 12% (limite 20%) ✅
  - Resultado trimestral: nenhum nos próximos 7 dias ✅
```

## Fases futuras (não implementadas ainda)

- Travas (bull call spread, bear put spread): exigirá critérios de correlação
  entre dois strikes e cálculo de risco/retorno da trava como um todo.
- Condor: exigirá lógica de 4 pernas e gestão de margem mais sofisticada.

Quando essas fases forem iniciadas, criar skills separadas
(`iron-condor-strategy`, `spread-strategy`) em vez de sobrecarregar esta.
