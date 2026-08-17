## Context

Veja `proposal.md` para a motivação. Hoje o projeto tem quatro formas de
execução com premissas locais diferentes:

- FastAPI inicia por Uvicorn em `127.0.0.1`, sem autenticação, e a mesma
  aplicação já contém rotas de leitura e escrita de carteira.
- O pipeline intradiário, o relatório do agente e o alerta independente são
  timers systemd; fechar a sessão ou desligar a máquina interrompe o serviço.
- O ETL diário é cron do GitHub Actions e não compõe avaliação, QuantLib,
  agente e notificação numa única execução observável.
- Neon é a fonte de verdade. A conexão direta e uma conexão nova por operação
  foram escolhidas para baixa concorrência, não para cold starts simultâneos.

QuantLib, Anthropic e Yahoo estão em dependências opcionais; o runtime diário
precisa delas de forma reproduzível. Os ETLs isolam falha por ticker, mas vários
terminam com código zero mesmo quando uma fonte falha por completo. Os relatórios
também escrevem arquivos locais, que não sobrevivem a uma tarefa efêmera.

A interface está no repositório separado `opcoes-ia-web`. Esta change prepara a
origem S3/CloudFront, o contrato, as políticas compartilhadas e a role OIDC de
publicação; o código PKCE e o workflow do bundle são coordenados naquele
repositório.

## Goals / Non-Goals

**Goals:**

- Ter um único ambiente de produção em `sa-east-1`, próximo ao Neon existente,
  sem instância de aplicação permanentemente ligada.
- Tornar API, pipeline intradiário, pipeline diário e alerta reproduzíveis,
  autenticados, correlacionáveis e recuperáveis.
- Preservar as invariantes de domínio: dados de mercado vêm de fonte, decisão é
  determinística, QuantLib é contexto e toda estratégia é apenas sugestão.
- Manter custos fixos baixos e limites explícitos de concorrência, retenção e
  orçamento.
- Fazer deploy e rollback por artefatos imutáveis, com migração serializada e
  sem chave AWS permanente no GitHub.

**Non-Goals:**

- Hospedar o Neon dentro da AWS ou introduzir outro banco, cache ou fila como
  fonte de verdade.
- Implementar o frontend ou mover seu código para este repositório.
- Substituir Brapi, Anthropic, SMTP ou os providers de earnings.
- Criar alta disponibilidade multi-região, ambiente permanente de staging ou
  disaster recovery automatizado nesta primeira implantação pessoal.
- Executar ordens, integrar corretora ou permitir que o agente reavalie os
  critérios determinísticos.
- Resolver nesta change a falta de acesso a opções no plano Free da Brapi.

## Decisions

### 1. Terraform gerencia somente a infraestrutura AWS

Usar Terraform com provider AWS, organizado em:

- `infra/bootstrap`: backend remoto de estado e identidade OIDC inicial.
- `infra/modules`: módulos pequenos para imagens, frontend estático, API,
  identidade Cognito, runtime operacional, agendamentos, observabilidade e
  segredos referenciados.
- `infra/environments/prod`: composição e valores não secretos de produção.

O estado ficará em S3 com versionamento, criptografia e lock nativo do backend
S3. A criação inicial do bucket e das roles OIDC é um bootstrap único documentado;
depois disso, todo plano e aplicação ocorre no GitHub Actions. Segredos entram
por Secrets Manager e variáveis protegidas do GitHub, nunca como valores em
`tfvars` ou outputs. O Terraform cria bucket S3 privado, distribuição CloudFront
com Origin Access Control e role OIDC limitada à publicação do frontend. Não há
provider, token, DNS ou recurso Cloudflare.

Alternativas consideradas:

- AWS CDK: integra bem com AWS, mas exigiria outra linguagem/toolchain e
  substituiria a base Terraform já validada.
- AWS SAM: bom para Lambda, porém não cobre bem ECS, Cognito e a composição
  completa.
- Configuração manual: reduz o primeiro diff, mas cria estado invisível e torna
  rollback e reprodução não auditáveis.

