## 1. Banco: fonte manual de datas de resultado

- [ ] 1.1 Criar o diretório `src/db/migrations/` (primeira migração do
      projeto — hoje não existe) com um `README.md` curto fixando a
      convenção de nomes e a ordem de aplicação, já que esta change
      estabelece o padrão para as próximas.
- [ ] 1.2 Escrever a migração que cria `eventos_resultado` (ticker, data do
      resultado, origem informada, momento do registro), aditiva e
      idempotente (`CREATE TABLE IF NOT EXISTS`), aplicável sobre o banco
      pessoal existente sem recriar nada — ver `design.md`, decisão 1 e
      Migration Plan.
- [ ] 1.3 Adicionar a mesma tabela a `src/db/schema.sql` para bancos novos,
      sem reescrever retroativamente o que já está em produção pessoal
      (regra 4 do projeto).
- [ ] 1.4 Aplicar a migração no banco local e confirmar que as tabelas e os
      dados existentes seguem intactos.

## 2. Gestão das datas de resultado

- [ ] 2.1 Implementar o registro de uma data de resultado informada pelo
      usuário, persistindo origem e momento do registro (spec
      `earnings-calendar`, requisito "Registro manual de data de resultado").
- [ ] 2.2 Implementar validação com erro explícito para entrada inválida,
      sem ajustar ou reinterpretar o valor recebido (requisito "Rejeição de
      registro inválido"), no mesmo estilo de `PosicaoInvalida` em
      `src/portfolio/manage.py`.
- [ ] 2.3 Implementar a consulta "próxima data a partir de uma referência",
      retornando o estado explícito "desconhecida" quando só houver datas
      passadas ou nenhuma (requisito "Consulta da data vigente de um ativo").
- [ ] 2.4 Implementar correção/remoção de uma data registrada preservando a
      rastreabilidade da alteração (requisito "Correção de uma data
      registrada").
- [ ] 2.5 Expor os comandos por CLI seguindo o padrão de
      `python -m src.portfolio.manage` (add / list / remove), para que a
      mensagem de destravamento do relatório possa citar um comando real.
- [ ] 2.6 Testes da capability `earnings-calendar`: registro válido, entrada
      inválida rejeitada, próxima data à frente da referência, só datas
      passadas ⇒ desconhecida, e correção refletida na consulta seguinte.

## 3. Avaliação: três estados e política

- [ ] 3.1 Remover `dias_para_resultado` de `_CAMPOS_MERCADO_OBRIGATORIOS` em
      `src/strategy/covered.py`, de modo que sua ausência deixe de abortar a
      avaliação (`design.md`, decisão 3). Os outros cinco campos continuam
      abortando.
- [ ] 3.2 Estender `CriterioAvaliado` para representar três estados
      (`aprovado` / `reprovado` / `indisponivel`) em vez de um booleano
      (`design.md`, decisão 2), mantendo `criterios_json()` serializando o
      estado de forma legível para o relatório e para a auditoria.
- [ ] 3.3 Carregar e validar `politica_resultado_desconhecido` de
      `params.yaml`, com default `bloquear` quando ausente e erro explícito
      quando o valor for diferente de `bloquear`/`sinalizar` (spec
      `covered-strategy-execution`, requisito "Política configurável...",
      cenários de parâmetro ausente e valor inválido).
- [ ] 3.4 Avaliar o critério de resultado quando houver data registrada,
      contra `dias_bloqueio_antes_resultado`, independentemente da política
      (requisito "Data de resultado conhecida é avaliada normalmente").
- [ ] 3.5 Aplicar a política quando a data for desconhecida: `bloquear` não
      emite sugestão mas registra que o bloqueio foi por critério não
      verificável; `sinalizar` emite a sugestão com a marcação de
      verificação manual persistida junto dela.
- [ ] 3.6 Ajustar o motivo de não-elegibilidade para distinguir critérios
      reprovados de critérios não verificáveis (requisito "Todos os critérios
      precisam passar", cenário do motivo separado).
- [ ] 3.7 Ligar `_opcoes_call_candidatas` à consulta da tarefa 2.3,
      substituindo o `dias_para_resultado = None` fixo pela data real quando
      houver — este é o ponto exato que hoje curto-circuita tudo.
- [ ] 3.8 Atualizar os testes existentes que assumem "campo nulo ⇒ dado
      insuficiente" para `dias_para_resultado` e que leem
      `CriterioAvaliado.aprovado` como booleano (previsto em `design.md`,
      decisão 2 e Risks).
- [ ] 3.9 Testes novos: data desconhecida não impede a avaliação dos demais
      critérios; `bloquear` com demais critérios OK; `sinalizar` com demais
      critérios OK; resultado próximo demais reprova mesmo sob `sinalizar`;
      resultado distante aprova sem marcação.

## 4. Relatório diário

- [ ] 4.1 Coletar, na geração do relatório, as avaliações bloqueadas por data
      de resultado desconhecida (hoje `executar_avaliacao_carteira()` já
      retorna todos os resultados, inclusive não elegíveis — aproveitar esse
      retorno em vez de reavaliar).
- [ ] 4.2 Renderizar a seção de avaliações bloqueadas com os critérios já
      verificados e seus valores, omitindo a seção inteira quando não houver
      bloqueio (spec `daily-portfolio-report`, requisitos de bloqueio
      reportado e cenário "Nenhum bloqueio no dia").
- [ ] 4.3 Incluir na entrada de bloqueio a ação que destrava, citando o
      comando real da tarefa 2.5 (requisito "Bloqueio reportado indica a ação
      para destravar").
- [ ] 4.4 Exibir o aviso de agenda não verificada junto das sugestões geradas
      sob `sinalizar`, somando-se à indicação de revisão humana já existente
      (requisito "Sugestão sinalizada carrega o aviso no relatório").
- [ ] 4.5 Testes do relatório: com bloqueio, sem bloqueio (seção ausente), e
      com sugestão sinalizada exibindo o aviso.

## 5. Documentação e fechamento

- [ ] 5.1 Documentar o critério de resultado e a nova política em
      `skills/covered-options-strategy/SKILL.md`, incluindo o novo parâmetro
      em `params.yaml` com comentário explicando as duas posturas.
- [ ] 5.2 Atualizar a seção "Estado atual" do `CLAUDE.md`: o gap do
      calendário de resultados deixa de curto-circuitar a avaliação; registrar
      que a fonte é manual por ausência de fonte automática viável.
- [ ] 5.3 Atualizar os comandos úteis do `CLAUDE.md` e do `README.md` com o
      CLI de gestão de datas de resultado.
- [ ] 5.4 Rodar a suíte completa (`pytest`) e confirmar verde.
- [ ] 5.5 Validar o fluxo de ponta a ponta contra o banco real: sem data
      registrada ⇒ bloqueio visível no relatório; com data registrada ⇒
      critério avaliado. Como o ETL de opções segue bloqueado por plano, usar
      dados de opções sintéticos marcados com `fonte` distinta de `brapi`,
      para não contaminar a carteira real nem o orçamento de requests.
