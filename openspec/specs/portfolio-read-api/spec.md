## Purpose

Expor por HTTP, para consumo de uma interface própria, os dados de carteira,
cotações e sugestões que hoje só existem em linha de comando e no relatório
diário — sem duplicar nenhuma regra de decisão e sem disparar execução.

## Requirements

### Requirement: Leitura da carteira valorizada a mercado
O sistema SHALL expor a carteira atual com cada posição aberta, seu preço
médio de entrada, seu preço de mercado, o momento da cotação usada e o valor
resultante, além do patrimônio total.

Os valores SHALL vir da mesma função de domínio que o relatório diário
consome, e o sistema SHALL NOT recalcular a valorização por conta própria.

Quando alguma posição ficar sem cotação utilizável, a resposta SHALL
identificar quais posições ficaram de fora e SHALL sinalizar que o
patrimônio informado é parcial — nunca apresentar um total que aparente
cobrir a carteira inteira.

#### Scenario: Carteira inteira valorizada
- **WHEN** a interface consulta a carteira e todas as posições têm cotação
  dentro da janela de frescor
- **THEN** a resposta traz cada posição com preço médio e preço de mercado, o
  patrimônio total, e a indicação de que ele é completo

#### Scenario: Posição sem cotação utilizável
- **WHEN** uma posição não tem cotação dentro da janela de frescor
- **THEN** a resposta identifica essa posição como não valorizada, informa o
  motivo, e marca o patrimônio como parcial, sem inventar valor de mercado
  para ela

#### Scenario: Carteira vazia
- **WHEN** não há posição aberta
- **THEN** a resposta é bem-sucedida e representa carteira vazia
  explicitamente, em vez de erro

### Requirement: Leitura das cotações vigentes
O sistema SHALL expor a cotação mais recente de cada ativo acompanhado,
incluindo o momento da coleta, para que a interface possa mostrar a idade do
dado.

#### Scenario: Cotação com idade visível
- **WHEN** a interface consulta as cotações
- **THEN** cada entrada traz o preço e o momento da coleta, permitindo à
  interface distinguir dado fresco de dado velho

#### Scenario: Ativo sem cotação coletada
- **WHEN** um ativo acompanhado nunca teve cotação coletada
- **THEN** a resposta o representa como sem cotação, em vez de omiti-lo em
  silêncio

### Requirement: Leitura das sugestões registradas
O sistema SHALL expor as sugestões persistidas, cada uma com seu ativo,
tipo de operação, strike, vencimento, prêmio estimado, status e o snapshot
dos critérios avaliados que a justifica.

Cada sugestão exposta SHALL carregar a indicação de que está pendente de
revisão humana, e a resposta SHALL NOT conter linguagem que possa ser
confundida com ordem executada ou confirmada.

#### Scenario: Sugestão inclui a justificativa numérica
- **WHEN** a interface consulta as sugestões
- **THEN** cada sugestão vem acompanhada do valor e do veredito de cada
  critério avaliado, e da base de valorização usada

#### Scenario: Nenhuma sugestão registrada
- **WHEN** não há sugestão persistida para o período consultado
- **THEN** a resposta representa a ausência explicitamente, em vez de erro

#### Scenario: Nenhuma sugestão aparece como executada
- **WHEN** a interface consulta as sugestões
- **THEN** todas vêm com status pendente de revisão humana, e nenhuma é
  apresentada como executada ou confirmada

### Requirement: Leitura dos motivos de não-sugestão
O sistema SHALL expor o desfecho registrado da execução mais recente da
avaliação, com os motivos pelos quais opções não geraram sugestão, por
ativo, incluindo quantas foram afetadas em cada motivo.

A resposta SHALL informar o momento da execução que produziu esse desfecho,
para que a interface possa dizer de quando é o que mostra — se a avaliação
não rodou hoje, o registro mais recente é de outro dia.

O sistema SHALL distinguir reprovação em critério de ausência de dado, e
SHALL NOT apresentar ausência de sugestão sem o motivo quando ele estiver
registrado.

#### Scenario: Motivos acompanham a ausência de sugestão
- **WHEN** a interface consulta o desfecho de um dia em que nenhuma opção
  passou
- **THEN** a resposta traz, por ativo, cada motivo e quantas opções foram
  afetadas

#### Scenario: Momento da execução acompanha o desfecho
- **WHEN** a interface consulta o desfecho
- **THEN** a resposta informa quando aquela avaliação foi executada

#### Scenario: Nenhuma execução registrada
- **WHEN** não há desfecho registrado para o período consultado
- **THEN** a resposta representa isso explicitamente, em vez de erro ou de
  lista vazia sem contexto

### Requirement: A API não dispara execução
O sistema SHALL restringir esta superfície a leitura. Ela SHALL NOT disparar
coleta de dados, avaliação de estratégia, consolidação de datas de resultado
ou geração de relatório, e SHALL NOT gravar em nenhuma tabela.

#### Scenario: Consulta não altera estado
- **WHEN** qualquer endpoint desta superfície é chamado
- **THEN** nenhuma linha é criada, alterada ou removida no banco, e nenhum
  processo de coleta ou avaliação é iniciado

### Requirement: Nenhuma regra de decisão na API
O sistema SHALL obter os valores expostos das funções de domínio existentes,
e SHALL NOT implementar, duplicar ou reinterpretar critério de estratégia,
cálculo de exposição, valorização ou risco de resultado.

#### Scenario: Valores coincidem com os do relatório
- **WHEN** a interface consulta a carteira e o relatório diário é gerado para
  o mesmo momento
- **THEN** patrimônio, valor por posição e exposição por ativo são os mesmos
  nos dois, por virem da mesma função de domínio

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

### Requirement: Contrato publicado em formato consumível por cliente tipado
O sistema SHALL publicar a descrição do contrato desta superfície em formato
padrão, de modo que o cliente possa derivar seus tipos dela em vez de
mantê-los por conta própria.

#### Scenario: Descrição do contrato disponível
- **WHEN** o contrato é solicitado à API no ar
- **THEN** a descrição retornada cobre todos os endpoints e os formatos de
  resposta desta superfície

#### Scenario: Mudança de campo é detectável no cliente
- **WHEN** um campo de resposta muda de nome ou tipo na API
- **THEN** o contrato publicado reflete a mudança, permitindo ao cliente
  detectá-la na sua checagem de tipos em vez de em tempo de execução
