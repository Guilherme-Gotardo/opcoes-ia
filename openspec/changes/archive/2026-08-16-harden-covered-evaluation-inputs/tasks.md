## 1. Proteção de `strike`

- [x] 1.1 Adicionar `strike` a `_CAMPOS_MERCADO_OBRIGATORIOS`, com o
      comentário explicando que a ausência dele APROVAVA o critério de
      exposição no covered call.
- [x] 1.2 Guarda explícita de `strike is None` no ramo covered put, antes do
      cálculo da garantia (que roda antes da checagem de obrigatórios).
- [x] 1.3 Reordenar o ramo do put para conferir caixa antes de calcular a
      garantia — o cálculo rodava mesmo no caminho que terminaria em "caixa
      não informado".
- [x] 1.4 Remover `strike or 0.0` do orquestrador: sem strike, notional e
      exposição vão como `None`.

## 2. Constante de contrato

- [x] 2.1 Trocar o `100` da garantia do covered put por `ACOES_POR_CONTRATO`.
- [x] 2.2 Trocar o `100` da checagem de lote do covered call (valor e
      mensagem) pela mesma constante.

## 3. Frescor do dado da opção

- [x] 3.1 Extrair `_horas_positivas` em `market/valuation.py`, reusando a
      validação que já falhava alto para a janela da cotação.
- [x] 3.2 Implementar `frescor_maximo_horas_opcao`, herdando a janela da
      cotação quando `opcao_frescor_maximo_horas` não estiver em params.
- [x] 3.3 Expor `idade_em_horas` público, para cotação e opção não
      divergirem no tratamento de fuso.
- [x] 3.4 `_opcoes_call_candidatas` passa a levar `coletado_em` e
      `idade_horas` — a query já trazia o campo e o descartava.
- [x] 3.5 Pré-requisito estrutural em `avaliar`: idade ausente ou acima da
      janela vira dado insuficiente, nomeando o código e a idade.
- [x] 3.6 Documentar `idade_horas` como chave obrigatória no docstring de
      `avaliar`.

## 4. Visibilidade do viés de prazo

- [x] 4.1 Calcular o prêmio equivalente mensal e incluí-lo no detalhe do
      critério `premio_pct`, sem alterar o limiar.
- [x] 4.2 Critério adicional opcional `premio_pct_ao_mes`, ativo apenas se
      `premio_minimo_pct_ao_mes` estiver configurado.
- [x] 4.3 Documentar o viés e o parâmetro opcional em `params.yaml`, com a
      linha comentada por padrão.

## 5. Visibilidade do denominador parcial

- [x] 5.1 Propagar os tickers sem cotação da execução para a posição.
- [x] 5.2 Acrescentar a ressalva ao detalhe do critério de exposição,
      nomeando os tickers e dizendo que a exposição real é menor ou igual.
- [x] 5.3 Ampliar o `log.warning` para registrar que o efeito atinge todas
      as posições, não só as sem cotação.

## 6. Testes

- [x] 6.1 `strike` nulo em covered put vira dado insuficiente, sem exceção.
- [x] 6.2 Caixa ausente com strike válido reclama do caixa, não do cálculo.
- [x] 6.3 Garantia e lote calculados com `ACOES_POR_CONTRATO`.
- [x] 6.4 `strike` nulo em covered call vira dado insuficiente (antes
      aprovava exposição).
- [x] 6.5 Opção fora da janela e opção sem data de coleta são recusadas.
- [x] 6.6 Janela da opção pode ser mais curta que a da cotação.
- [x] 6.7 Prêmio ao mês aparece no detalhe sem criar critério novo.
- [x] 6.8 Critério mensal só existe configurado, e reprova onde o bruto
      aprova.
- [x] 6.9 Denominador parcial é declarado no detalhe; sem ele, detalhe limpo.
- [x] 6.10 Fixture existente ganha `idade_horas`; suíte completa verde
      (398 testes).
