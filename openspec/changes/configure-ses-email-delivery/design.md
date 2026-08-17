## Context

Ver `proposal.md — Why` para a motivação. O que restringe o desenho:

- O código já define o contrato de ambiente e não muda:
  `ConfigSMTP.from_env()` lê `SMTP_HOST`, `SMTP_PORT`, `SMTP_TO`, `SMTP_USER`,
  `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS`, e trata `USER` sem `PASSWORD`
  (e `HOST` sem `TO`) como erro explícito.
- A encanação da infraestrutura já existe: as sete variáveis não secretas já
  são `environment` do task definition, `SMTP_PASSWORD` já é uma das seis
  chaves do container de segredo do runtime operacional, e a security group já
  libera egress em `var.smtp_port`. Falta o provedor e os valores.
- Guardrails do repo que o desenho não pode violar
  (`scripts/check_terraform.py`): nenhum
  `aws_secretsmanager_secret_version` no plano; nenhuma variável ou output com
  nome de formato secreto; nenhum segredo em `*.tfvars`; nenhuma ação IAM
  ampla fora da allowlist justificada.

Estado da conta AWS `351093152305`, verificado em 2026-08-17 contra a API:

- `email-smtp.sa-east-1.amazonaws.com:587` responde com `STARTTLS` e
  `AUTH PLAIN LOGIN` — o caminho que `notificar.enviar()` já implementa.
- `sesv2 get-account` retorna `ProductionAccessEnabled: false`: a conta está no
  **sandbox** do SES, com cota de 200 mensagens/24h e 1 msg/s.
- `list-email-identities` retorna vazio: nenhuma identidade existe ainda.

## Goals / Non-Goals

**Goals:**

- Entregar o alerta e o relatório por um canal que vive na mesma conta AWS,
  descrito em Terraform, com credencial de menor privilégio possível.
- Manter o valor da credencial fora do plano, do state e do inventário
  versionado.
- Eliminar a configuração parcial que a própria infraestrutura produz hoje.

**Non-Goals:**

- Sair do sandbox do SES (ver decisão 2).
- Domínio próprio, DKIM, SPF ou DMARC — sem domínio do projeto, não há o que
  assinar; a identidade é um endereço.
- Entrega por outro canal (SNS para negócio, Telegram, webhook). SNS continua
  restrito a orçamento e alarmes da conta.
- Reescrever `notificar.py` ou `alertar_pregao.py`.
- Rotação automática da credencial.

## Decisions

### 1. SES por SMTP, não pela API do SES

O SES aceita envio pela API (`SendEmail`) ou pelo endpoint SMTP. Escolho SMTP.

*Por quê:* o código de entrega já é SMTP puro e é exercitado por testes; a
alternativa exigiria um caminho de envio novo em `notificar.py`, com
`boto3` no container operacional, para ganhar nada em uma mensagem por dia.
Mais importante, manter SMTP mantém o projeto **portável**: trocar o SES por
qualquer outro servidor é mudar quatro variáveis de ambiente, não reescrever
uma camada.

*Custo aceito:* a senha SMTP é derivada da chave de acesso IAM, o que
acrescenta um passo administrativo que a API não teria.

### 2. Permanecer no sandbox do SES

No sandbox, o SES só entrega para endereços verificados e limita a 200
mensagens/24h.

*Por quê:* o único destinatário é o titular, que também é o remetente — uma
identidade verificada satisfaz as duas pontas. O volume previsto é o relatório
diário mais o alerta em dia útil, mais tentativas manuais: duas ordens de
grandeza abaixo da cota. Pedir acesso de produção significa abrir chamado,
justificar caso de uso e assumir responsabilidade por reputação de envio para
terceiros — para um sistema que não envia a terceiros.

*Consequência declarada:* adicionar um destinatário novo (um segundo e-mail,
alguém da família) exige verificar aquele endereço antes, ou o envio é
recusado. Isso é uma limitação real do desenho, não um esquecimento, e vai
para o runbook.

