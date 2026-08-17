## ADDED Requirements

### Requirement: Acesso hospedado autenticado
Em produção, o sistema SHALL exigir JWT emitido pelo provedor de identidade
configurado antes de acessar qualquer endpoint protegido. A validação SHALL
ocorrer no gateway antes da invocação do runtime e novamente no limite da
aplicação, SHALL cobrir endpoints de leitura e escrita e SHALL NOT tratar CORS
como mecanismo de autenticação. O sistema SHALL permitir que a interface
estática seja carregada sem sessão, mas SHALL NOT expor dado protegido nem
executar escrita sem JWT válido.

#### Scenario: Usuário autorizado acessa pela interface publicada
- **WHEN** uma requisição apresenta JWT válido para o cliente configurado e
  origem CloudFront permitida
- **THEN** a API processa a requisição normalmente

#### Scenario: Requisição sem identidade
- **WHEN** uma requisição chega ao hostname da API sem credencial de identidade
  válida
- **THEN** o gateway a recusa antes de invocar a aplicação ou acessar dados

#### Scenario: Acesso direto tenta contornar o proxy
- **WHEN** uma requisição alcança a origem da API sem passar pelo hostname
  esperado ou com JWT destinado a outro cliente
- **THEN** a API recusa a requisição, mesmo que sua origem conste na política de
  CORS

#### Scenario: Interface carrega sem sessão
- **WHEN** um visitante abre o bundle estático sem sessão autenticada
- **THEN** nenhum dado de carteira é retornado e nenhuma escrita é aceita até a
  conclusão do login

#### Scenario: Origem de navegador não autorizada
- **WHEN** uma página de origem diferente da interface publicada tenta consumir
  a API pelo navegador
- **THEN** a requisição é recusada pela política de origem cruzada

#### Scenario: Desenvolvimento local explícito
- **WHEN** a aplicação roda em modo de desenvolvimento local configurado
  explicitamente
- **THEN** ela pode aceitar a origem local sem tornar esse modo o padrão do
  ambiente de produção

## REMOVED Requirements

### Requirement: Acesso restrito à máquina local
**Reason**: A dependência de `127.0.0.1` impede uso sem o computador pessoal
ligado, e a aplicação atual também contém endpoints de escrita que não podem ser
publicados sem identidade verificada.

**Migration**: Publicar a interface pelo CloudFront sobre origem S3 privada,
autenticar pelo provedor gerenciado, validar o JWT no gateway e na API e
restringir CORS à distribuição publicada. O modo local permanece apenas para
desenvolvimento explícito.