### 2. API Gateway HTTP API invoca Lambda por imagem

A API será empacotada em uma imagem Linux `x86_64` mínima, com dependências de
API e um adaptador ASGI para Lambda. API Gateway HTTP API usa seu endpoint
regional padrão `execute-api` e encaminha as rotas protegidas à Lambda somente
depois do JWT authorizer. Não haverá certificado ACM, custom domain nem DNS da
aplicação.

A Lambda ficará fora de VPC: Neon e Brapi já são serviços públicos TLS, e
colocá-la em subnets privadas criaria NAT Gateway de custo fixo sem proteger
essas saídas. Reserved concurrency e timeout serão pequenos e configuráveis;
o valor inicial será validado contra o limite do Neon antes do cutover.

O runtime da API não carrega QuantLib, Anthropic, Yahoo, SMTP nem comandos
operacionais. `Settings` será separado por contexto para que abrir conexão não
exija todos os tokens. Como `/catalogo` consulta Brapi, a API ainda recebe
`BRAPI_TOKEN`; `DATABASE_URL` usa o endpoint pooled do Neon.

Alternativas consideradas:

- Lambda ZIP: pode ter cold start menor, mas cria empacotamento diferente do
  runtime testado e complica dependências nativas futuras.
- FastAPI em Fargate permanente: elimina adaptação ASGI, mas mantém custo e
  processo ligados mesmo sem uso.
- Lambda em VPC com NAT: adiciona custo fixo e pontos de falha sem evitar acesso
  público aos provedores externos.

### 3. Cognito autentica o usuário e API Gateway valida o access token

Um Cognito User Pool terá cadastro público desabilitado e MFA TOTP obrigatório.
O único usuário será criado administrativamente depois do provisionamento, fora
do Terraform, para que senha temporária e estado de credencial nunca entrem no
state. O Hosted UI usa o domínio gerenciado gratuito da AWS.

O frontend usa um app client público sem secret, authorization code flow com
PKCE e callback em
`https://<distribution>.cloudfront.net/auth/callback`. O cliente solicita um escopo
próprio da API. API Gateway valida issuer, client/audience e escopo do access
token antes de invocar a Lambda; FastAPI repete assinatura, issuer, client,
expiração, `token_use=access` e escopo com cache curto das chaves públicas. A
validação cobre GET e POST; `OPTIONS` é apenas preflight e sinais de saúde
deliberadamente públicos não acessam domínio. CORS permite somente a origem
CloudFront em produção e a origem local no modo de desenvolvimento explícito.

O bundle estático permanece publicamente carregável no CloudFront, mas não contém
dados nem credenciais. Sem login, toda leitura ou escrita protegida é recusada.

Alternativas consideradas:

- Hospedagem externa: manteria uma segunda plataforma, credencial e plano de
  controle sem necessidade para um bundle estático pequeno.
- CORS como proteção: CORS é política de navegador e não impede `curl` ou outro
  cliente direto.
- API key ou bearer token estático: não oferece login, expiração, MFA nem rotação
  adequada para credencial presente no browser.
- VPN/Tailscale: funciona, mas reintroduz cliente e rede privada que a escolha
  serverless pretende evitar.

### 4. S3 privado e CloudFront hospedam o frontend estático

O bundle de `opcoes-ia-web` será enviado para bucket S3 sem acesso público. Uma
distribuição CloudFront usa Origin Access Control para ler apenas aquele bucket,
HTTPS obrigatório e o domínio padrão `cloudfront.net`, sem Route 53, ACM ou
domínio pago. Respostas 403/404 de rotas do SPA retornam `index.html`, sem tornar
objetos privados acessíveis diretamente pelo endpoint S3.

O domínio da distribuição é output Terraform e alimenta no mesmo grafo as URLs
de callback/logout Cognito e a origem CORS da API. O build do frontend recebe
como configuração pública esse domínio, endpoint API, Hosted UI, client ID e
escopo. Nenhum desses valores é segredo.