### 3. Terraform cria a identidade de envio; a chave nasce fora dele

O módulo declara `aws_sesv2_email_identity` e um `aws_iam_user` com política
inline restrita a `ses:SendRawEmail` sobre o ARN daquela identidade. O módulo
**não** declara `aws_iam_access_key`.

*Alternativa recusada:* `aws_iam_access_key` expõe o atributo
`ses_smtp_password_v4`, o que resolveria a derivação em uma linha. Mas o valor
iria para o state em texto claro e o repo tem regra explícita contra isso — a
mesma razão por que nenhum `aws_secretsmanager_secret_version` existe no plano.
Conveniência de uma linha não vale abrir a exceção que todo o resto da infra
evita.

*Fluxo resultante:* `aws iam create-access-key` local → derivação da senha →
`aws secretsmanager put-secret-value` com o JSON completo das seis chaves. O
`AccessKeyId` (não secreto) vira `smtp_user` no inventário versionado; a senha
derivada vira `SMTP_PASSWORD` no container.

*Por que `SendRawEmail` e não `SendEmail`:* o endpoint SMTP autentica e envia
mensagens MIME completas, o que a AWS autoriza por `ses:SendRawEmail`. Conceder
`SendEmail` não habilitaria o caminho SMTP.

### 4. A condição `ses:FromAddress` fecha a política

Além de escopar o recurso ao ARN da identidade, a política carrega
`StringEquals` em `ses:FromAddress` com o remetente configurado.

*Por quê:* o escopo por identidade já impede enviar por outra identidade, mas a
condição torna a intenção legível e sobrevive a alguém adicionar uma segunda
identidade ao módulo depois. É defesa barata contra uma mudança futura.

### 5. `SMTP_TO` deixa de ser derivado de `notification_email`

Hoje `infra/environments/prod/main.tf:89` passa
`smtp_to = var.notification_email`. Passa a existir `var.smtp_to` própria, e o
módulo `operations` injeta o par host/destinatário **condicionalmente**: com
`smtp_host` vazio, nenhuma das duas variáveis entra no `environment` do
container.

*Por quê:* é a causa mecânica da falha em produção. `notification_email` é o
destinatário de orçamento e alarme do SNS — mesmo endereço, propósito
diferente. Ao ser reusado como `SMTP_TO`, ele publicou meia configuração no
container e transformou "canal não configurado" (aviso) em "canal quebrado"
(`FalhaCritica`). Separar as duas variáveis faz o estado inválido deixar de ser
alcançável a partir do inventário.

*Alternativa recusada:* relaxar `ConfigSMTP.from_env()` para tolerar host
vazio com destinatário preenchido. Isso trocaria uma falha alta por um silêncio
— exatamente a inversão que o projeto evita em `CalendarioVencido` e no
alerta independente. O código está certo; o inventário é que produzia o estado
impossível.

### 6. A derivação da senha SMTP vira script versionado

`scripts/ses_smtp_password.py` implementa a derivação documentada pela AWS
(HMAC-SHA256 encadeado sobre `AWS4<secret>` com data fixa `11111111`, região,
serviço `ses`, terminal `aws4_request`, mensagem `SendRawEmail`, prefixada pelo
byte de versão `0x04` e codificada em base64). Lê a chave de `stdin` ou de
variável de ambiente, nunca de argumento de linha de comando.

*Por quê:* o console do SES gera a credencial pronta, mas por um caminho manual
que também cria um usuário IAM fora do Terraform — dois donos para o mesmo
recurso. Com o script, o usuário é do Terraform e a derivação é reproduzível e
auditável. Argumento de linha de comando fica no histórico do shell e na tabela
de processos, por isso a leitura é por `stdin`.

