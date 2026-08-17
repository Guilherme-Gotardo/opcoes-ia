# Runbook - infraestrutura serverless

Inventario, limites e pre-requisitos do ambiente de producao. Valores secretos
nao entram neste arquivo: ficam no AWS Secrets Manager ou no GitHub Environment
`Principal`.

## Inventario de producao

| Parametro | Valor | Fonte / validacao |
|---|---|---|
| Ambiente | `prod` | Ambiente unico deste projeto pessoal |
| Regiao AWS | `sa-east-1` | Mesma regiao do Neon |
| AWS account ID | `351093152305` | Informado pelo titular em 2026-08-17; a CLI local estava com token expirado |
| Interface | `d1krzquhhr159h.cloudfront.net` | CloudFront sobre bucket S3 privado com OAC |
| API | endpoint regional `execute-api` | Gerado pelo API Gateway; sem custom domain |
| Prefixo Hosted UI | `opcoes-ia-prod` | Forma o dominio Cognito gerenciado na `sa-east-1` |
| Callback PKCE | `https://d1krzquhhr159h.cloudfront.net/auth/callback` | Rota SPA coordenada com o frontend |
| Logout | `https://d1krzquhhr159h.cloudfront.net/` | Retorno apos encerrar a sessao |
| Escopo da API | `opcoes-ia/api` | Exigido no access token pelo gateway e FastAPI |
| Usuario administrativo | `guilher.gotardo@gmail.com` | Criado fora do Terraform; self-signup desabilitado |
| Destino SNS/Budget | `guilher.gotardo@gmail.com` | Alerta independente do agente |
| Budget mensal | `USD 5` | Limiar de alerta, nao cobranca nem reserva de saldo |
| Neon pooled host | `ep-lively-firefly-actnx4rn-pooler.sa-east-1.aws.neon.tech` | Conexao TLS executada com `SELECT 1` em 2026-08-17 |
| Neon `max_connections` | `901` | `SHOW max_connections` no endpoint direto em 2026-08-17 |
| Neon pooler | Ate `10.000` clientes; transaction pooling | Documentacao oficial Neon; pool real usa ate 90% de `max_connections` |

O hostname pooled e publico, mas a connection string completa contem usuario e
senha e nunca deve aparecer em documentacao, Terraform state, imagem ou log.
Migracoes continuam usando o endpoint direto porque o pooler trabalha em modo
de transacao e nao preserva estado de sessao.

## Limites iniciais

Os valores iniciais privilegiam custo e margem de conexoes. Eles sao entradas do
Terraform, nao constantes de dominio:

| Recurso | Limite inicial | Motivo |
|---|---:|---|
| Lambda API reserved concurrency | `20` | O painel dispara endpoints em paralelo; 2 causou 20 throttles/5xx no smoke real |
| Lambda API memoria | `512 MiB` | Runtime FastAPI sem QuantLib |
| Lambda API timeout | `30 s` | Limite compativel com requisicao HTTP, sem job operacional |
| Fargate operations CPU | `512` (`0.5 vCPU`) | Um pipeline por task |
| Fargate operations memoria | `1024 MiB` | Inclui QuantLib e providers; validar no smoke test |
| Concorrencia por fluxo/janela | `1` | Impede duplicar provider, sugestao e notificacao |
| Tasks Fargate simultaneas | `2` | Permite alerta independente durante um daily lento |
| CloudWatch logs | `30 dias` | Retencao finita para controlar custo |
| Brapi | `600 requests/dia` | Teto operacional configuravel atual |

Mesmo no pico configurado, API (20), duas tasks e uma migracao administrativa
ficam muito abaixo das 901 conexoes diretas. A aplicacao usa o pooler; somente a
migracao serializada recebe a URL direta.

## Cadencia inicial

- Intraday: 14 disparos de 30 em 30 minutos, de 10:00 ate 16:30, em
  `America/Sao_Paulo`. Nao recupera disparo perdido.
- Daily: 17:10 em dias uteis, com recuperacao limitada de launch.
- Alert: 18:30 em dias uteis, independente do daily.

O codigo do calendario da B3 continua sendo a autoridade para feriado, horario
especial e vigencia. EventBridge faz apenas a janela grossa.

Com 14 intradays, uma cotacao daily, duas candles e uma opcoes, a estimativa
otimista e 18 requests por ticker/dia: o teto de 600 comporta aproximadamente
33 tickers. Requests que falham antes de persistir ainda sao subcontados pelo
proxy atual.

