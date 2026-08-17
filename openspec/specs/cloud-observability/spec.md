# cloud-observability Specification

## Purpose

Tornar cada requisição e execução hospedada diagnosticável, com sinais duráveis
que diferenciem falhas de plataforma, aplicação, dados e integrações externas.

## Requirements

### Requirement: Logs estruturados e correlacionáveis
O sistema SHALL emitir logs estruturados com ambiente, componente, execução ou
requisição, etapa, resultado e duração. Todas as mensagens de uma mesma
execução lógica SHALL compartilhar um identificador de correlação.

#### Scenario: Diagnóstico de uma execução diária
- **WHEN** um operador pesquisa pelo identificador da execução
- **THEN** encontra os eventos de todas as etapas e tentativas em ordem, sem
  precisar correlacioná-los por horário aproximado

#### Scenario: Exceção contém configuração sensível
- **WHEN** uma exceção ou objeto de configuração é registrado
- **THEN** URLs credenciadas, tokens, chaves e senhas são mascarados ou omitidos

### Requirement: Resultados operacionais distinguem classes de falha
O sistema SHALL distinguir falha de disparo, falha de inicialização da tarefa,
falha total de etapa, sucesso parcial de coleta, indisponibilidade do banco,
falha de notificação e erro da API.

#### Scenario: Uma fonte falha para parte dos tickers
- **WHEN** a coleta persiste dados de alguns tickers e falha para outros
- **THEN** a execução é observável como sucesso parcial e identifica fonte,
  contagem e tickers afetados

#### Scenario: Tarefa não chega a iniciar
- **WHEN** o agendador não consegue iniciar o runtime operacional
- **THEN** a falha é observável sem depender de um log que somente a tarefa
  iniciada poderia produzir

### Requirement: Alarmes acionáveis
O sistema SHALL produzir alarmes para ausência ou falha do pipeline esperado,
execução órfã, erro de inicialização de tarefa, erro elevado da API e esgotamento
de conexões com o banco. Cada alarme SHALL indicar ambiente, componente e forma
de localizar a execução ou requisição afetada.

#### Scenario: Pipeline esperado não conclui
- **WHEN** passa a janela operacional sem uma conclusão válida
- **THEN** um alarme é acionado e identifica o fluxo e a janela ausente

#### Scenario: Taxa de erro da API ultrapassa o limite
- **WHEN** a taxa de respostas 5xx excede o limiar configurado
- **THEN** um alarme é acionado com ligação para os logs do período

### Requirement: Retenção e custo são definidos
O sistema SHALL configurar retenção finita para logs e métricas operacionais,
identificar recursos por ambiente e centro de custo e alertar quando o gasto
mensal da infraestrutura ultrapassar o orçamento configurado.

#### Scenario: Log ultrapassa a retenção
- **WHEN** um evento de log fica mais antigo que o período configurado
- **THEN** ele é expirado automaticamente em vez de ser armazenado por tempo
  indefinido

#### Scenario: Gasto projetado excede orçamento
- **WHEN** o custo real ou projetado ultrapassa o limiar mensal configurado
- **THEN** o sistema produz uma notificação de orçamento independente do agente
  de relatório

### Requirement: Saúde da API não depende de escrita
O sistema SHALL oferecer um sinal de saúde da API que comprove disponibilidade
do runtime e, separadamente, disponibilidade do Neon, sem alterar dados de
carteira ou disparar processos operacionais.

#### Scenario: API disponível com banco indisponível
- **WHEN** o runtime responde mas não consegue consultar o Neon
- **THEN** os sinais distinguem aplicação disponível de dependência de banco
  indisponível
