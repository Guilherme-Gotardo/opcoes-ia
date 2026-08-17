## Why

Hoje a API e os fluxos operacionais dependem de processos locais, systemd ou
GitHub Actions, de modo que fechar o computador interrompe coleta, avaliação e
entrega do relatório. A plataforma precisa de uma execução reproduzível e
operável sem servidor permanente, preservando o Neon como fonte de verdade e a
separação entre sugestão e execução de ordens.

## What Changes

- Provisionar por infraestrutura como código a API FastAPI em API Gateway e
  Lambda, e os fluxos operacionais em tarefas efêmeras do ECS Fargate.
- Publicar imagens versionadas no ECR, com um runtime de API mínimo e um runtime
  operacional que inclua QuantLib e as dependências do agente Anthropic.
- Agendar por EventBridge Scheduler o pipeline intradiário, o fluxo diário e o
  alerta independente, preservando calendário da B3, política de recuperação e
  limite de concorrência de cada execução.
- Compor o fluxo diário na ordem coleta de mercado, consolidação de earnings,
  avaliação determinística, enriquecimento quantitativo, relatório do agente e
  notificação determinística, com estado explícito por etapa.
- Manter o Neon como banco externo único, usando endpoint pooled, concorrência
  limitada e credenciais injetadas em runtime por AWS Secrets Manager.
- Autenticar o usuário único por Amazon Cognito, usando o domínio hospedado do
  serviço e JWT validado pelo API Gateway e pela aplicação, inclusive nos
  endpoints de escrita; a interface estática será hospedada em bucket S3
  privado atrás de CloudFront com OAC e não contém dados sem consultar a API
  autenticada.
- Centralizar logs, métricas e alarmes operacionais no CloudWatch, distinguindo
  falha de disparo, falha de tarefa, falha parcial de coleta, indisponibilidade
  do banco e erro/latência da API.
- Usar GitHub Actions somente para CI/CD: testes em banco descartável, build e
  publicação de imagens, aplicação controlada do Terraform, migração única e
  deploy; o cron operacional atual será desativado no cutover.
- **BREAKING**: substituir o contrato de API restrita a `127.0.0.1` e sem
  autenticação por uma API hospedada no endpoint padrão do API Gateway que exige
  JWT Cognito e aplica CORS somente à distribuição CloudFront publicada.
- **BREAKING**: EventBridge passa a ser o único agendador operacional em
  produção; os timers systemd e o cron de ETL do GitHub Actions não podem
  permanecer ativos após o cutover.

## Capabilities

### New Capabilities
- `cloud-application-hosting`: Hospedagem serverless da API e dos runtimes
  operacionais, conectividade com Neon, imagens, segredos e limites de
  concorrência.
- `scheduled-pipeline-operations`: Agendamento, composição, idempotência,
  concorrência e semântica de falha dos fluxos intradiário, diário e de alerta.
- `cloud-observability`: Logs correlacionáveis, métricas, retenção, alarmes e
  visibilidade operacional dos componentes hospedados.
- `infrastructure-delivery`: Infraestrutura como código e promoção controlada
  por GitHub Actions, incluindo imagens, migrações, deploy e cutover.

### Modified Capabilities
- `portfolio-read-api`: Substituir o acesso exclusivamente local e sem
  autenticação por acesso hospedado e autenticado, sem permitir que a API
  dispare o pipeline operacional.
- `market-data-collection`: Produzir resultado operacional agregado que
  diferencie sucesso, sucesso parcial e falha total por fonte, sem perder o
  isolamento de falha por ticker.

## Impact

- Novos artefatos de Terraform para AWS e integração OIDC com GitHub, além de
  Dockerfiles, definições de tarefa ECS, bucket S3 privado e distribuição
  CloudFront para `opcoes-ia-web`; não permanece dependência de Cloudflare.
- Adaptação da aplicação FastAPI para Lambda e validação de JWT Cognito;
  configuração do User Pool, Hosted UI, cliente PKCE e authorizer do API
  Gateway; revisão de CORS, conexão pooled com Neon e separação dos segredos
  mínimos por runtime.
- Novo orquestrador operacional e contratos de resultado dos ETLs; persistência
  do relatório deve depender do Neon, não do filesystem efêmero da tarefa.
- Novos workflows de CI/CD e retirada do agendamento de
  `.github/workflows/daily-etl.yml` no cutover; unidades systemd permanecem
  apenas como opção de desenvolvimento/recuperação manual, desabilitadas em
  produção.
- O login PKCE e a geração do cliente OpenAPI exigem mudança coordenada no
  repositório separado `opcoes-ia-web`. Esta change também provisiona a origem
  AWS e a identidade OIDC mínima usada por aquele repositório para publicar o
  bundle imutável no S3 e invalidar CloudFront.
- Custos passam a incluir chamadas sob demanda de Lambda/API Gateway, Fargate,
  ECR, CloudWatch, Secrets Manager e EventBridge, além dos custos já existentes
  de Neon, Brapi e Anthropic.
- Nenhum componente recebe capacidade de enviar ordem a corretora: avaliação e
  agente continuam produzindo somente sugestões para revisão humana.