## Estimativa mensal AWS

Estimativa conservadora antes do primeiro mes observado, para uso pessoal e sem
NAT Gateway. Nao e cotacao: precos variam por regiao e volume, e o AWS Budget de
`USD 5` e a fonte operacional que substitui esta hipotese depois do cutover.

| Componente | Hipotese | Ordem mensal |
|---|---|---:|
| Fargate | 16 tasks por dia util, maioria curta, 0.5 vCPU/1 GiB | `USD 1-2` |
| Secrets Manager | 2 containers de runtime | `~USD 0.80` |
| Lambda + HTTP API | Um usuario, chamadas esporadicas | `< USD 1` |
| S3 + CloudFront | Bundle pequeno, PriceClass 100, trafego pessoal | `< USD 1` |
| Logs, ECR, EventBridge, SNS e Cognito | Baixo volume, retencao 30 dias, 1 MAU | `< USD 1` |
| Total inicial | Sem NAT, EFS, ALB ou instancia permanente | `USD 2-5` |

Todos os recursos que suportam tags recebem `Project=opcoes-ia`,
`Environment=prod` e `CostCenter=personal`. O Budget cobre o gasto real e
projetado da conta e publica no SNS independente de Anthropic/SMTP.

## Matriz de configuracao

`requerido` significa que o runtime deve falhar antes de trabalhar quando a
variavel nao existe. `opcional` deve produzir estado explicito quando ausente.

| Runtime | Requerido | Opcional | Nao recebe |
|---|---|---|---|
| API | `DATABASE_URL` pooled, `BRAPI_TOKEN` | limite Brapi, origem CloudFront, issuer/client/escopo Cognito | Anthropic, SMTP, OpLab, News |
| Intraday | `DATABASE_URL` pooled, `BRAPI_TOKEN` | limite Brapi | Anthropic, SMTP, OpLab, News |
| Daily | `DATABASE_URL` pooled, `BRAPI_TOKEN` | Anthropic quando houver insumo, News, OpLab legado, SMTP SES | configuracao de identidade web |
| Alert | `DATABASE_URL` pooled | SMTP SES; SNS e gerido pela AWS | Brapi, OpLab, News, Anthropic |
| Migration | `DATABASE_URL` direta | nenhuma | todos os tokens de provider e notificacao |
| CI tests | `DATABASE_URL` descartavel | dummies somente no teste do provider | Neon e segredos de producao |
| Terraform plan | role OIDC de plan, IDs e nomes Cognito nao secretos | nenhuma | segredos de runtime |
| Release | roles OIDC por job | referencias aos secrets existentes | chave AWS permanente |

Anthropic e SMTP nao bloqueiam o inicio do daily: insumo vazio nao chama o
modelo, e relatorio persistido continua valido quando envio nao esta configurado.
O canal SMTP e o SES da propria conta; ver "Notificacao por email (SES)".
Opcoes bloqueadas por plano e noticias sem provider aparecem como resultado
operacional, nunca como sucesso vazio.

## Pre-requisitos de identidade

Nao ha dominio proprio, certificado ACM ou DNS. CloudFront usa o certificado e o
hostname padrao da AWS; o Cognito usa o dominio hospedado da AWS.

Antes do primeiro apply:

1. Confirmar que `opcoes-ia-prod` esta disponivel como prefixo Cognito na
   `sa-east-1`.
2. Confirmar a callback `/auth/callback` e o logout `/` no repositorio web.
3. Renovar a autenticacao AWS local ou usar as roles OIDC do GitHub.
4. Inserir valores secretos diretamente nos stores aprovados, nunca no
   Terraform.

## Contratos do Secrets Manager

O Terraform cria somente dois containers, `opcoes-ia/prod/api` e
`opcoes-ia/prod/operations`. Nao existe `aws_secretsmanager_secret_version` na
configuracao: a primeira versao e cada rotacao sao escritas fora do Terraform,
portanto o valor nao entra no plano nem no state.

O JSON da API aceita exatamente estas duas chaves, ambas nao vazias:

```json
{
  "DATABASE_URL": "<endpoint pooled TLS do Neon>",
  "BRAPI_TOKEN": "<token Brapi>"
}
```

