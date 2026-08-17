# O agente de relatório (Fases 3 e 4)

Compõe o relatório do dia a partir do que os módulos determinísticos
apuraram, e o entrega em `reports/`, no banco, na tela e opcionalmente por
e-mail.

```bash
python -m src.agente.ferramentas   # mostra as ferramentas (sem token)
python -m src.agente.verificar     # chamada de teste: buscou? citou a fonte?
python -m src.agente.relatorio --seco   # mostra o prompt e para
python -m src.agente.relatorio     # compõe e entrega
```

## As peças, e onde o LLM entra

```
dados.py    junta o que os módulos determinísticos decidiram   [sem LLM]
prompt.py   monta a instrução e os guarda-corpos               [sem LLM]
relatorio.py chama o modelo e persiste                         [COM LLM]
entrega.py  escreve em reports/                                [sem LLM]
```

O texto é a única coisa que vem do modelo. Todo número que ele cita precisa
estar no insumo, e o prompt cobra isso.

**Falha do agente não invalida nada.** Sugestões, desfecho e enriquecimento
já estão gravados quando ele roda; sem chave, sem rede ou com recusa do
modelo, o que se perde é o texto.

## O que o agente recebe — e o que não recebe

Entra o **veredito** de cada critério: aprovado ou reprovado, com o valor
comparado e o limiar que valia. Não entra o dado de mercado cru que
permitiria refazer a conta.

A diferença é o guarda-corpo central. Com IV rank, delta e preço soltos, o
modelo *poderia* reavaliar — e um modelo que pode reavaliar eventualmente
reavalia, discorda, e escreve "esta parece elegível apesar de reprovada".
Recebendo só o veredito e os números que o sustentaram, discordar exigiria
contradizer um dado explícito na frente dele.

Os guarda-corpos do prompt são cobrados por teste, trecho a trecho
(`GUARDA_CORPOS` em `prompt.py`): não reavalia critério, não sugere ordem,
não estima preço-alvo, não usa busca web para número, sempre cita a fonte,
nunca trata nulo como zero. Guarda-corpo que ninguém testa some no primeiro
refactor — e some em silêncio, porque o relatório continua saindo.

### A regra que a busca web criou