Uma role OIDC exclusiva confia somente no repositório `opcoes-ia-web` e pode
sincronizar objetos no bucket e criar invalidação apenas na distribuição exata.
O workflow gera tipos do OpenAPI versionado, faz lint/build, publica assets com
cache longo e `index.html` sem cache, e só então invalida os caminhos do shell.

Alternativas consideradas:

- Amplify Hosting: reduz comandos de publicação, mas adiciona outro plano de
  controle e integração de repositório para um site estático simples.
- Bucket público sem CloudFront: perde TLS/edge, expõe a origem e não entrega um
  hostname adequado ao callback OAuth.
- Domínio próprio/Route 53: melhora o nome, mas adiciona custo e gestão que não
  são necessários para validar o fluxo.

### 5. Uma imagem operacional Fargate executa comandos efêmeros

Uma segunda imagem contém core, QuantLib, SDK Anthropic e providers opcionais,
com versões travadas e teste de import durante o build. Ela é usada por três
comandos:

- `intraday`: calendário B3, cotação e avaliação; o enriquecimento continua
  posterior ao commit determinístico.
- `daily`: cotações, candles, opções, notícias se configuradas, earnings,
  avaliação, QuantLib, relatório determinístico persistido, relatório Anthropic
  e notificação.
- `alert`: verificação independente de ausência/falha/órfão/banco.

EventBridge Scheduler chama `RunTask` em um cluster ECS sem serviços
residentes. As tarefas ficam em duas subnets públicas, sem porta de entrada,
com public IP e security group apenas de saída. Isso evita NAT Gateway; o
trade-off é um endereço público efêmero sem listener, mitigado pela ausência de
inbound e por não executar daemon.

O cache CVM usa `/tmp` e pode ser baixado em cada rodada. Não será introduzido
EFS ou S3 de artefatos nesta fase: tudo que precisa sobreviver vai ao Neon, e
arquivos em `reports/` tornam-se apenas export local opcional.

Alternativas consideradas:

- Uma Lambda para cada etapa: QuantLib e o conjunto de dependências aumentam
  empacotamento, timeout e diferenças de runtime; a sequência também exigiria
  mais coordenação.
- Step Functions: oferece visualização por etapa, mas uma única tarefa já
  precisa das dependências e transações do pipeline. Estado por etapa no Neon e
  logs estruturados entregam a auditabilidade necessária com menos recursos.
- ECS Service: mantém capacidade ociosa e não corresponde à carga em lote.

### 6. EventBridge Scheduler substitui todos os crons de produção

Schedules usam timezone `America/Sao_Paulo`, sem conversão UTC fixa:

- Intraday: cadência configurável dentro de 10:00-17:00 em dias úteis, flexible
  window desligada e idade máxima curta; o código continua sendo a autoridade
  final sobre sessão, feriados e vigência do calendário.
- Daily: padrão 17:10 em dias úteis, depois do fechamento, com janela de retry
  limitada para falha de entrega/inicialização.
- Alert: padrão 18:30, independente do daily, com política de retry própria.

O Scheduler considera sucesso ao aceitar `RunTask`, não ao container terminar.
Por isso retries automáticos cobrem apenas entrega/inicialização. Exit code e
estado final são observados por evento ECS/CloudWatch e pelo alerta independente;
uma falha interna não reinicia silenciosamente o pipeline nem repete requests de
provedor. Recuperação manual usa um identificador lógico explícito.

Os horários ficam em variáveis Terraform porque extensão de after-market ou
mudança de cadência afeta orçamento Brapi. A cadência inicial será a documentada
em `docs/PREGAO.md`, corrigindo antes do cutover a divergência atual entre os 14
disparos descritos e os 15 horários aparentes do timer.

Alternativas consideradas:

- GitHub Actions cron: não possui garantia operacional adequada e mistura
  automação da aplicação com CI/CD.
- EventBridge Rule em UTC: exige atualizar horário em mudanças de timezone e
  tem semântica de scheduler menos explícita.
- Recuperar intraday perdido: executaria avaliação fora do pregão sobre preço
  potencialmente velho.