A Lambda recebe apenas o ARN do container em `API_RUNTIME_CONFIG_ARN`. No cold
start, `src/runtime_secrets.py` busca e valida esse JSON antes de importar a
aplicacao; o valor fica em cache somente na memoria daquela instancia.

O JSON operacional tem exatamente estas seis chaves:

```json
{
  "DATABASE_URL": "<endpoint pooled TLS do Neon>",
  "BRAPI_TOKEN": "<token Brapi>",
  "ANTHROPIC_API_KEY": "<chave ou string vazia>",
  "NEWS_API_KEY": "<chave ou string vazia>",
  "OPLAB_TOKEN": "<token legado ou string vazia>",
  "SMTP_PASSWORD": "<senha ou string vazia>"
}
```

As seis chaves precisam existir porque o agente ECS injeta cada uma pelo seletor
JSON `arn:...:secret:...:CHAVE::`; integracoes opcionais desabilitadas usam
string vazia. Host, porta, usuario, remetente e destinatario SMTP nao sao
segredos e permanecem parametros do task definition.

Depois que os containers existirem, grave cada JSON por um canal administrativo
local, por exemplo com `aws secretsmanager put-secret-value --secret-id <ARN>
--secret-string file:///caminho/protegido/runtime.json`. Nao passe o JSON na
linha de comando, em `tfvars`, output, workflow ou issue. A role de deploy nao
possui `secretsmanager:PutSecretValue` nem `GetSecretValue`; somente as roles de
execucao leem seu proprio container.

A URL **direta** administrativa do Neon nunca entra nesses containers. Ela
permanece no GitHub Environment `Principal`, no secret protegido
`DATABASE_URL`, consumido somente pelo job de migracao durante
`python -m src.db.bootstrap`. API e operacoes usam sempre a URL pooled.

O nome da variavel e o mesmo nos dois contextos; o **valor** e que difere, e a
diferenca e funcional, nao burocratica. `aplicar` protege a migracao com
`pg_advisory_lock`, que e lock de SESSAO. Medido contra o Neon em 2026-08-17:
pelo endpoint pooled, dois bootstraps concorrentes adquirem o **mesmo** lock ao
mesmo tempo e ambos seguem; pelo direto, o segundo e barrado. Por isso
`src/db/bootstrap.py` **recusa** um host com `-pooler` — e essa checagem e o
unico sinal que resta separando as duas URLs agora que o nome e comum.

## Grafo e aplicacao

O grafo relevante foi separado para nao criar dependencia circular:

```text
ECR + containers ───────────────┬─> Lambda/API Gateway execute-api
Cognito User Pool -> app client/resource server -> JWT authorizer ┘
S3 privado -> CloudFront -> callback/logout e origem CORS
ECR + container operations -> VPC/roles/task definition Fargate
```

Com imagens publicadas, um `terraform apply` normal resolve o grafo sem depender
de DNS externo. Enquanto as imagens estiverem pendentes, o unico staging
permitido e criar ECR e containers sem runtime:

```bash
terraform apply \
  -target=module.ecr \
  -target=module.runtime_containers \
  -var='api_image_digest=sha256:<digest-real>' \
  -var='operations_image_digest=sha256:<digest-real>'
```

Preencha os dois containers fora do Terraform e execute um plano e apply
completos sem `-target`. Nao invoque Lambda nem rode a task antes de preencher os
JSONs. Schedules continuam fora deste recorte e nao sao criados por estas
tarefas.

## IAM deste recorte

- Lambda runtime: `secretsmanager:GetSecretValue` somente no container API e
  escrita somente no proprio log group.
- ECS execution: pull somente do repositorio operations, leitura somente do
  container operations e escrita somente no proprio log group.
- ECS task: nenhuma policy AWS de data plane; todos os providers sao acessados
  por TLS de saida e o resultado vai ao Neon.
- GitHub plan: state e metadados de recursos; nao le valor de Secrets Manager.
- GitHub deploy: state e control plane dos recursos declarados; nao le nem grava
  versoes de credencial.
- GitHub web publish: leitura/escrita somente no bucket web e invalidacao
  somente da distribuicao `ECN1AA7ZM0SFW`.
- GitHub migration: nenhuma permissao AWS de data plane; recebe somente a URL
  direta protegida durante o job.

Nao ha SDK, endpoint, IAM action, porta de entrada ou integracao de negociacao.
O runtime operacional somente persiste sugestoes para revisao humana.

