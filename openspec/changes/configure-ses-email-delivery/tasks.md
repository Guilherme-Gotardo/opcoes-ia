## 1. Módulo de notificação (Terraform)

- [x] 1.1 Criar `infra/modules/notifications/` (`main.tf`, `variables.tf`,
      `outputs.tf`, `versions.tf`) seguindo o estilo de
      `modules/runtime-containers`: versão do provider fixada, tags recebidas
      por variável, sem valor secreto no plano
- [x] 1.2 Declarar `aws_sesv2_email_identity` para o endereço remetente, com
      `identity_type` de e-mail; expor `arn` e `verified_for_sending_status`
      como outputs
- [x] 1.3 Declarar `aws_iam_user` de envio e `aws_iam_user_policy` inline com
      `ses:SendRawEmail` escopado ao ARN da identidade e condição
      `StringEquals` em `ses:FromAddress`; **não** declarar
      `aws_iam_access_key`
- [x] 1.4 Expor o nome do usuário e o ARN da identidade como outputs; conferir
      que nenhum output tem nome de formato secreto (o guardrail de
      `check_terraform.py` reprova `password|secret|token|api_key`)

## 2. Fiação no ambiente de produção

- [x] 2.1 Instanciar `module "notifications"` em
      `infra/environments/prod/main.tf`, passando região, endereço remetente e
      tags comuns
- [x] 2.2 Criar `variable "smtp_to"` em `infra/environments/prod/variables.tf`
      e trocar `smtp_to = var.notification_email` por `smtp_to = var.smtp_to`
      na chamada do módulo `operations`
- [x] 2.3 Em `infra/modules/operations/main.tf`, tornar a injeção de
      `SMTP_HOST` e `SMTP_TO` **condicional**: com `var.smtp_host` vazio,
      nenhuma das duas entra no `environment` do container (usar `concat` com
      lista condicional, mantendo as demais variáveis inalteradas).
      **Acrescentado na implementação:** `precondition` no task definition que
      recusa o apply quando só um dos dois está preenchido — sem ela, a
      injeção condicional trocaria a falha explícita por um canal desligado em
      silêncio
- [x] 2.4 Preencher **apenas** `smtp_from` em `prod.auto.tfvars` nesta etapa.
      **Corrigido em relação ao plano:** o endereço é insumo para *criar* a
      identidade SES, então precisa existir um apply antes do que liga o
      canal; `smtp_host`, `smtp_user` e `smtp_to` é que ficam para a tarefa
      5.4. `var.smtp_from` deixou de ter default vazio por isso

## 3. Permissões da role de deploy

- [x] 3.1 Adicionar em `infra/bootstrap/main.tf` os locals com o ARN da
      identidade SES e o ARN do usuário de envio. Exigiu também
      `variable "sender_address"` no bootstrap, para escopar a permissão a uma
      identidade exata em vez de `identity/*`
- [x] 3.2 Adicionar statement de gestão da identidade SES escopado por ARN
      (`CreateEmailIdentity`, `DeleteEmailIdentity`, `GetEmailIdentity`,
      `TagResource`, `UntagResource`, `ListTagsForResource`)
- [x] 3.3 Adicionar statement de gestão do usuário de envio escopado por ARN
      (`CreateUser`, `DeleteUser`, `GetUser`, `TagUser`, `UntagUser`,
      `PutUserPolicy`, `GetUserPolicy`, `DeleteUserPolicy`,
      `ListUserPolicies`, `ListAttachedUserPolicies`, `ListAccessKeys`) —
      **sem** `iam:CreateAccessKey`. `DeleteAccessKey` e `ListGroupsForUser`
      entraram porque `force_destroy` no usuário precisa delas no rollback
- [x] 3.4 Allowlist de `scripts/check_terraform.py` **não** precisou mudar:
      nenhuma ação nova exige `Resource: "*"` — `ses:ListEmailIdentities` não
      é chamada pelo provider para um recurso nomeado. Registrado aqui para
      não parecer esquecimento
- [x] 3.5 Aplicar o bootstrap e confirmar que `python scripts/check_terraform.py`
      continua passando. **Bloqueio encontrado e resolvido:** o apply falhou
      com `LimitExceeded: Maximum policy size of 10240 bytes exceeded` — a
      política inline `terraform-deploy` já estava no teto. Como esse limite é
      **agregado por role**, uma segunda inline não resolveria; as permissões
      do canal viraram a managed policy
      `opcoes-ia-prod-deploy-notifications`, anexada à role. Confirmado por
      `aws iam list-attached-role-policies`

## 4. Derivação da senha SMTP

- [x] 4.1 Criar `scripts/ses_smtp_password.py`: lê a secret access key de
      `stdin` (ou de variável de ambiente), recebe a região por argumento, e
      imprime a senha SMTP derivada; recusa receber a chave por argumento de
      linha de comando
