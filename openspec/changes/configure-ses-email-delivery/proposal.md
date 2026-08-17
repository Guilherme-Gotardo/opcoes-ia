## Why

O fluxo `alert` de 2026-08-17 (`execution_id
2aac5da2-5b56-4dc1-9fcd-11d8025f4fbb`) terminou em `FalhaCritica`: a etapa
`notificacao_alerta` levantou `SMTP_HOST e SMTP_TO devem ser configurados
juntos`. O canal de entrega nunca foi configurado — é a última pendência
declarada do cutover serverless — e, pior, a infraestrutura hoje **fabrica** o
estado inválido: `infra/environments/prod/main.tf:89` faz
`smtp_to = var.notification_email`, então o container sobe com `SMTP_TO`
preenchido pelo destinatário do SNS e `SMTP_HOST` vazio. Sem canal, o alerta
independente de "o pipeline não rodou hoje" não alerta ninguém, que é
exatamente a condição que ele existe para cobrir.

## What Changes

- Provisionar identidade de e-mail verificada no Amazon SES em `sa-east-1` e
  uma identidade IAM de envio dedicada, com permissão restrita a enviar por
  aquela identidade — sem console, sem credencial criada à mão fora do
  inventário declarado.
- **A senha SMTP continua fora do Terraform.** A chave de acesso é criada por
  canal administrativo local, convertida em senha SMTP e gravada na chave
  `SMTP_PASSWORD` do container operacional no Secrets Manager, que já existe e
  hoje guarda string vazia. Nenhum `aws_iam_access_key` entra no plano ou no
  state.
- Corrigir o acoplamento que produz configuração parcial: `SMTP_TO` passa a ser
  injetado no task definition **somente quando** o host estiver configurado. O
  destinatário de negócio deixa de ser derivado silenciosamente do destinatário
  de orçamento/alarme do SNS.
- Ampliar as permissões da role de deploy no bootstrap para os recursos SES e
  para a identidade de envio, mantendo o escopo por ARN.
- Registrar o procedimento operacional (verificação da identidade, criação e
  rotação da credencial, teste de entrega) no `docs/RUNBOOK-CLOUD.md`.

Não muda: a decisão de que envio **não é ferramenta do agente**; o texto do
relatório e do alerta; a política de falhar explicitamente quando o canal
estiver configurado e a entrega não acontecer.

## Capabilities

### New Capabilities
- `email-notification-delivery`: como o sistema entrega e-mail operacional —
  identidade de envio verificada, credencial de envio-apenas, comportamento
  quando o canal está ausente, parcialmente configurado ou indisponível, e a
  proibição de o canal virar capacidade do modelo.

### Modified Capabilities
- `cloud-application-hosting`: o requisito "Segredos são injetados em runtime"
  passa a cobrir explicitamente a credencial de envio de e-mail — ela é
  gravada fora do Terraform, lida só pelo runtime operacional, e a API não a
  recebe.

## Impact

- `infra/modules/notifications/` (novo): identidade SES e identidade IAM de
  envio.
- `infra/modules/operations/main.tf`: injeção condicional de `SMTP_TO`;
  `infra/environments/prod/main.tf`, `variables.tf`, `prod.auto.tfvars`:
  fiação e inventário não secreto.
- `infra/bootstrap/main.tf`: permissões da role de deploy.
- `scripts/`: derivação determinística da senha SMTP a partir da chave de
  acesso (algoritmo SigV4 do SES), executada localmente.
- `docs/RUNBOOK-CLOUD.md`: procedimento e rotação.
- `tests/test_terraform_infrastructure.py`: guardrails do novo módulo.
- Nenhuma mudança em `src/agente/notificar.py` ou
  `scripts/alertar_pregao.py` — o contrato de ambiente que eles já leem é o
  que passa a ser satisfeito.
- Custo: SES cobra por mensagem (ordem de USD 0,10 por mil); o volume previsto
  é de poucas mensagens por dia útil.