## Release e contrato do frontend

GitHub Actions nao executa operacao de mercado. `ci.yml` testa com Postgres
descartavel; `terraform-plan.yml` publica apenas o plano de pull request; e
`release.yml` exige aprovacao do environment `Principal`, serializa por
`release-prod` e segue esta ordem:

1. Suite completa em Postgres descartavel.
2. Primeiro bootstrap somente de ECR e containers vazios de Secrets Manager.
3. Build unico de cada imagem, smoke/import no Dockerfile, scan local, push
   imutavel `release-<sha>` e scan ECR.
4. Migração pelo endpoint Neon direto sob advisory lock de sessao.
5. Gate de metadata exige uma versao `AWSCURRENT` nos dois containers sem ler
   seus valores. No primeiro release, preencha-os fora do Terraform e reexecute;
   os mesmos tags/digests serao reutilizados.
6. Plan/apply dos mesmos digests, sem rebuild; o estado dos schedules segue o
   gate versionado `schedules_enabled`.
7. Export de `openapi-<sha>.json` como artefato da release.

Uma reexecucao encontra os dois tags imutaveis e reutiliza seus digests. Se
somente um existir, o workflow falha em vez de reconstruir metade da release.
Falha de teste, import, scan ou migração impede o job de deploy e preserva os
digests referenciados pelos runtimes anteriores.

O artefato OpenAPI e um gate para o repositorio `opcoes-ia-web`: antes do
cutover, ele deve gerar os tipos contra esse arquivo, implementar
authorization-code+PKCE, registrar a callback
`https://d1krzquhhr159h.cloudfront.net/auth/callback` e concluir o build tipado.
O workflow do web usa OIDC para publicar assets imutaveis no S3, depois o shell
sem cache, e so entao invalida CloudFront.

Secrets exigidos no GitHub Environment `Principal`:

- `DATABASE_URL`: somente o job de migracao; endpoint **direto** TLS, sem
  `-pooler` no host. O bootstrap recusa o endpoint pooled.

Nao ha chave AWS permanente. Credenciais de runtime sao
gravadas diretamente nos dois containers Secrets Manager antes do primeiro
deploy completo, conforme os contratos deste runbook.

## Usuario Cognito e TOTP

O usuario unico nunca e recurso Terraform. Depois do primeiro apply, crie-o por
canal administrativo; o Cognito envia a senha temporaria por email sem coloca-la
no shell, state ou log:

```bash
POOL_ID="$(terraform -chdir=infra/environments/prod output -raw cognito_issuer | cut -d/ -f4)"
aws cognito-idp admin-create-user --region sa-east-1 \
  --user-pool-id "$POOL_ID" \
  --username <email> \
  --user-attributes Name=email,Value=<email> Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
```

No primeiro login pela Hosted UI, troque a senha temporaria e associe o TOTP
quando solicitado. Self-signup permanece desabilitado. Valide no minimo:

1. Access token do app client correto e com escopo `opcoes-ia/api` acessa uma
   rota protegida.
2. Requisicao anonima, ID token, token expirado, outro client e token sem o
   escopo sao recusados.
3. Acesso direto ao endpoint `execute-api` sem token continua recusado; CORS nao
   substitui autenticacao.

Se o unico autenticador TOTP for perdido, desabilite o fator antigo e force uma
nova autenticacao. O proximo login exige associar outro TOTP porque MFA continua
obrigatorio no User Pool:

```bash
aws cognito-idp admin-set-user-mfa-preference --region sa-east-1 \
  --user-pool-id "$POOL_ID" --username <email> \
  --software-token-mfa-settings Enabled=false,PreferredMfa=false
aws cognito-idp admin-reset-user-password --region sa-east-1 \
  --user-pool-id "$POOL_ID" --username <email>
```

Para conter acesso sem apagar dados, use `admin-disable-user`; para restaurar,
`admin-enable-user`. Nunca crie senha permanente por argumento de CLI ou
Terraform.

## SNS e Budget

O apply cria um topico SNS e uma subscription por email. Ela so entrega depois
que o destinatario clica em **Confirm subscription**. Confirme o estado e envie
um teste independente de Anthropic e SMTP:

