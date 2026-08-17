# scheduled-pipeline-operations Specification

## Purpose

Executar os fluxos de mercado e de relatório nos horários definidos, com ordem,
concorrência, recuperação e resultados operacionais verificáveis.

## Requirements

### Requirement: Execução intradiária respeita o pregão
O sistema SHALL disparar o fluxo intradiário na cadência configurada para dias
úteis e SHALL confirmar no calendário da B3 que o instante pertence ao pregão
antes de coletar cotação ou avaliar estratégias. Disparos intradiários perdidos
SHALL NOT ser recuperados fora da janela de pregão.

#### Scenario: Disparo durante pregão válido
- **WHEN** o agendador dispara dentro da sessão de um dia coberto pelo
  calendário da B3
- **THEN** o fluxo registra a execução, coleta cotações e executa a avaliação
  nessa ordem

#### Scenario: Disparo fora da sessão
- **WHEN** o agendador dispara fora da sessão da B3
- **THEN** o fluxo registra que foi pulado e não coleta nem avalia

#### Scenario: Calendário fora da vigência
- **WHEN** o fluxo consulta uma data que o calendário não cobre
- **THEN** a execução falha explicitamente e não presume que há ou não pregão

#### Scenario: Disparo intradiário perdido
- **WHEN** a plataforma fica indisponível durante um horário intradiário e
  retorna depois do encerramento
- **THEN** o disparo perdido não executa sobre cotação velha fora do pregão

### Requirement: Fluxo diário tem ordem determinística
O sistema SHALL executar o fluxo diário na ordem coleta de mercado, consolidação
de earnings, avaliação determinística, enriquecimento quantitativo, composição
do relatório do agente e notificação determinística. Uma etapa SHALL receber
somente saídas persistidas ou resultados explícitos das etapas anteriores.

#### Scenario: Rodada diária completa
- **WHEN** todas as etapas terminam com sucesso
- **THEN** a execução registrada demonstra a ordem das etapas e a notificação
  referencia o relatório persistido nessa rodada

#### Scenario: Avaliação não encontra opção elegível
- **WHEN** a avaliação determinística não gera sugestão
- **THEN** o agente recebe o desfecho persistido e não cria nem reclassifica uma
  estratégia por conta própria

#### Scenario: Enriquecimento quantitativo falha
- **WHEN** a decisão determinística já foi persistida e o enriquecimento
  quantitativo falha
- **THEN** a sugestão e o desfecho permanecem persistidos, e a execução registra
  a falha de enriquecimento separadamente

### Requirement: Execuções não se sobrepõem
O sistema SHALL garantir no máximo uma execução ativa por tipo de fluxo e janela
lógica. Uma repetição do mesmo evento SHALL ser idempotente e SHALL NOT duplicar
consumo de provedor, sugestão, relatório ou notificação.

#### Scenario: Novo disparo chega durante execução ativa
- **WHEN** um fluxo do mesmo tipo ainda está em execução e chega outro disparo
  para a mesma janela
- **THEN** o novo disparo é recusado ou marcado como duplicado sem iniciar uma
  segunda coleta

#### Scenario: Evento é entregue novamente
- **WHEN** o agendador repete um evento cujo identificador lógico já foi
  processado
- **THEN** o sistema retorna o resultado existente sem repetir efeitos externos

### Requirement: Recuperação é limitada e explícita
O sistema SHALL aplicar tentativas automáticas limitadas a falhas transitórias e
SHALL registrar cada tentativa sob a mesma execução lógica. Falhas permanentes
ou esgotamento de tentativas SHALL terminar em estado final observável.

#### Scenario: Falha transitória ao iniciar compute
- **WHEN** a plataforma não consegue iniciar a tarefa na primeira tentativa
- **THEN** o agendador tenta novamente dentro do limite configurado e mantém a
  correlação com a execução lógica original

#### Scenario: Limite de tentativas esgotado
- **WHEN** todas as tentativas configuradas falham
- **THEN** a execução termina como falha e produz sinal para o alerta
  operacional

### Requirement: Persistência precede notificação
O sistema SHALL persistir o relatório no Neon antes de tentar notificá-lo. Uma
falha de notificação SHALL NOT apagar nem invalidar o relatório já persistido.

#### Scenario: SMTP indisponível após geração
- **WHEN** o relatório foi persistido e o envio SMTP falha
- **THEN** o relatório permanece consultável e a etapa de notificação termina
  como falha explícita

### Requirement: Alerta de ausência é independente
O sistema SHALL executar, depois do fechamento, uma verificação independente do
fluxo avaliado, capaz de detectar ausência de execução, falha, execução órfã ou
indisponibilidade do banco.

#### Scenario: Pipeline diário não iniciou
- **WHEN** chega o horário da verificação e não existe execução esperada
- **THEN** o alerta independente registra a condição e tenta notificá-la sem
  depender do pipeline ausente