### 7. Idempotência e progresso ficam no Neon

Uma migração ampliará o registro operacional para representar:

- chave única `(ambiente, tipo_fluxo, janela_logica)`;
- `execution_id` usado em logs, métricas e relatórios;
- status da execução e timestamps de início/heartbeat/fim;
- uma linha por etapa com tentativa, status, contagens, detalhe estruturado e
  erro sanitizado;
- vínculo do relatório e da notificação à execução.

O primeiro processo a inserir a chave lógica possui a execução; concorrentes
saem como duplicados antes de chamar provedores. Um evento entregue novamente
consulta o estado existente e não repete efeitos. Heartbeat permite ao alerta
classificar execução órfã. Não será mantido advisory lock de sessão porque o
endpoint pooled do Neon pode usar transaction pooling.

O fluxo grava a conclusão de cada etapa em transação própria. Falha do QuantLib
não volta a transação da decisão. O relatório determinístico passa a ter
persistência em tabela própria ou repositório durável equivalente no Neon; a
saída do agente continua em sua tabela. Notificação registra uma chave única por
relatório/canal para impedir envio duplicado.

Uma repetição automática depois de o container começar não é habilitada. Para
retomar manualmente uma execução parcialmente concluída, o comando exige modo
`resume` e pula etapas concluídas; etapas com chamadas externas em estado
ambíguo exigem decisão explícita do operador, em vez de presumir que podem ser
repetidas sem custo.

Alternativas consideradas:

- Lock somente no Scheduler: entrega é ao menos uma vez e não protege execução
  manual.
- Advisory lock no Postgres: não é confiável através de pool transacional e se
  perde no crash sem preservar o desfecho.
- DynamoDB para lock: adiciona uma segunda fonte de estado operacional sem
  necessidade para a escala de um usuário.

### 8. ETLs retornam resultado estruturado e política de estágio

Cada coletor retorna um objeto comum com fonte, estado, contagens e falhas por
ticker. CLIs continuam imprimindo resumo humano, mas o orquestrador consome o
objeto, não texto ou presença de logs. Os estados são:

- `sucesso`: todos os alvos previstos persistidos;
- `parcial`: parte persistida e parte falhou/ficou sem orçamento;
- `falha`: havia alvos e nenhum resultado utilizável por erro;
- `bloqueado`: provedor/feature indisponível no plano;
- `pulado`: universo vazio ou fonte opcional sem configuração.

A política versionada marca cotações e earnings como obrigatórios para as
respectivas decisões. Opções bloqueadas no plano e notícias não configuradas não
fazem o container mentir com sucesso completo: o pipeline pode continuar, mas
termina com ressalva/estado parcial e o relatório recebe o motivo. A política
será testada sem chamar provedores reais.

Alternativas consideradas:

- Tratar qualquer ticker como falha total: perderia o isolamento já existente.
- Manter somente warnings: CloudWatch e o orquestrador não distinguiriam uma
  fonte totalmente indisponível de uma rodada saudável.

### 9. Logs JSON, métricas EMF, eventos ECS e SNS formam a observabilidade

API e tarefas escrevem JSON em stdout. CloudWatch Log Groups têm retenção
configurável, inicialmente 30 dias, e nomes separados por ambiente/componente.
O orquestrador emite Embedded Metric Format para duração e estado por etapa; API
Gateway fornece request count, latência e 4xx/5xx. Eventos de ECS Task State
Change capturam container que não inicia ou sai diferente de zero.

Alarmes cobrem:

- falha ao lançar ou exit code não zero;
- ausência de conclusão e heartbeat órfão;
- `parcial`/`falha` de fonte obrigatória;
- 5xx e latência da API;
- erros de conexão Neon observados pela aplicação;
- gasto AWS real/projetado acima do orçamento.

SNS entrega alarmes operacionais e de orçamento por um canal independente do
agente/Anthropic. O alerta de negócio por SMTP é mantido porque consulta o Neon
e explica ausência/falha com contexto do pipeline. Logs nunca recebem objetos
Settings completos ou DSNs sem sanitização.

