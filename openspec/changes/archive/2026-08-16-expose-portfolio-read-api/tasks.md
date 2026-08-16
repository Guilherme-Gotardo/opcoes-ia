> A tarefa 5 acontece no repositório `opcoes-ia-web`
> (`/home/guilhermeg/Área de trabalho/projetos/opcoes-ia-web`), não neste.

## 1. Extrair a visão de carteira para o domínio

- [x] 1.1 Mover a valorização por posição (`_valorizar`, `_preco_opcao`) e a
      montagem do resumo (`_resumo_carteira`) de `src/report/daily.py` para
      uma função pública em `src/market/valuation.py` (`design.md`,
      decisão 1).
- [x] 1.2 Devolver a visão como estrutura tipada (dataclass), não dict solto,
      já que agora ela atravessa duas camadas — relatório e API.
- [x] 1.3 Fazer `src/report/daily.py` consumir a função extraída, mantendo
      apenas a renderização Markdown.
- [x] 1.4 Confirmar que `tests/test_report_daily.py` passa **sem alteração de
      expectativa**. Qualquer teste que precise mudar é sinal de que a
      extração alterou comportamento e deve ser revista (`design.md`, riscos).
- [x] 1.5 Testes da função extraída em `tests/test_market_valuation.py`:
      carteira completa, posição sem cotação, patrimônio parcial, opção
      valorizada mas fora do patrimônio.

## 2. Dependências e esqueleto da API

- [x] 2.1 Adicionar `fastapi` e `uvicorn` a `requirements.txt`, com
      comentário de que servem só à interface e não ao pipeline diário.
- [x] 2.2 Criar `src/api/__init__.py` e `src/api/app.py` com a aplicação
      FastAPI e `python -m src.api` subindo o servidor ligado a `127.0.0.1`
      — nunca `0.0.0.0` (`design.md`, decisão 3).
- [x] 2.3 Configurar CORS liberando apenas a origem do dev server do Vite,
      lida de variável de ambiente com padrão local. Não usar `*`.
- [x] 2.4 Registrar no módulo, em docstring, os três limites desta
      superfície: não decide, não dispara, não escreve.

## 3. Endpoints de leitura

- [x] 3.1 Modelos de resposta (Pydantic) para carteira, cotação e sugestão,
      existindo para o OpenAPI sair descritivo — não para revalidar regra de
      domínio (`design.md`, decisão 2).
- [x] 3.2 Endpoint de carteira, servindo posições com preço médio e preço de
      mercado, patrimônio total, exposição por ativo, e a marcação de
      patrimônio parcial com os tickers sem cotação (spec, requisito "Leitura
      da carteira valorizada a mercado").
- [x] 3.3 Endpoint de cotações vigentes, com preço e momento da coleta, e
      representando explicitamente o ativo sem cotação (spec, requisito
      "Leitura das cotações vigentes").
- [x] 3.4 Endpoint de sugestões, com strike, vencimento, prêmio, status e o
      snapshot de critérios, incluindo a base de valorização (spec, requisito
      "Leitura das sugestões registradas").
- [x] 3.5 Garantir que toda sugestão exposta carrega a indicação de pendente
      de revisão humana, e que nenhum texto da API sugere ordem executada
      (spec, cenário "Nenhuma sugestão aparece como executada").
- [x] 3.5b Endpoint do desfecho da avaliação, servindo por ativo os motivos
      de não-sugestão, a contagem por motivo e por critério, a amostra e o
      momento da execução (spec, requisito "Leitura dos motivos de
      não-sugestão"). Lê `desfecho_avaliacao` pela mesma função que o
      relatório usa — a API não roda a avaliação.
- [x] 3.6 Carteira vazia e ausência de sugestões respondem com sucesso
      representando o vazio, nunca com erro.
- [x] 3.7 Testes com `TestClient`: desfecho com motivos e sem execução
      registrada, carteira completa, carteira parcial,
      carteira vazia, cotações, sugestões com critérios, ausência de
      sugestões, e a checagem de que nenhum endpoint escreve no banco.
- [x] 3.8 Teste de que os números da API coincidem com os do relatório para o
      mesmo estado — a prova de que vieram da mesma função de domínio (spec,
      cenário "Valores coincidem com os do relatório").

## 4. Contrato OpenAPI

- [x] 4.1 Conferir que o schema publicado cobre os três endpoints e que os
      campos saem com nome e tipo úteis para geração de cliente (spec,
      requisito "Contrato publicado em formato consumível por cliente
      tipado").
- [x] 4.2 Adicionar um comando para salvar o schema em arquivo, para que a
      geração de tipos não dependa da API estar no ar.

## 5. Tipos no `opcoes-ia-web`

- [x] 5.1 Adicionar `openapi-typescript` como dependência de
      desenvolvimento e um script npm de geração.
- [x] 5.2 Gerar os tipos a partir do schema e versionar o arquivo gerado, com
      comentário de que é gerado e não deve ser editado à mão.
- [x] 5.3 Escrever um cliente mínimo tipado que consuma o endpoint de
      carteira, provando o contrato de ponta a ponta.
- [x] 5.4 Confirmar que `npm run build` (que roda `tsc -b`) aceita o
      resultado.

## 6. Documentação

- [x] 6.1 `CLAUDE.md`: como subir a API, onde ela mora, e os três limites
      (não decide, não dispara, não escreve).
- [x] 6.2 `CLAUDE.md`: registrar que a interface mostra o desfecho da
      ÚLTIMA execução, não do instante — se a avaliação não rodou hoje, o
      que aparece é de outro dia, e a data precisa estar visível.
- [x] 6.3 `docs/ARQUITETURA.md`: a Fase 4 deixa de ser apenas relatório
      estático; registrar a separação em dois repositórios e por quê.
- [x] 6.4 `README.md` do `opcoes-ia-web`: substituir o placeholder do comando
      da API pelo comando real e documentar a geração de tipos.

## 7. Validação de ponta a ponta

- [x] 7.1 Rodar `pytest` completo apontando para o banco descartável.
- [x] 7.2 Com a API no ar contra o Neon, conferir que o endpoint de carteira
      devolve o mesmo patrimônio que o relatório gerado no mesmo momento.
- [x] 7.3 Subir o dev server do Vite e confirmar que o cliente tipado busca a
      carteira sem erro de CORS.
- [x] 7.4 Confirmar que a API responde apenas em `127.0.0.1` — uma requisição
      ao IP da máquina na rede local deve ser recusada.
