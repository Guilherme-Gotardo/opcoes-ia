## Purpose

Executar a API e os trabalhos operacionais em infraestrutura sob demanda, sem
depender de computador pessoal ou servidor permanentemente ligado.

## ADDED Requirements

### Requirement: Frontend estático hospedado na AWS
O sistema SHALL disponibilizar o bundle da interface por uma distribuição AWS
HTTPS e SHALL manter sua origem de objetos sem acesso público direto. Rotas do
SPA SHALL carregar o shell da aplicação sem depender de servidor residente ou
de plataforma de hospedagem externa à AWS.

#### Scenario: Usuário abre uma rota interna diretamente
- **WHEN** o usuário acessa `/auth/callback` ou outra rota do SPA pelo hostname
  publicado
- **THEN** a distribuição retorna o shell da aplicação e o roteador cliente
  processa a rota

#### Scenario: Acesso direto ao bucket
- **WHEN** um cliente tenta ler um objeto pelo endpoint público do armazenamento
- **THEN** o acesso é recusado e somente a distribuição autorizada lê a origem

#### Scenario: Bundle carrega sem sessão
- **WHEN** um visitante abre a distribuição sem sessão Cognito
- **THEN** os arquivos estáticos carregam, mas nenhum dado protegido é retornado
  pela API

### Requirement: API disponível sob demanda
O sistema SHALL disponibilizar a aplicação HTTP em infraestrutura serverless
capaz de iniciar sob demanda e SHALL NOT depender de processo residente no
computador do usuário.

#### Scenario: Computador pessoal desligado
- **WHEN** o computador pessoal do usuário está desligado e uma requisição
  autenticada chega à API publicada
- **THEN** a API processa a requisição usando a infraestrutura hospedada

#### Scenario: Período sem requisições
- **WHEN** não há requisições à API
- **THEN** o sistema não exige instância de aplicação permanentemente ligada

### Requirement: Trabalhos operacionais usam execução efêmera
O sistema SHALL executar coleta, consolidação de earnings, avaliação,
enriquecimento quantitativo, relatório e alerta em compute efêmero, encerrado ao
final de cada trabalho.

#### Scenario: Trabalho operacional concluído
- **WHEN** um trabalho agendado termina com sucesso ou falha
- **THEN** sua capacidade de compute é encerrada sem depender de intervenção
  no computador do usuário

### Requirement: Neon permanece como fonte de verdade
O sistema SHALL usar o Neon como armazenamento durável único para carteira,
dados de mercado, execuções, sugestões e relatórios persistidos. O sistema
SHALL NOT depender do filesystem efêmero de Lambda ou tarefa operacional para
preservar um artefato necessário depois da execução.

#### Scenario: Tarefa é substituída após gerar relatório
- **WHEN** a tarefa que gerou um relatório é encerrada e seu filesystem é
  descartado
- **THEN** o relatório continua consultável a partir do Neon

#### Scenario: Nova instância atende a API
- **WHEN** uma nova instância serverless atende uma requisição
- **THEN** ela lê o estado vigente do Neon, sem depender de cache local de uma
  instância anterior

### Requirement: Conexões serverless são limitadas
O sistema SHALL usar a interface pooled do Neon e SHALL limitar a concorrência
da API e das tarefas operacionais de forma compatível com o limite de conexões
do banco.

#### Scenario: Pico de requisições à API
- **WHEN** várias requisições chegam durante a inicialização simultânea de
  instâncias serverless
- **THEN** a concorrência é limitada e as conexões usam o endpoint pooled, sem
  abrir quantidade não controlada de conexões diretas ao Neon

### Requirement: Segredos são injetados em runtime
O sistema SHALL armazenar credenciais fora do código, das imagens e dos planos
de infraestrutura legíveis, e SHALL entregar a cada runtime somente os segredos
necessários para sua função. O sistema SHALL NOT registrar valores secretos em
logs.

#### Scenario: Imagem publicada no registro
- **WHEN** uma imagem de aplicação é construída e publicada
- **THEN** ela não contém URL credenciada do banco, tokens de provedores, chave
  Anthropic nem credenciais SMTP

#### Scenario: API inicia sem credencial do agente
- **WHEN** a API serverless é iniciada
- **THEN** ela recebe somente as credenciais necessárias aos endpoints que
  serve e não precisa da chave Anthropic ou da credencial SMTP

### Requirement: Runtimes não executam ordens
Nenhuma identidade, imagem ou tarefa criada para a infraestrutura hospedada
SHALL possuir integração ou permissão para enviar ordens a uma corretora.

#### Scenario: Estratégia produz oportunidade
- **WHEN** a avaliação hospedada aprova uma estratégia
- **THEN** o sistema persiste uma sugestão pendente de revisão humana e não
  envia ordem de negociação