Alternativas consideradas:

- Somente tabela `execucao_pipeline`: não captura falha antes da primeira
  conexão com o banco nem falha de lançamento ECS.
- Somente CloudWatch: não é a fonte consultada pela interface e não preserva a
  relação de domínio entre avaliação e relatório.
- Serviço externo de APM: custo e complexidade não se justificam nesta fase.

### 10. Imagens e dependências são imutáveis e separadas por runtime

Haverá dois Dockerfiles multi-stage e um lock de dependências reproduzível:

- API: FastAPI, adaptador Lambda, psycopg, HTTP client e dependências dos
  endpoints.
- Operations: dependências core mais QuantLib, Anthropic e earnings providers.

Builds rodam em `linux/amd64`, executam testes de import e scanner da imagem,
publicam no ECR e promovem por digest. ECR mantém scan-on-push e lifecycle para
limitar imagens não referenciadas, sem remover digests de rollback recentes.

Alternativas consideradas:

- Uma imagem única: simplifica build, mas aumenta cold start e superfície de
  ataque da API com bibliotecas e segredos que ela não usa.
- Instalar opcionais ao iniciar: torna cada execução lenta, não reproduzível e
  dependente da disponibilidade do índice de pacotes.

### 11. GitHub Actions faz CI/CD, não operação

Workflows separados terão responsabilidades e permissões mínimas:

- `ci`: lint/formatação, testes unitários e integração com Postgres service,
  OpenSpec validate, build local das duas imagens e testes de import.
- `terraform-plan`: fmt/validate e plano sem segredos em pull request.
- `release`: aprovação do environment, credencial AWS OIDC, publicação por
  digest, migração serializada e apply/deploy.

`concurrency` do GitHub serializa releases por ambiente. A migração também
adquire lock no banco pela conexão direta administrativa, executa
`src.db.bootstrap` e bloqueia o deploy se falhar. O bootstrap continua
idempotente; não haverá rollback destrutivo automático de schema.

O deploy segue expand-and-contract: infraestrutura compatível primeiro,
migração aditiva, runtimes, frontend, smoke tests autenticados e só então
schedules. O contrato OpenAPI é exportado como artefato da release para o
repositório web gerar e validar tipos antes de publicar no S3/CloudFront.

Alternativas consideradas:

- Segredos AWS estáticos no GitHub: ampliam duração e impacto de vazamento.
- Migração no cold start da Lambda: permite concorrência e adiciona latência em
  requisição de usuário.
- Rebuild por ambiente: impede provar que produção recebeu o artefato testado.

## Risks / Trade-offs

- [O endpoint `execute-api` é publicamente descobrível] → Exigir access token no
  JWT authorizer antes da Lambda e repetir a validação no FastAPI; CORS não é
  considerado controle de acesso.
- [O bundle CloudFront é público] → Manter S3 privado por OAC, não embutir dado
  nem credencial e carregar todo estado protegido somente depois do login
  Cognito.
- [Perda do autenticador TOTP bloqueia o único usuário] → Manter runbook de
  recuperação administrativa e não habilitar SMS como fallback pago.
- [Cold starts podem aumentar latência] → Imagem de API mínima, concorrência
  reservada configurável, smoke test e alarme de p95; provisioned concurrency só
  será considerada após medição, pois cria custo fixo.
- [Lambda/Fargate podem saturar conexões Neon] → Endpoint pooled, limites de
  concorrência, timeouts e métrica de erro; migrações usam conexão administrativa
  separada e serializada.
- [Subnet pública expõe tarefa] → Nenhuma porta inbound, nenhum load balancer,
  security group sem ingress e processo em lote de curta duração. NAT Gateway
  permanece alternativa se o perfil de risco mudar.
- [Retry pode duplicar requests Brapi e notificações] → Scheduler só retenta
  lançamento, chave lógica única antes das integrações, etapas persistidas e
  notificação com chave idempotente.
