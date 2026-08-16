## Decisão 1: `strike` vira campo obrigatório, em vez de guarda pontual

A correção mínima seria só mover a checagem de `strike is None` para antes
do cálculo da garantia. Isso resolveria o `TypeError` e deixaria o segundo
defeito de pé — o covered call continuaria aprovando exposição zero com
strike nulo.

`strike` já era obrigatório de FATO nos dois ramos: garantia no put,
notional descoberto no call. A lista existia justamente para nomear esses
campos, e ele estava fora dela por omissão. Entrando na lista, os dois
caminhos passam a falhar do mesmo jeito e pelo mesmo motivo.

A guarda no ramo do put continua necessária porque aquele bloco roda ANTES
da checagem de obrigatórios — é pré-requisito estrutural, não critério de
mercado. Duas guardas, portanto, mas por razões diferentes e ambas
documentadas no ponto de uso.

## Decisão 2: janela própria para o dado da opção, herdando a da cotação

Três caminhos possíveis: reusar `cotacao_frescor_maximo_horas` direto,
criar um parâmetro independente com padrão próprio, ou criar um parâmetro
que herda o da cotação quando omitido.

O primeiro impede apertar a opção sem apertar a ação — e são grandezas com
ritmos de envelhecimento diferentes: o preço de uma ação sobrevive a um fim
de semana, mas delta e IV rank mudam com o tempo até o vencimento mesmo sem
nenhum negócio novo.

O segundo mudaria a postura de risco de quem já usa o sistema no momento em
que a correção fosse aplicada, sem ninguém pedir.

O terceiro é o adotado: quem não configurar nada continua exatamente onde
estava, e quem quiser uma janela mais curta para opção configura só ela.

## Decisão 3: expor o viés de prazo, não corrigi-lo

Normalizar `premio_pct` por prazo mudaria quais sugestões saem — é mudança
de critério de estratégia, e critério é do usuário (regra 2 do projeto),
não de quem está consertando um bug ao lado.

O que a revisão apontou de fato é que o viés era **invisível**: nada no
relatório dizia que 45 dias e 10 dias competiam pelo mesmo mínimo. Então a
correção é de visibilidade — o equivalente mensal aparece no detalhe do
critério — mais um critério ADICIONAL opcional para quem decidir barrar por
rendimento normalizado. Sem configuração, nada muda.

Rejeitado: trocar o limiar bruto pelo mensal, mesmo "sendo mais correto".
Isso alteraria a carteira sugerida de alguém sem decisão explícita.

## Decisão 4: a ressalva viaja com o número que ela qualifica

O aviso de patrimônio parcial existia como `log.warning` no início da
execução — longe do desfecho, e invisível para quem lê o resultado depois.

A ressalva passa a compor o DETALHE do critério de exposição, que é o número
distorcido pelo denominador incompleto. Quem audita a reprovação lê, na
mesma linha, que a exposição real é menor ou igual à exibida e quais tickers
faltaram. O log continua, agora dizendo também que o efeito atinge todas as
posições — não só as sem cotação.

## Decisão 5: idade da opção viaja no dicionário, não é recalculada em `avaliar`

`avaliar()` é função pura e precisa continuar testável sem banco. Passar
`coletado_em` e deixar a função calcular a idade exigiria injetar "agora"
nela, tornando o teste dependente de relógio.

`_opcoes_call_candidatas` calcula `idade_horas` na leitura (onde já tem o
`agora` da execução) e a envia junto. `avaliar` compara com o limite e não
sabe que horas são. A conta em si vive em `idade_em_horas`, público em
`market/valuation.py`, para cotação e opção não divergirem no tratamento de
fuso — que é exatamente onde esse tipo de bug mora.

Consequência assumida: `idade_horas` passou a ser chave obrigatória do
dicionário de opção, e ausência dela é dado insuficiente. "Não sei se o dado
ainda vale" não é permissão para usá-lo.
