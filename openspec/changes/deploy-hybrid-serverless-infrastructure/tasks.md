## 1. Parâmetros e guardrails de produção

- [x] 1.1 Registrar AWS account, prefixo Hosted UI, email do usuário administrativo, destinatários SNS, orçamento AWS e endpoint pooled do Neon sem incluir segredos no repositório.
- [x] 1.2 Confirmar os limites de conexão do plano Neon e transformar reserved concurrency da Lambda, CPU/memória Fargate e paralelismo operacional em parâmetros conservadores documentados.
- [x] 1.3 Conferir a cadência intradiária desejada contra o orçamento Brapi e corrigir a divergência entre os 14 disparos documentados e os 15 horários aparentes antes de codificar o schedule.
- [x] 1.4 Revisar e testar a matriz de variáveis e segredos mínimos para API/Cognito, fluxo intradiário, fluxo diário, alerta, migração e CI/CD.

## 2. Configuração, logs e resultados de coleta

- [x] 2.1 Separar a configuração global atual em configurações por runtime, mantendo `.env` local e impedindo que uma conexão de banco exija tokens não usados pelo processo.
- [x] 2.2 Implementar logging JSON com ambiente, componente, request/execution ID, etapa, resultado e duração, incluindo sanitização testada de DSN, tokens, chaves e senhas.
- [x] 2.3 Criar o modelo comum de resultado de coleta com estados `sucesso`, `parcial`, `falha`, `bloqueado` e `pulado`, contagens e detalhe por ticker.
- [x] 2.4 Adaptar o ETL de cotações para retornar o resultado comum sem perder isolamento por ticker, limite de orçamento ou resumo da CLI.
- [x] 2.5 Adaptar o ETL de candles para retornar o resultado comum para cada intervalo e distinguir universo vazio de falha.
- [x] 2.6 Adaptar o ETL de opções para classificar indisponibilidade de plano como `bloqueado` e erros reais como `falha`/`parcial`.
- [x] 2.7 Adaptar ETL de notícias e consolidação de earnings para distinguir fonte opcional não configurada, execução vazia e erro de provider.
- [x] 2.8 Implementar a política versionada que agrega fontes obrigatórias e opcionais no estado da etapa, com testes para sucesso, parcial, falha, bloqueio e skip.

## 3. Estado operacional durável

- [x] 3.1 Criar migração idempotente para chave lógica única por ambiente/fluxo/janela, execution ID, heartbeat, estado final e erro sanitizado da execução.
- [x] 3.2 Criar na mesma evolução de schema o registro por etapa/tentativa com status, timestamps, contagens e detalhe estruturado, preservando compatibilidade com `execucao_pipeline` existente.
- [x] 3.3 Criar persistência no Neon para o relatório determinístico e chave idempotente de notificação, vinculadas à execução e ao relatório do agente.
- [x] 3.4 Implementar repositórios transacionais para adquirir uma execução, detectar duplicata, atualizar heartbeat, concluir etapa e classificar órfã, com testes de concorrência no Postgres descartável.
- [x] 3.5 Implementar repositório do relatório durável e tornar a escrita em `reports/` um export local opcional, com teste que consulta o relatório após descartar o diretório temporário.
- [x] 3.6 Implementar reserva/conclusão idempotente da notificação para impedir reenvio do mesmo relatório/canal.

## 4. Orquestrador operacional

- [x] 4.1 Criar uma CLI operacional única com comandos `intraday`, `daily` e `alert`, execution ID propagado e exit codes coerentes com o estado final.
- [x] 4.2 Migrar o fluxo intradiário para o orquestrador, preservando abertura anterior ao trabalho, calendário que falha alto, ordem cotação → avaliação e comportamento de `--forcar`.
- [x] 4.3 Separar o disparo do enriquecimento quantitativo da transação da avaliação para que apareça como etapa explícita sem virar gate nem import de topo em `strategy/covered.py`.
- [x] 4.4 Compor o fluxo diário na ordem coleta, earnings, avaliação, QuantLib, relatório determinístico, relatório Anthropic e notificação, persistindo cada conclusão antes da próxima etapa.
- [x] 4.5 Adaptar o alerta independente para o novo modelo de execução e cobrir ausência, falha, órfã e indisponibilidade do Neon sem depender do agente.
- [x] 4.6 Implementar rejeição de execução lógica duplicada antes de chamadas externas e testes concorrentes que provem uma única aquisição.
- [x] 4.7 Implementar `resume` explícito que pula etapas concluídas e recusa automaticamente etapa externa em estado ambíguo, com testes de crash/reentrada.
- [x] 4.8 Testar que falha de QuantLib ou SMTP não remove decisão/relatório persistido e que o agente recebe somente vereditos já calculados.