O agente tem busca web. Se ele procurar "cotação de PETR4", vai achar — e
passará a existir um **terceiro** número de preço, competindo com o do ETL e
com o do modelo, sem procedência no banco. A regra 1 do projeto ("dado nunca
é lembrado ou estimado pelo agente") só sobrevive com a busca restrita a
contexto narrativo: fato relevante, guidance, notícia. Preço, grega e IV vêm
do insumo, sempre.

## Agendamento: por que timer próprio

`opcoes-ia-pregao.timer` dispara **14 vezes** por dia útil. Encadear o agente
ali seria 14 chamadas de LLM por dia para produzir um texto que resume o
*dia*. `opcoes-ia-relatorio.timer` roda **uma vez**, às 17h30 — meia hora
depois do fechamento, com o dia inteiro já gravado.

Diferença deliberada entre os dois timers: o do relatório tem
`Persistent=true`, o do pregão não. São casos opostos — uma avaliação
intradiária perdida não deve rodar de madrugada sobre preço velho, mas um
relatório perdido ainda vale, porque descreve um dia que já aconteceu.

```bash
cp deploy/systemd/opcoes-ia-relatorio.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now opcoes-ia-relatorio.timer
```

Para entrega por e-mail, acrescente `SMTP_HOST`, `SMTP_TO` e, se necessário,
`SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` e `SMTP_STARTTLS` ao
`~/.config/opcoes-ia/env`. O envio é feito por `src/agente/notificar.py`,
depois que o script grava o relatório; o modelo não recebe ferramenta de
notificação. Sem SMTP, arquivo, banco e interface continuam disponíveis e o
journal registra que a entrega externa está desativada.

## Entrega

Dois arquivos por dia, de propósito:

| Arquivo | O que é | LLM? |
|---|---|---|
| `reports/AAAA-MM-DD.md` | o que o sistema apurou | não |
| `reports/AAAA-MM-DD-agente.md` | uma leitura sobre aquilo | sim |

Fundi-los faria a interpretação herdar a autoridade da apuração, e daqui a
seis meses ninguém saberia qual parágrafo foi calculado e qual foi redigido.

O mesmo texto vai para `relatorios_agente` (migração 009) e aparece no
cartão **Leitura do dia**, na tela de Carteira — por último na página, depois
dos números: abrir a tela com o texto do modelo daria a ele a primeira
palavra sobre uma carteira que ele não apurou.

## Três correções ao plano (Fase 3)

## Três correções ao plano

### 1. `mcp_servers` sozinho é erro de validação

O plano dizia que os MCPs são "passados via parâmetro `mcp_servers` na
chamada à Messages API". Não bastam. A API exige, para **cada** servidor
declarado, uma entrada correspondente em `tools`:

```python
mcp_servers=[{"type": "url", "name": "brapi", "url": "..."}]
tools=[{"type": "mcp_toolset", "mcp_server_name": "brapi"}]   # ← sem isto, 400
betas=["mcp-client-2025-11-20"]                                # ← e sem isto também
```

Um servidor sem toolset faz a API rejeitar a requisição **inteira**, com um
400 genérico que não diz qual servidor ficou faltando.

`ferramentas.montar()` produz as duas listas do mesmo laço, então declarar
uma sem a outra é impossível por esse caminho. `validar()` cobra a
invariante mesmo assim, e é o que os testes exercitam.

### 2. Busca web não precisa de MCP nenhum

O plano listava "busca web/notícia" como o primeiro MCP a conectar. A
Messages API tem `web_search` como ferramenta **nativa** de servidor:

- sem servidor para hospedar
- sem credencial para guardar
- **com citação de fonte embutida** — que é literalmente o critério de pronto
  da fase ("citar corretamente a fonte")

Um MCP de busca seria mais trabalho para um resultado pior.

### 3. Notificação não é ferramenta do agente

O plano previa um MCP de Slack/e-mail/Telegram para o agente entregar o
relatório. Dar ao modelo uma ferramenta de **envio** transfere a ele a
decisão de mandar, para quem e quantas vezes.

O envio fica determinístico, no script, **depois** de o agente compor o
texto. É a mesma fronteira que mantém "nada aqui é ordem executada"
verdadeira no resto do projeto — e vale igual para uma mensagem e para uma
ordem.

## Onde ficam os segredos

`src/agente/ferramentas.yaml` declara o **nome da variável de ambiente** que
guarda o token de cada servidor, nunca o token. O arquivo é versionado; a
variável vai no `EnvironmentFile` do systemd, com permissão 600 — o mesmo
lugar de `DATABASE_URL` e `BRAPI_TOKEN` (ver `docs/PREGAO.md`).

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> ~/.config/opcoes-ia/env
chmod 600 ~/.config/opcoes-ia/env
```

`python -m src.agente.ferramentas` mascara o token na saída, porque é o
comando que se cola num relato de problema.

## O MCP da Brapi, e por que está desligado

`.mcp.json` na raiz já configura o MCP da Brapi — mas aquele arquivo é a
config do **Claude Code**, mecanismo diferente que não vale para a Messages
API. Por isso ele aparece de novo em `ferramentas.yaml`, com `ativo: false`:

- metade das tools exige plano Startup (403 no Free — testado tool a tool)
- as que funcionam (perfil, lookup de ticker) o projeto já coleta por ETL
  próprio

Ligar só faria o agente reconsultar o que já está no banco, gastando request
do mesmo orçamento diário.

## Modelo

O plano escolheu `claude-sonnet-5` para a rotina e `claude-opus-4-8` para
escalar. A escolha de rotina se mantém; o alvo de escalada foi superado por
`claude-opus-5`, ao mesmo preço.

`verificar.py` testa no **mesmo modelo** que o agente vai usar — testar
noutro provaria uma fiação que não é a que roda.

## Chave de outro provedor

`ANTHROPIC_API_KEY` com uma chave que não começa com `sk-ant-` falha **antes**
de gastar a viagem, com mensagem que diz o que aconteceu. Sem isso, a chave
iria para `api.anthropic.com`, voltaria 401 falando de autenticação, e quem
colou a chave concluiria que ela expirou — não que está no lugar errado.

Chaves de DeepSeek, OpenAI e compatíveis não funcionam aqui, e não é questão
de qualidade do modelo: esta camada usa busca web nativa e conector MCP, que
só existem na Messages API.

## O que ainda falta

- **A chave não está configurada.** Sem `ANTHROPIC_API_KEY` nenhuma chamada
  real acontece, e o critério de pronto da Fase 3 ("buscar uma notícia real e
  citar a fonte") só fecha quando você rodar `python -m src.agente.verificar`.
  Toda a montagem é testada sem chave; a viagem até a API, não. Vale igual
  para o relatório: nenhum texto foi composto por um modelo de verdade ainda.
- **Escalada de modelo não está implementada.** O plano previa subir para um
  modelo mais capaz quando o próprio agente sinalizasse contradição entre
  fontes. Hoje `--modelo` troca à mão; detectar a contradição e escalar
  sozinho é decisão em aberto.
- **Cross-check de calendário não virou MCP.** O plano previa um; o projeto
  já tem Earnings Event Service com providers próprios (manual, CVM, Yahoo),
  e um MCP de calendário duplicaria isso com uma fonte a menos de
  procedência. O caminho certo é a Fase 4 passar o que o serviço já sabe
  como contexto, em vez de mandar o agente buscar de novo.