- [x] 4.2 Escrever teste em `tests/` com vetor determinístico (chave e região
      fixas → senha esperada) e teste de que passar a chave por argumento é
      recusado
- [x] 4.3 Rodar `pytest` da nova suíte apontando para o banco descartável,
      conforme a convenção do repo

## 5. Provisionamento e ligação do canal

- [x] 5.1 `terraform apply` criando identidade e usuário; confirmar que o
      container operacional continua sem `SMTP_HOST`/`SMTP_TO` (canal ainda
      desligado, comportamento idêntico ao de hoje). Aplicado: 3 recursos
      criados, task definition na **revisão 2** com `environment` contendo
      apenas `BRAPI_REQUESTS_DIA_MAXIMO`, `OPCOES_IA_ENV` e
      `OPCOES_IA_COMPONENT` — o `SMTP_TO` órfão saiu de produção neste apply,
      então a `FalhaCritica` do fluxo `alert` já não pode se repetir
- [x] 5.2 Concluir a verificação da identidade pelo link enviado pela AWS;
      confirmar `verified_for_sending_status` verdadeiro via
      `aws sesv2 get-email-identity`. Confirmado: `VerifiedForSendingStatus:
      true`
- [x] 5.3 Criar a chave de acesso do usuário de envio por canal administrativo
      local, derivar a senha com o script da tarefa 4.1 e gravar o JSON
      completo das seis chaves do container operacional com
      `aws secretsmanager put-secret-value --secret-string file://...`;
      apagar o arquivo temporário. `AccessKeyId AKIAVDPWILIY72V5FZ7R`; as
      outras cinco chaves conferidas como preservadas.
      **Correção que o caminho revelou:** o runbook mandava `fileb://`, que é
      de `--secret-binary`. Com `--secret-string` o CLI recusa e **ecoa o
      payload na mensagem de validação** — vazou segredo de produção na saída.
      As três ocorrências no `docs/RUNBOOK-CLOUD.md` foram corrigidas para
      `file://`, e a primeira tentativa deixou uma access key órfã que foi
      removida
- [x] 5.4 Preencher `smtp_host`, `smtp_port`, `smtp_user`, `smtp_from` e
      `smtp_to` em `prod.auto.tfvars` (nenhum deles é segredo) e aplicar; o
      canal liga neste apply. Task definition na **revisão 3** com as seis
      variáveis SMTP presentes

## 6. Validação de ponta a ponta

- [x] 6.1 Disparar o fluxo `alert` na task definition atualizada e observar
      exit 0 com o alerta entregue (ou "sem alerta" legítimo, se não houver
      condição — nesse caso forçar a condição para exercitar a entrega).
      Execução `3f5a474d-dcfb-4069-8a57-a3598719126a`, condição `daily
      ausente`, etapa `notificacao_alerta` **sucesso em 332ms** e exit 0 —
      é a mesma etapa que falhava com `FalhaCritica`. `SentLast24Hours: 1.0`
      no SES confirma a saída da mensagem
- [ ] 6.2 Confirmar a chegada da mensagem **na caixa de entrada** do
      destinatário, não em spam; marcar o remetente como confiável se
      necessário
- [x] 6.3 Verificar no CloudWatch que nenhum valor de credencial aparece nos
      logs da execução. Varredura por senha derivada, access key ID, chave
      Anthropic, URL credenciada e token Brapi: nenhuma ocorrência
- [ ] 6.4 Observar a próxima execução natural do fluxo `daily` entregando o
      relatório do dia, e confirmar que a notificação foi reservada uma única
      vez (sem duplicata no repositório de notificação)

## 7. Guardrails e documentação

- [x] 7.1 Estender `tests/test_terraform_infrastructure.py`: o módulo
      `notifications` não contém `aws_iam_access_key`; a política de envio é
      escopada por ARN de identidade; `SMTP_TO` é injetado condicionalmente em
      `modules/operations`
- [x] 7.2 Adicionar seção de notificação por e-mail ao `docs/RUNBOOK-CLOUD.md`:
      arquitetura do canal, limitação do sandbox (destinatário novo exige
      verificação prévia), procedimento de rotação da credencial
      (`create-access-key` → atualizar segredo e `smtp_user` →
      `delete-access-key`) e diagnóstico de `535 Authentication Credentials
      Invalid`
- [x] 7.3 Atualizar a tabela de credenciais por runtime em
      `docs/RUNBOOK-CLOUD.md`, que hoje lista SMTP como não configurado
- [x] 7.4 Atualizar o "Estado atual" do `CLAUDE.md`: SMTP deixa de ser
      pendência do cutover; registrar a decisão de permanecer no sandbox e o
      que ela custa
