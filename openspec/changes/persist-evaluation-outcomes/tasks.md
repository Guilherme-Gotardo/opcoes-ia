## 1. Schema

- [x] 1.1 Escrever a migração `003` criando a tabela do desfecho de execução,
      com chave (execução, ativo, motivo), contagem de opções afetadas,
      contagem por critério e a amostra representativa. Aditiva e idempotente
      (`CREATE TABLE IF NOT EXISTS`), no padrão do `README.md` de migrações.
- [x] 1.2 Documentar em comentário na coluna de contagem por critério que a
      soma pode exceder o total, porque uma opção reprovada em vários
      critérios é contada em cada um (`design.md`, decisão 3).
- [x] 1.3 Replicar a tabela em `src/db/schema.sql`, para que um banco novo
      saia igual a um migrado (regra 3 do README de migrações).
- [x] 1.4 Aplicar com `python -m src.db.bootstrap` no banco descartável e
      confirmar que a segunda execução não altera nada.

## 2. Classificação do motivo

- [x] 2.1 Implementar a derivação do código de motivo a partir de um
      `ResultadoAvaliacao`, com o conjunto fechado da decisão 2 do
      `design.md` (`sugerida`, `bloqueio_data_resultado`,
      `criterio_reprovado`, `dado_insuficiente`, `pre_requisito`).
- [x] 2.2 Garantir que a ordem de classificação segue a mesma precedência de
      `avaliar()`: reprovação no mérito vence bloqueio por dado faltante, e
      cada resultado cai em exatamente um código.
- [x] 2.3 Implementar a agregação de uma lista de resultados em linhas por
      (ativo, motivo), com contagem, contagem por critério reprovado e
      escolha determinística da amostra representativa.
- [x] 2.4 Testes da classificação e da agregação, sem banco: cada motivo
      isolado; reprovação com vários critérios contando em todos; precedência
      entre reprovação e bloqueio; ativo sem nenhuma opção avaliada;
      determinismo da amostra escolhida.

## 3. Persistência do desfecho

- [x] 3.1 Implementar o repositório que grava as linhas do desfecho, no
      padrão de `src/earnings/repository.py`.
- [x] 3.2 Implementar a consulta do desfecho da execução mais recente de uma
      data, que é o que o relatório e a futura API vão consumir.
- [x] 3.3 Fazer `executar_avaliacao_carteira` gravar o desfecho **na mesma
      transação** que persiste as sugestões, antes do commit (`design.md`,
      decisão 6).
- [x] 3.4 Registrar o desfecho também quando nenhuma sugestão for gerada e
      quando um ativo não tiver nenhuma opção para avaliar (spec, cenários
      "Execução sem nenhuma sugestão" e "Ativo sem nenhuma opção para
      avaliar").
- [x] 3.5 Confirmar que `sugestoes` continua recebendo apenas o que passou —
      nenhuma linha nova com status alternativo (spec
      `covered-strategy-execution`, cenário "Avaliação não-sugerida não polui
      as sugestões").
- [x] 3.6 Testes de integração contra o Postgres (pulados sem banco): duas
      execuções no mesmo dia ficam distinguíveis; o registro sobrevive à
      execução; a consulta devolve a mais recente.

## 4. Relatório lê do banco

- [x] 4.1 Fazer `gerar_relatorio` montar a seção de não-sugestões a partir do
      desfecho persistido quando o argumento `avaliacoes` não for informado,
      mantendo o argumento aceito (`design.md`, decisão 5).
- [x] 4.2 Estender a seção para cobrir todos os motivos, não só bloqueio por
      data de resultado, informando o motivo e quantas opções foram afetadas
      (spec `daily-portfolio-report`, cenário "Reprovação em critério também
      é reportada").
- [x] 4.3 Preservar a orientação de destravamento nos dois passos
      (`manage add` → `ingest`) para o motivo de data de resultado, que já é
      requisito vigente.
- [x] 4.4 Manter a seção ausente quando não houver não-sugestão no dia, sem
      gerar seção vazia.
- [x] 4.5 Testes em `tests/test_report_daily.py`: relatório gerado sem o
      argumento monta a seção a partir do banco; motivos além de earnings
      aparecem; nenhum motivo no dia não gera seção; os testes existentes que
      passam `avaliacoes` continuam válidos.

## 5. Documentação

- [x] 5.1 `CLAUDE.md`: registrar a tabela nova e que o motivo de
      não-sugestão passou a ser persistido e comparável entre execuções.
- [x] 5.2 `docs/ARQUITETURA.md`: registrar o desfecho de execução como fonte
      para relatório e interface.
- [x] 5.3 Remover da change `expose-portfolio-read-api` (arquivada ou não) a
      limitação declarada de não poder servir avaliações bloqueadas —
      atualizando o artefato correspondente ou registrando em `CLAUDE.md` que
      ela deixou de valer, conforme o estado daquela change no momento.

## 6. Validação de ponta a ponta

- [x] 6.1 Rodar `pytest` completo apontando para o banco descartável.
- [x] 6.2 Aplicar a migração no Neon com `python -m src.db.bootstrap`.
- [x] 6.3 Com opção sintética (`fonte='sintetico'`, como nas changes
      anteriores), exercitar os motivos: sem data de resultado registrada
      (bloqueio) e com IV rank abaixo do mínimo (reprovação), confirmando que
      cada um vira registro com a contagem certa.
- [x] 6.4 Gerar o relatório **sem** passar `avaliacoes` e confirmar que a
      seção de não-sugestões aparece igual — a prova de que o relatório
      deixou de depender da execução.
- [x] 6.5 Limpar do banco os dados sintéticos usados na validação.
