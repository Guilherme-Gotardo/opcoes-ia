## Purpose

Entregar por e-mail o relatório diário e o alerta operacional de ausência de
execução, a partir de uma identidade de envio verificada e de uma credencial
que só pode enviar, para que uma falha silenciosa do pipeline chegue ao
titular sem depender do computador pessoal.

## ADDED Requirements

### Requirement: Identidade de envio é verificada e declarada
O sistema SHALL enviar e-mail operacional a partir de um endereço remetente
previamente verificado no provedor de envio, declarado na infraestrutura como
código. O sistema SHALL NOT enviar a partir de remetente não verificado.

#### Scenario: Remetente ainda não verificado
- **WHEN** a identidade de envio existe mas a verificação não foi concluída
- **THEN** a tentativa de envio falha de forma explícita e registrada, e
  nenhuma mensagem é entregue como se tivesse sido enviada

#### Scenario: Remetente verificado
- **WHEN** a identidade está verificada e o canal configurado
- **THEN** o relatório diário e o alerta operacional são entregues ao
  destinatário configurado

### Requirement: Credencial de envio é de envio-apenas
A credencial usada para entregar e-mail SHALL permitir somente o envio pela
identidade verificada do projeto e SHALL NOT conceder leitura de mensagens,
gestão de identidades, alteração de configuração do provedor ou qualquer
permissão fora do envio. A credencial SHALL ser legível apenas pelo runtime
operacional.

#### Scenario: Credencial usada fora do escopo
- **WHEN** a credencial de envio tenta uma operação que não seja enviar pela
  identidade verificada
- **THEN** a operação é negada pela política associada à identidade

#### Scenario: Runtime da API inicia
- **WHEN** o runtime que serve a API HTTP é iniciado
- **THEN** ele não recebe a credencial de envio de e-mail, que é entregue
  somente ao runtime operacional

### Requirement: Canal ausente não é confundido com canal quebrado
O sistema SHALL tratar "canal de e-mail não configurado" como estado distinto
de "canal configurado que falhou". Quando nenhum endereço de destino e nenhum
servidor estiverem configurados, o relatório SHALL permanecer disponível pelas
demais superfícies e a ausência de envio SHALL ser registrada como aviso, não
como falha. A infraestrutura SHALL NOT publicar configuração parcial: um
destinatário SHALL NOT ser injetado no runtime sem o servidor de envio
correspondente.

#### Scenario: Nenhuma configuração de e-mail publicada
- **WHEN** o inventário de infraestrutura não declara servidor de envio
- **THEN** o runtime operacional inicia sem destinatário e sem servidor, e o
  fluxo diário conclui registrando que a notificação não está configurada

#### Scenario: Configuração pela metade
- **WHEN** apenas um entre servidor e destinatário está configurado no runtime
- **THEN** a tentativa de envio falha de forma explícita, sem entregar
  mensagem e sem seguir como se o canal estivesse íntegro

#### Scenario: Destinatário de orçamento não vira destinatário de negócio
- **WHEN** o endereço usado para alarmes e orçamento da conta de nuvem está
  declarado
- **THEN** ele não é injetado sozinho como destinatário do canal de e-mail do
  pipeline

### Requirement: Entrega permanece determinística e fora do modelo
O envio de e-mail SHALL ser executado pelo processo operacional depois de o
conteúdo estar persistido, e SHALL NOT ser exposto como ferramenta ao modelo
de linguagem. O modelo SHALL NOT decidir se envia, para quem envia ou quantas
vezes envia.

#### Scenario: Agente compõe o relatório
- **WHEN** o agente termina de compor o texto do relatório do dia
- **THEN** o envio é decidido e executado pelo processo, depois da
  persistência, e o conjunto de ferramentas oferecido ao modelo não inclui
  envio de mensagem

#### Scenario: Falha de entrega após persistência
- **WHEN** o conteúdo já foi persistido e a entrega falha
- **THEN** o conteúdo permanece consultável e a etapa de notificação termina
  como falha explícita, sem nova tentativa que duplique a mensagem já
  reservada

### Requirement: Alerta de ausência chega por caminho próprio
O alerta operacional de ausência, falha ou execução órfã SHALL usar o canal de
e-mail sem depender da execução do pipeline que ele vigia nem da composição
feita pelo modelo.

#### Scenario: Pipeline diário não executou
- **WHEN** a verificação posterior ao fechamento não encontra execução
  concluída no dia
- **THEN** a mensagem de alerta é entregue ao destinatário configurado citando
  o motivo, sem depender do fluxo ausente

#### Scenario: Banco indisponível na verificação
- **WHEN** a verificação não consegue consultar o log de execução
- **THEN** a própria indisponibilidade vira motivo de alerta entregue pelo
  canal de e-mail