## 5. FastAPI em Lambda e autenticação

- [x] 5.1 Adicionar o adaptador ASGI e um handler Lambda que reutilize a aplicação FastAPI sem alterar o entrypoint Uvicorn de desenvolvimento.
- [x] 5.2 Implementar validação de access token Cognito com assinatura, issuer, client, expiração, `token_use`, escopo e cache limitado das chaves públicas.
- [x] 5.3 Aplicar autenticação Cognito em todas as rotas de produção, inclusive POST, deixando somente preflight e sinais de saúde deliberadamente classificados.
- [x] 5.4 Restringir CORS em produção ao hostname CloudFront provisionado, preservando a origem local somente no modo de desenvolvimento explícito.
- [x] 5.5 Criar sinais separados de liveness e dependência Neon que não escrevem nem disparam ETL/avaliação.
- [x] 5.6 Adaptar testes para access token Cognito válido, ausente, expirado, client/issuer/escopo incorretos, bypass direto, POST protegido, preflight e origem recusada.
- [x] 5.7 Exportar o OpenAPI com o contrato de autenticação Cognito e verificar que nenhuma rota de execução operacional foi adicionada à API pública.

## 6. Imagens reproduzíveis

- [x] 6.1 Introduzir lock reproduzível de dependências separado entre runtime API e operacional, removendo ferramentas de teste das dependências de produção.
- [x] 6.2 Criar Dockerfile multi-stage `linux/amd64` mínimo para Lambda/API, sem segredos e com teste local do handler.
- [x] 6.3 Criar Dockerfile multi-stage para Fargate com QuantLib, Anthropic e providers opcionais instalados no build, usuário sem privilégio e `/tmp` gravável.
- [x] 6.4 Adicionar testes de import, smoke tests dos três comandos e inspeção que prove ausência de credenciais/cópia de `.env` nas duas imagens.
- [x] 6.5 Configurar scan das imagens e política de retenção que preserve digests recentes necessários para rollback.

## 7. Bootstrap Terraform e identidade de CI

- [x] 7.1 Criar `infra/bootstrap` para bucket S3 criptografado/versionado com lock de state e documentar o bootstrap único e a migração para backend remoto.
- [x] 7.2 Atualizar as roles OIDC para incluir uma role exclusiva de publicação confiada somente ao `opcoes-ia-web`, preservando separação por plano, imagens, frontend, migração e deploy.
- [x] 7.3 Introduzir os módulos Cognito e frontend S3/CloudFront com providers travados, tags comuns, nenhuma dependência Cloudflare e nenhum valor secreto em state/output.
- [x] 7.4 Adaptar verificações de `terraform fmt`, `validate` e segurança/IAM à arquitetura Cognito sem perder os guardrails existentes.

## 8. Registro, segredos e runtimes AWS

- [x] 8.1 Provisionar repositórios ECR separados para API e operações, com scan-on-push e lifecycle compatível com rollback por digest.
- [x] 8.2 Provisionar referências/containers de Secrets Manager por runtime e IAM de leitura mínima, sem criar valores secretos via Terraform.
- [x] 8.3 Adaptar a Lambda por digest para receber issuer, client e escopo Cognito não secretos, preservando reserved concurrency, timeout, memória e log group.
- [x] 8.4 Adaptar API Gateway HTTP API para o endpoint regional `execute-api`, integração proxy e JWT authorizer Cognito, sem ACM, custom domain ou DNS.
- [x] 8.5 Provisionar VPC enxuta, duas subnets públicas, security group sem ingress e cluster/definição Fargate com public IP e somente saída.
- [x] 8.6 Revalidar por plano Terraform e teste automatizado que a troca para Cognito não introduz segredo em state nem integração ou permissão de corretora.
- [x] 8.7 Provisionar bucket S3 privado e distribuição CloudFront com OAC, HTTPS, fallback de SPA, cache explícito e outputs de domínio/bucket/distribution ID.
- [x] 8.8 Restringir a bucket policy à distribuição exata e provar por teste que o endpoint S3 não é público.

## 9. Cognito e acesso publicado

- [x] 9.1 Provisionar Cognito User Pool com self-signup desabilitado, email como identidade, TOTP obrigatório e proteção adequada contra exclusão acidental.
- [x] 9.2 Adaptar Hosted UI e app client público sem secret para authorization code com PKCE, callback `/auth/callback` e logout no hostname CloudFront.
- [x] 9.3 Provisionar resource server/escopo da API, JWT authorizer e issuer/client/escopo usados pela validação em profundidade no runtime.
- [ ] 9.4 Documentar criação e recuperação administrativa do único usuário fora do Terraform e validar login, MFA, anonimato, client/escopo incorretos e acesso direto à origem.

