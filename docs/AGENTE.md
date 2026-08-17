# Ferramentas do agente (Fase 3)

O agente de relatório ainda não existe — é a Fase 4. Esta fase entrega a
**fiação**: a configuração de ferramentas que a chamada à Messages API vai
usar, montada de forma que não dê para errar, e um comando que prova que ela
funciona.

```bash
python -m src.agente.ferramentas   # mostra o que seria enviado (sem token)
ANTHROPIC_API_KEY=sk-ant-... python -m src.agente.verificar   # chamada real
```

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

## O que ainda falta

- **A chave não está configurada.** Sem `ANTHROPIC_API_KEY` nenhuma chamada
  real acontece, e o critério de pronto da fase ("buscar uma notícia real e
  citar a fonte") só fecha quando você rodar `python -m src.agente.verificar`.
  Toda a montagem é testada sem chave; a viagem até a API, não.
- **O agente em si é a Fase 4.** Aqui não há prompt, não há relatório e não
  há entrega — só a configuração que a Fase 4 consome.
- **Cross-check de calendário não virou MCP.** O plano previa um; o projeto
  já tem Earnings Event Service com providers próprios (manual, CVM, Yahoo),
  e um MCP de calendário duplicaria isso com uma fonte a menos de
  procedência. O caminho certo é a Fase 4 passar o que o serviço já sabe
  como contexto, em vez de mandar o agente buscar de novo.
