## Why

Uma revisão do `strategy/covered.py` encontrou cinco pontos onde a avaliação
não honrava a própria garantia central do desenho: **campo ausente vira
"dado insuficiente", nunca um valor assumido e nunca uma exceção.**

Três eram defeitos de verdade, não estilo:

1. **`strike` era usado sem proteção.** No ramo covered put,
   `opcao["strike"] * 100` rodava ANTES da checagem de campos obrigatórios —
   e `strike` nem estava nessa lista. Com `strike` nulo (que o próprio ETL
   grava quando o provedor não devolve, e que `_opcoes_call_candidatas` já
   previa com `float(strike) if strike is not None else None`), a avaliação
   estourava `TypeError` em vez de registrar dado insuficiente. Uma execução
   inteira caía por causa de uma linha incompleta no banco.

2. **A mesma ausência APROVAVA um critério no covered call.** O orquestrador
   fazia `strike=opcao["strike"] or 0.0` ao calcular o notional. Strike nulo
   virava notional zero, que virava exposição zero, que **passava** no
   critério de exposição. O dado que faltava não bloqueava a sugestão: ele a
   liberava.

3. **A janela de frescor valia só para a cotação da ação.** `DISTINCT ON
   (codigo) ... ORDER BY coletado_em DESC` traz a linha mais RECENTE, o que
   não é o mesmo que recente. Delta e IV rank coletados dias atrás entravam
   nos critérios como se fossem de agora, enquanto o preço da ação era
   rigorosamente barrado por `cotacao_frescor_maximo_horas`. A assimetria não
   tinha razão de ser — e é pior do lado da opção, que envelhece mesmo sem
   negócio novo, só pela passagem do tempo até o vencimento.

Os outros dois eram lacunas de VISIBILIDADE, não de correção. O número
estava certo; o que faltava era o leitor conseguir saber sob que condições
ele foi produzido:

4. **`premio_pct` não desconta o prazo.** Uma opção de 45 dias e uma de 10
   disputam o mesmo `premio_minimo_pct`, e o prêmio cresce com o tempo — o
   que favorece estruturalmente os vencimentos mais longos da faixa
   permitida. Pode ser a escolha desejada; o problema é ela ser invisível.

5. **Patrimônio parcial só virava `log.warning`.** O denominador do critério
   de exposição é um só para a carteira inteira: quando um ticker fica sem
   cotação, a exposição de TODAS as posições é superestimada, não só a dele.
   O efeito é conservador — mas conservador em silêncio ainda é bloqueio sem
   explicação, e quem lê o desfecho não tinha como saber.

## What Changes

- **`strike` entra em `_CAMPOS_MERCADO_OBRIGATORIOS`**, e o ramo covered put
  ganha guarda própria antes do cálculo da garantia, porque ele roda antes
  daquela checagem.
- **Fim do `or 0.0`**: sem strike não se calcula notional, e a exposição vai
  como `None` para a checagem de obrigatórios em vez de virar zero.
- **`ACOES_POR_CONTRATO` no lugar dos `100` soltos**, na garantia do covered
  put e na checagem de lote do covered call.
- **Janela de frescor para o dado da opção**, com chave própria
  (`opcao_frescor_maximo_horas`) que herda a da cotação quando omitida.
- **Prêmio ao mês exposto no detalhe do critério**, sem alterar o limiar; e
  um critério ADICIONAL opcional (`premio_minimo_pct_ao_mes`) para quem
  quiser barrar por rendimento normalizado.
- **Ressalva de denominador parcial no detalhe do critério de exposição**,
  nomeando os tickers sem cotação.

## Non-goals

- **Não muda a postura de risco por omissão.** O limiar de prêmio segue
  sobre o valor bruto e a janela da opção segue igual à da cotação enquanto
  ninguém configurar o contrário. Mudar quais sugestões saem é decisão do
  usuário, não efeito colateral de uma correção.
- **Não implementa covered put de ponta a ponta.** O gap de caixa/garantia
  registrado no MVP continua aberto; aqui só se corrigiu o caminho de dado
  ausente que já existia na função pura.