- [Falha no meio de uma chamada externa deixa resultado ambíguo] → Não retomar
  automaticamente a etapa ambígua; exigir `resume` explícito e mostrar custo/
  efeito potencial ao operador.
- [ETL parcial passa despercebido apesar de exit code zero] → Resultado comum,
  política versionada, métrica por estado e alerta para fonte obrigatória.
- [Filesystem efêmero perde relatórios/cache] → Persistir relatórios no Neon;
  tratar arquivo como export opcional e cache CVM como descartável.
- [QuantLib ou Anthropic falha após decisão] → Transações independentes; decisão
  permanece, etapa contextual/notificação falha separadamente.
- [Custo cresce com cadência e logs] → Cadência parametrizada junto ao orçamento
  Brapi, retenção finita, lifecycle ECR e AWS Budget/SNS.
- [Terraform state expõe configuração de identidade] → Não criar usuário ou
  senha via Terraform; state criptografado contém somente IDs, issuer, client
  público e configuração não secreta.
- [Mudança simultânea em repositório web quebra interface] → Publicar OpenAPI,
  testar cliente tipado e validar PKCE/callback antes do cutover.
- [Cache CloudFront mantém shell antigo] → Publicar assets content-addressed,
  servir `index.html` sem cache e invalidar o shell depois do upload completo.
- [Agendadores legado e novo rodam juntos] → Criar schedules inicialmente
  desabilitados e usar checklist automático de cutover antes de habilitá-los.
- [Região `sa-east-1` pode ter preço maior] → Proximidade do Neon e residência
  atual simplificam latência/operação; Budget mede o custo real antes de cogitar
  outra região.

## Migration Plan

1. Confirmar AWS account, endpoint pooled Neon, limites de
   conexão e destinatários de alarme; criar bootstrap de state/OIDC.
2. Adicionar resultados estruturados dos ETLs, configuração por runtime,
   autenticação Cognito/JWT, handler Lambda, persistência operacional por etapa e
   persistência durável do relatório. Aplicar migrações primeiro no banco local.
3. Criar imagens, validar QuantLib/Anthropic e rodar toda a suíte contra Postgres
   descartável em CI.
4. Provisionar ECR, frontend S3/CloudFront, log groups, Secrets Manager sem
   valores, Cognito, rede, ECS, Lambda, API Gateway e schedules desabilitados.
5. Preencher segredos diretamente nos stores aprovados, publicar imagens por
   digest, executar migração serializada no Neon e criar administrativamente o
   único usuário Cognito sem registrar senha em state ou log.
6. Fazer smoke tests autenticados da API, incluindo rejeição sem JWT, CORS,
   leitura, escrita controlada e saúde com/sem banco.
7. Executar manualmente tarefas `intraday`, `daily` em modo seco/forçado e
   `alert`; verificar chave idempotente, estados parciais, logs, métricas, SNS e
   persistência após destruição da tarefa.
8. Coordenar `opcoes-ia-web`: gerar tipos do OpenAPI, implementar
   authorization-code+PKCE, publicar S3/CloudFront pela role OIDC própria e
   validar fluxo browser → Cognito → API.
9. Desabilitar o cron operacional do GitHub Actions e timers systemd de
   produção, registrar o estado anterior e habilitar EventBridge. Observar uma
   sessão intradiária e uma rodada diária completas.
10. Declarar cutover concluído somente após alarmes, orçamento, ausência de
    schedules duplicados e consulta do relatório hospedado estarem validados.

Rollback:

- Desabilitar schedules EventBridge primeiro para impedir novos efeitos.
- Restaurar digests e configuração Lambda/ECS anteriores por Terraform.
- Se o problema for apenas API/Cognito, manter pipeline novo, bloquear o app
  client e voltar temporariamente ao acesso local sem expor rota sem JWT.
- Não desfazer migração aditiva automaticamente. Runtimes anteriores devem
  permanecer compatíveis durante a janela de rollback.
- Reativar temporariamente systemd/GitHub cron somente por decisão manual,
  depois de confirmar que EventBridge está desabilitado e registrar o período
  para evitar duplicidade.