## 10. EventBridge e semântica de execução

- [x] 10.1 Provisionar Scheduler Group, role mínima de `ecs:RunTask`/`iam:PassRole` e destinos ECS para `intraday`, `daily` e `alert`.
- [x] 10.2 Configurar schedules em `America/Sao_Paulo`, inicialmente desabilitados, com flexible window, idade máxima e retries próprios para cada fluxo.
- [x] 10.3 Configurar intraday sem recuperação fora da janela, daily às 17:10 e alerta independente às 18:30, mantendo horários como variáveis revisáveis.
- [x] 10.4 Criar captura de ECS Task State Change para falha de launch/stop antes ou fora do registro Neon.
- [x] 10.5 Testar em infraestrutura descartável ou execução manual que entrega repetida usa a mesma janela lógica e não inicia segunda coleta.

## 11. CloudWatch, alarmes e custo

- [x] 11.1 Provisionar log groups separados com retenção finita e confirmar ingestão dos campos JSON da API e das tarefas.
- [x] 11.2 Emitir métricas EMF para duração/estado de execução, etapa e fonte, incluindo parcial, falha, bloqueio e erro de conexão Neon.
- [x] 11.3 Criar alarmes para launch/exit Fargate, ausência de conclusão, heartbeat órfão, fonte obrigatória falha, API 5xx/latência e falha de conexão observada.
- [x] 11.4 Provisionar SNS e subscriptions de alarme independentes de Anthropic/SMTP, validando uma notificação de teste.
- [x] 11.5 Revalidar AWS Budget real/projetado, tags de custo e estimativa mensal incluindo S3/CloudFront.

## 12. CI/CD e migração controlada

- [x] 12.1 Criar workflow `ci` com Postgres service descartável, variável `DATABASE_URL` explícita, suíte completa, OpenSpec strict validate e builds locais das imagens.
- [x] 12.2 Criar workflow de Terraform plan em pull request, usando OIDC de leitura/plano e publicando o plano revisável sem segredos.
- [x] 12.3 Criar workflow de release aprovado por environment que publique as duas imagens uma vez, obtenha digests e os promova sem rebuild.
- [x] 12.4 Serializar releases por environment e adicionar gate de migração que use conexão administrativa, lock de banco e `src.db.bootstrap` antes do deploy.
- [x] 12.5 Bloquear atualização de Lambda/ECS quando migração, scan, testes de import ou smoke test falhar, preservando os digests anteriores.
- [x] 12.6 Publicar OpenAPI como artefato versionado e documentar o gate coordenado para tipos, login PKCE e build do `opcoes-ia-web` contra os outputs AWS.
- [x] 12.7 Remover o cron operacional de `.github/workflows/daily-etl.yml`, mantendo GitHub Actions exclusivamente em funções de CI/CD.
- [ ] 12.8 Criar no `opcoes-ia-web` workflow OIDC que faz lint/build, publica assets no S3 com política de cache e invalida CloudFront somente depois do upload completo.

## 13. Validação, cutover e operação

- [x] 13.1 Aplicar todas as migrações no Postgres descartável e executar testes de concorrência, idempotência, persistência, falha parcial e rollback de aplicação.
- [x] 13.2 Provisionar produção com schedules desabilitados, preencher segredos e criar o usuário Cognito fora do Terraform, validando que imagens/state/logs não expõem valores sensíveis.
- [ ] 13.3 Executar smoke tests Cognito da API, incluindo login+TOTP, leitura, uma escrita controlada, rejeição sem token, CORS, liveness, Neon indisponível simulado e OpenAPI.
- [x] 13.4 Executar manualmente `intraday`, `daily` e `alert`, validar logs/CloudWatch/SNS, destruir as tasks e confirmar que execução e relatórios permanecem no Neon.
- [ ] 13.5 Coordenar login PKCE, callback, publicação S3/CloudFront e checagem tipada no `opcoes-ia-web` antes de liberar o acesso de produção.
- [ ] 13.6 Desabilitar e registrar os timers systemd de produção, verificar ausência de cron legado e somente então habilitar os schedules EventBridge.
- [ ] 13.7 Observar uma sessão intradiária e uma rodada diária completas, validar orçamento Brapi, alarmes, ausência de duplicatas e alerta independente.
- [x] 13.8 Documentar runbooks de deploy, recuperação do usuário/TOTP Cognito, rotação de segredo, execução manual/resume, diagnóstico por execution ID, rollback e reativação emergencial sem dois agendadores.
- [x] 13.9 Atualizar `docs/PREGAO.md`, runbooks, `.env.example`, documentação da API e a seção de estado do `CLAUDE.md` com Cognito, S3/CloudFront e limitações realmente validadas.
