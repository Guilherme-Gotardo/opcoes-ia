## Purpose

Manter o cadastro dos ativos que a carteira acompanha — a entidade de
referência de que cotações, opções e notícias dependem — sempre informada
por um humano, incluindo o identificador que liga o ativo às divulgações da
CVM.

## ADDED Requirements

### Requirement: Registro de um ativo acompanhado
O sistema SHALL permitir registrar um ativo informando ticker, nome e tipo,
e SHALL persistir esse registro como a entidade de referência que cotações,
opções e notícias passam a poder apontar.

O sistema SHALL NOT derivar, inferir ou buscar o nome do ativo a partir do
ticker ou de um provedor externo: o nome é informado por quem cadastra.

#### Scenario: Ativo novo é cadastrado
- **WHEN** o usuário registra um ativo informando ticker, nome e tipo
- **THEN** o ativo passa a existir no cadastro e a coleta de cotações para
  esse ticker deixa de ser rejeitada por ativo inexistente

#### Scenario: Nome não é inventado
- **WHEN** o usuário tenta registrar um ativo sem informar o nome
- **THEN** o sistema rejeita o registro, e SHALL NOT gravar um nome derivado
  do ticker ou obtido de outra fonte

### Requirement: Rejeição de cadastro inválido
O sistema SHALL rejeitar, com erro explícito que identifique o problema, um
cadastro de ativo cujos dados não sejam utilizáveis — e SHALL NOT ajustar,
completar ou reinterpretar a entrada para torná-la aceitável.

#### Scenario: Ticker vazio
- **WHEN** o usuário tenta registrar um ativo sem ticker
- **THEN** o sistema rejeita com mensagem que identifica o campo, sem gravar
  nada

#### Scenario: Tipo fora dos valores aceitos
- **WHEN** o usuário informa um tipo de ativo que o sistema não reconhece
- **THEN** o sistema rejeita informando o valor recebido e os valores
  aceitos

### Requirement: Correção de um ativo cadastrado
O sistema SHALL permitir corrigir os dados de um ativo já cadastrado sem
criar uma segunda entrada para o mesmo ticker, preservando as referências
existentes a ele.

#### Scenario: Recadastro do mesmo ticker corrige em vez de duplicar
- **WHEN** o usuário registra novamente um ticker já cadastrado, com nome
  diferente
- **THEN** o cadastro passa a refletir o novo nome, continua existindo uma
  única entrada para aquele ticker, e as cotações já coletadas continuam
  associadas a ele

### Requirement: Identificador para o dump da CVM
O sistema SHALL permitir associar ao ativo o identificador que o liga às
divulgações da CVM, e SHALL tratá-lo como opcional — um ativo sem esse
identificador continua utilizável para coleta de cotações.

Quando uma fonte de datas de resultado depender desse identificador e ele
não estiver cadastrado, o sistema SHALL sinalizar isso citando a ação que
resolve, em vez de tratar a ausência como "esse ativo não tem resultado".

#### Scenario: Ativo cadastrado sem o identificador
- **WHEN** um ativo é registrado sem o identificador da CVM
- **THEN** o cadastro é aceito e a coleta de cotações funciona normalmente
  para esse ticker

#### Scenario: Fonte que depende do identificador avisa como resolver
- **WHEN** a consolidação de datas de resultado consulta uma fonte que
  depende do identificador da CVM e o ativo não o tem cadastrado
- **THEN** o aviso emitido identifica o ativo e cita o comando de cadastro
  que resolve

### Requirement: Consulta dos ativos cadastrados
O sistema SHALL fornecer uma forma de listar os ativos cadastrados,
mostrando quais têm e quais não têm o identificador da CVM.

#### Scenario: Listagem distingue quem tem identificador
- **WHEN** o usuário lista os ativos cadastrados
- **THEN** a saída permite distinguir os ativos com identificador da CVM dos
  que estão sem ele

#### Scenario: Cadastro vazio
- **WHEN** o usuário lista os ativos e nenhum foi cadastrado
- **THEN** o sistema informa explicitamente que não há ativo cadastrado, em
  vez de devolver saída vazia sem explicação