```bash
TOPIC="$(terraform -chdir=infra/environments/prod output -raw alarm_sns_topic_arn)"
aws sns list-subscriptions-by-topic --region sa-east-1 --topic-arn "$TOPIC"
aws sns publish --region sa-east-1 --topic-arn "$TOPIC" \
  --subject "opcoes-ia: teste operacional" \
  --message "Teste do canal CloudWatch/SNS de producao."
```

`PendingConfirmation` nao e canal validado. O Budget de USD 5 e os alarmes
CloudWatch publicam no mesmo topico.

## Notificacao por email (SES)

O relatorio diario e o alerta independente saem por SMTP autenticado no Amazon
SES em `sa-east-1`. O modulo `infra/modules/notifications` declara a identidade
de envio (`aws_sesv2_email_identity`) e o principal de envio-apenas
(`aws_iam_user` + politica com `ses:SendRawEmail` escopada ao ARN da identidade
e condicao `ses:FromAddress`). Terraform **nao** declara `aws_iam_access_key`:
o atributo `ses_smtp_password_v4` gravaria a senha no state em texto claro.

Host, porta, usuario, remetente e destinatario nao sao segredos e vivem em
`prod.auto.tfvars`. Somente `SMTP_PASSWORD` vai para o container operacional no
Secrets Manager.

`smtp_host` e `smtp_to` sao injetados **juntos ou nenhum dos dois**. Um
`precondition` no task definition recusa o apply quando so um esta preenchido.
Isso existe porque o inverso ja quebrou producao: `smtp_to` era derivado de
`notification_email` (o destinatario do SNS), o container subia com
destinatario e sem host, e `ConfigSMTP.from_env()` tratava a metade como erro,
derrubando o fluxo `alert` com `FalhaCritica` em 2026-08-17.

### A conta esta no sandbox do SES

`sesv2 get-account` retorna `ProductionAccessEnabled: false`. No sandbox o SES
entrega **somente para enderecos verificados**, com teto de 200 mensagens/24h e
1 msg/s. Isso e suficiente e deliberado: remetente e destinatario sao o mesmo
endereco do titular, e o volume e o relatorio diario mais o alerta em dia util.

Consequencia pratica: **adicionar um destinatario novo exige verificar aquele
endereco antes**, ou o envio e recusado. Para isso:

```bash
aws sesv2 create-email-identity --email-identity <novo@exemplo.com> \
    --region sa-east-1   # a AWS envia link; o envio so funciona apos o clique
```

Sair do sandbox e um chamado de suporte e so faz sentido se um dia houver
destinatario de terceiro.

### Primeiro provisionamento

1. `terraform apply` cria identidade e usuario. `smtp_from` ja precisa estar no
   inventario, porque o endereco e insumo da identidade; `smtp_host`,
   `smtp_user` e `smtp_to` continuam vazios e o canal segue desligado.
2. Concluir a verificacao pelo link que a AWS envia ao endereco. Conferir com
   `aws sesv2 get-email-identity --email-identity <endereco> --region sa-east-1`
   ate `VerifiedForSendingStatus` virar `true`.
3. Criar a credencial e grava-la, sem passar a chave por argumento:

```bash
aws iam create-access-key --user-name opcoes-ia-prod-smtp   # anote AccessKeyId
printf %s "<SecretAccessKey>" | python -m scripts.ses_smtp_password sa-east-1
```

   Monte o JSON com as seis chaves em arquivo `0600`, com `SMTP_PASSWORD`
   recebendo a senha derivada, grave com
   `aws secretsmanager put-secret-value --secret-id <ARN operations>
   --secret-string file://<arquivo>` e apague o arquivo.
4. Preencher `smtp_host` (`email-smtp.sa-east-1.amazonaws.com`), `smtp_user`
   (o `AccessKeyId`, que nao e segredo) e `smtp_to` em `prod.auto.tfvars` e
   aplicar. **E este apply que liga o canal.**

### Rotacao da credencial de envio

`create-access-key` -> derivar a senha -> gravar o segredo e atualizar
`smtp_user` no inventario -> aplicar -> validar uma entrega -> so entao
`aws iam delete-access-key --user-name opcoes-ia-prod-smtp --access-key-id
<antigo>`. A ordem importa: deletar antes de validar deixa o canal mudo com o
sintoma parecendo problema de rede.

### Diagnostico

- `535 Authentication Credentials Invalid`: senha derivada na regiao errada (a
  regiao entra na derivacao), `smtp_user` fora de sincronia com a chave gravada,
  ou chave ja deletada. Rederive antes de suspeitar do SES.