*Teste:* o algoritmo é determinístico, então o script tem teste com vetor fixo
— chave conhecida e região conhecida produzem senha conhecida. Sem isso, um
erro de derivação só apareceria como `535 Authentication Credentials Invalid`
em produção, e seria confundido com credencial errada.

### 7. Permissões de deploy escopadas por ARN, como o resto do bootstrap

A role de deploy ganha dois statements novos: um para os verbos SES da
identidade (`ses:CreateEmailIdentity`, `ses:DeleteEmailIdentity`,
`ses:GetEmailIdentity`, `ses:TagResource`, `ses:UntagResource`,
`ses:ListTagsForResource`), escopado ao ARN
`arn:aws:ses:sa-east-1:<conta>:identity/<endereço>`; outro para o usuário IAM
de envio, escopado ao ARN daquele usuário. `ses:ListEmailIdentities` exige
`Resource: "*"` — entra na allowlist justificada de
`scripts/check_terraform.py`, com comentário, como já ocorre com
`cognito-idp:ListUserPools`.

*Nota deliberada:* a role de deploy **não** recebe `iam:CreateAccessKey`. Ela
cria o usuário; ela não pode fabricar credencial de envio. Quem cria a chave é
o operador humano, localmente.

## Risks / Trade-offs

- **A verificação da identidade é manual e assíncrona** → `terraform apply`
  cria a identidade, a AWS envia um e-mail com link, e o envio só funciona
  depois do clique. `verified_for_sending_status` fica `false` até lá. O
  runbook trata isso como passo explícito, e a tarefa de validação só passa
  depois de uma entrega real observada.
- **Sandbox recusa destinatário não verificado** → aceito na decisão 2;
  documentado no runbook junto do comando para verificar um endereço novo.
- **Gmail pode classificar como spam** → sem domínio próprio, o remetente é um
  endereço `@gmail.com` verificado enviando por infraestrutura AWS, o que é
  material de filtro. Mitigação: a tarefa de validação exige confirmar a
  chegada **na caixa de entrada**, e o runbook manda marcar como confiável;
  se recorrer, a saída é um domínio próprio com DKIM, que é change própria.
- **A senha SMTP passa pela máquina do operador** → é inerente ao fluxo
  escolhido na decisão 3. Mitigação: leitura por `stdin`, gravação por arquivo
  com permissão restrita, e o runbook manda apagar o arquivo temporário; o
  histórico do shell nunca vê o valor.
- **Uma credencial vazada envia e-mail em nome do titular** → limitada a uma
  identidade e a 200 mensagens/24h pelo sandbox, sem acesso a leitura. A
  rotação é `create-access-key` → atualizar segredo e `smtp_user` →
  `delete-access-key`, no runbook.
- **Custo** → dentro do orçamento de USD 5: o volume previsto custa frações de
  centavo por mês, mas o alarme de orçamento existente continua sendo o
  guarda-corpo.

## Migration Plan

1. `terraform apply` cria identidade e usuário de envio. O inventário já traz
   `smtp_from` — o endereço é insumo para criar a identidade, então ele precede
   o apply que liga o canal, e `var.smtp_from` por isso não tem default vazio.
   Nada mais muda: com `smtp_host` e `smtp_to` ainda vazios, o container
   continua subindo sem canal, e o comportamento é o de hoje.
2. Verificar a identidade pelo link enviado ao endereço.
3. Criar a chave de acesso, derivar a senha, gravar o JSON completo das seis
   chaves no container operacional.
4. Preencher `smtp_host`, `smtp_user`, `smtp_from` e `smtp_to` no inventário e
   aplicar de novo — é este apply que liga o canal.
5. Validar por execução real do fluxo `alert`.

**Rollback:** esvaziar `smtp_host` no inventário e aplicar. O canal desliga por
completo (a injeção condicional derruba host e destinatário juntos) e o sistema
volta ao estado atual, com o relatório disponível pelas demais superfícies. A
identidade e o usuário podem permanecer, sem custo por existirem.