- `554 Message rejected: Email address is not verified`: sandbox recusando um
  destinatario ou remetente nao verificado. Verifique a identidade primeiro.
- `SMTP_HOST e SMTP_TO devem ser configurados juntos`: meia configuracao
  chegou ao container. Nao deveria ser alcancavel pelo inventario; se
  acontecer, confira o `environment` da task definition ativa.
- Nenhum erro e nenhum email: confira se o canal esta ligado de fato com
  `aws ecs describe-task-definition --task-definition opcoes-ia-prod-operations
  --query 'taskDefinition.containerDefinitions[0].environment'`. Sem
  `SMTP_HOST` na lista, o canal esta desligado e o runtime apenas registra
  aviso.

### Desligar o canal

Esvazie `smtp_host` e `smtp_to` em `prod.auto.tfvars` e aplique. Os dois saem
juntos do container, o relatorio continua disponivel na interface e no banco, e
a ausencia de envio volta a ser aviso, nao falha.

## Rotacao de segredos

Monte o JSON novo em arquivo temporario com permissao `0600`, grave-o com
`put-secret-value --secret-string file://...` e apague o arquivo. Nao altere o
container Terraform nem use `tfvars`. Lambda busca a versao `AWSCURRENT` em cold
start; force uma atualizacao de configuracao ou aguarde nova instancia. ECS
resolve cada seletor JSON quando inicia uma nova task, sem nova task definition.

Depois da rotacao, rode liveness/readiness da API e um comando operacional
manual. Mantenha a versao anterior no Secrets Manager ate concluir o smoke; para
rollback de credencial, mova `AWSCURRENT` para o VersionId anterior.

## Execucao manual e resume

Obtenha cluster, task definition e rede pelo state/AWS e use override somente no
comando do container. A task e efemera e deve terminar sozinha:

```bash
python -m src.operations intraday --window <ISO-8601> --trigger manual --forcar
python -m src.operations daily --window <ISO-8601> --trigger manual
python -m src.operations alert --window <ISO-8601> --trigger manual
```

Em Fargate, passe os mesmos argumentos em
`aws ecs run-task --overrides '{"containerOverrides":[...]}'`, com public IP,
subnets e security group do output `operations_run_task_network`. Entrega
repetida da mesma janela sai como duplicada antes de chamar provider.

Para recuperar crash, use a mesma janela e `--resume`. Etapa concluida e pulada.
Etapa externa deixada em estado ambiguo e recusada ate o operador autorizar
explicitamente `--allow-external-retry <etapa>`; essa autorizacao pode repetir
custo ou efeito externo e deve ser registrada.

## Diagnostico por execution ID

Pesquise o UUID primeiro no Neon (`execucao_pipeline` e
`execucao_etapa_tentativa`) e depois nos logs `/ecs/opcoes-ia-prod-operations`.
Todos os logs da aplicacao e metricas EMF carregam `execution_id`; eventos que
falham antes do container ficam em `/aws/events/opcoes-ia-prod-task-state` e sao
correlacionados pelo task ARN.

Para API, use `x-request-id` retornado pela resposta e pesquise em
`/aws/lambda/opcoes-ia-prod-api`. `/health/live` prova somente runtime;
`/health/ready` testa o Neon sem escrever.

## Cutover e rollback

Antes de habilitar EventBridge, prove que nao existe outro disparador:

```bash
systemctl --user disable --now opcoes-ia-pregao.timer \
  opcoes-ia-alerta.timer opcoes-ia-relatorio.timer
systemctl --user is-enabled opcoes-ia-pregao.timer opcoes-ia-alerta.timer \
  opcoes-ia-relatorio.timer
aws scheduler list-schedules --region sa-east-1 \
  --group-name opcoes-ia-prod-operations
```

O cron operacional `daily-etl.yml` foi removido; GitHub Actions serve apenas
CI/CD. Registre data, timers encontrados e estado dos tres schedules. So altere
os schedules para `ENABLED` depois de login PKCE, API, tarefas, SNS e alarmes
validados. Observe uma sessao intraday e uma rodada daily completas antes de
declarar o cutover.

Rollback:

1. Desabilite os tres schedules primeiro.
2. Restaure os digests anteriores de Lambda/ECS por Terraform; nao reconstrua a
   imagem antiga.
3. Nao reverta migracao aditiva automaticamente.
4. Se precisar reativar systemd, confirme novamente que EventBridge esta
   desabilitado e registre o intervalo de contingencia.
5. Se somente a API falhar, desabilite o app client/usuario e use acesso local;
   nunca publique rota sem JWT.

## Primeiro deploy de 2026-08-17

Validado primeiro em producao com schedules desabilitados:

- Migrações `001` a `010` aplicadas no Neon e conexao pooled testada.
- Lambda respondeu liveness e ingeriu JSON correlacionado no CloudWatch.
- Frontend publicado em S3 privado + CloudFront; endpoint S3 direto respondeu
  403, callback SPA respondeu 200, login Cognito/PKCE retornou ao painel e a API
  registrou request autenticado com status 200.
- Escrita controlada adicionou VALE3 a watchlist e a removeu pelo painel. O
  primeiro refresh revelou throttling com concorrencia 2; apos elevar para 20,
  leitura paralela e rollback da escrita concluiram sem 503.
- Intraday Fargate concluiu com exit 0 e persistiu a execucao
  `6c346eb5-b68e-4393-9e60-eb16fa0c91b3`.
- O primeiro disparo EventBridge real das 15h concluiu com exit 0, execution ID
  `e7508125-0550-4090-bf91-9bd9e6618bf2`, uma unica linha para a janela,
  cotacoes 2/2 e proxy Brapi 6/600. Por decisao do titular, daily/alert naturais
  nao foram aguardados; os dois ja tinham smoke manual na mesma task definition.
- Daily concluiu o container com exit 0/estado parcial, persistiu relatorio e fez
  chamada Anthropic real; OpLab e NewsAPI locais responderam 401 e foram
  desabilitados no secret de producao.
- Alert detectou a condicao e falhou explicitamente porque SMTP nao estava
  configurado; SNS e o canal operacional independente. Resolvido depois pela
  change `configure-ses-email-delivery`, que tambem removeu a causa de a falha
  ser critica em vez de aviso: o `SMTP_TO` derivado de `notification_email`.
- Subscription SNS confirmada e mensagem de teste publicada com sucesso.
- Imagem operacional Trixie manteve 4 achados CRITICAL e 8 HIGH sem correcao
  publicada pelo ECR. O gate bloqueia achado severo corrigivel e reporta os
  unfixed, alinhado ao `ignore-unfixed` do Trivy.

Depois da quota Lambda subir para 1000, reserved concurrency 20 foi aplicada. O
inventario local encontrou os tres timers `not-found`/`inactive`, o cron legado
ja estava removido e `schedules_enabled=true` habilitou os tres schedules em
2026-08-17. Resta observar uma rodada agendada completa; a entrega de negocio
por email passou a existir com o SES (ver "Notificacao por email").

Uma migracao futura para `us-east-1` pode reduzir precos unitarios de Lambda e
Fargate, mas deve mover ou reavaliar tambem a regiao do Neon e medir latencia/
egress. Nao faz parte deste cutover validado em `sa-east-1`.

O certificado do hostname padrao `cloudfront.net` obriga o campo de politica
minima a `TLSv1`; HTTPS continua obrigatorio, mas impor TLS 1.2 no viewer exige
dominio proprio e certificado ACM. Essa restricao e aceita apenas enquanto o
projeto usa o hostname gratuito padrao.

Contas novas podem receber quota regional aplicada 10 enquanto o Service Quotas
considera 1000 o default. Nesse intervalo, a AWS recusa qualquer reserva porque
exige manter 10 execucoes nao reservadas. Somente para smoke com schedules
desabilitados, o plano aceita `-var='lambda_reserved_concurrency=-1'`; a quota da
conta ainda limita a funcao a 10. O cutover e a release normal usam 20 depois
da aprovacao. Aumento de quota e reserved
concurrency nao geram custo por si; provisioned concurrency, que nao e usado
aqui, geraria.

Na consulta de 2026-08-17, o Budget informou gasto atual USD 1,387 e forecast
USD 2,527 contra limite USD 5. Secrets Manager (USD 0,839) e EC2 Other
(USD 0,378) eram os maiores itens; S3 era USD 0,00007. Existem 20 alarmes
CloudWatch, ainda sem custo observado, portanto o forecast deve continuar sendo
acompanhado ate completar o primeiro mes. Brapi, Anthropic e Neon nao fazem
parte desse Budget AWS.
