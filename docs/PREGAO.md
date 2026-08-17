# Execução automática em pregão

Como o pipeline (`cotação → avaliação`) roda durante o pregão da B3, e o que
isso custa. Em producao, EventBridge Scheduler inicia uma task efemera no ECS
Fargate; systemd e apenas fallback local/de recuperacao e nunca pode ficar ativo
ao mesmo tempo.

## O que roda

`python -m src.operations intraday`, uma vez por disparo, sempre nesta ordem:

1. **Janela** — `src/pregao/calendario.py` diz se há pregão agora. Se não
   houver, registra `pulado_fora_de_pregao` com o motivo e sai. Fim.
2. **Cotação** — `src/etl/fetch_quotes.py` sobre o universo (carteira ∪
   vigiados).
3. **Avaliação** — `executar_avaliacao_carteira()`, sem nenhuma mudança.

Cada disparo adquire uma chave unica por ambiente/fluxo/janela em
`execucao_pipeline` **antes** de começar e grava tentativas por etapa em
`execucao_etapa_tentativa`. Ver `src/operations/` para idempotencia, heartbeat e
resume; `src/pregao/execucao.py` preserva compatibilidade do fluxo local.

### Por que a cotação vem junto, e não só a avaliação

Sem ela, uma avaliação disparada às 14h leria a cotação do **fechamento
anterior** — que tem menos de 72h e portanto passa na janela de frescor de
`params.yaml`. Não daria "dado insuficiente": daria uma sugestão calculada
sobre o preço de ontem, sem nada na tela indicando isso.

## Produção serverless

EventBridge usa `America/Sao_Paulo` e dispara a task definition operacional. Os
tres schedules nascem `DISABLED`; habilitacao so ocorre no cutover descrito em
`docs/RUNBOOK-CLOUD.md`. Logs ficam em `/ecs/opcoes-ia-prod-operations`, e o
estado duravel e o Neon, nao o filesystem da task.

## Recuperação local (unidade de usuário)

```bash
# 1. Segredos FORA do repositório, com permissão restrita.
mkdir -p ~/.config/opcoes-ia
cat > ~/.config/opcoes-ia/env <<'EOF'
DATABASE_URL=postgresql://.../neondb?sslmode=require
BRAPI_TOKEN=...
# OPLAB_TOKEN=...        # opcional, provedor legado de opções
# SMTP_HOST=...
# SMTP_TO=voce@exemplo.com
# SMTP_USER=...
# SMTP_PASSWORD=...
EOF
chmod 600 ~/.config/opcoes-ia/env

# 2. Unidades.
mkdir -p ~/.config/systemd/user
cp deploy/systemd/opcoes-ia-pregao.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now opcoes-ia-pregao.timer  # somente com EventBridge DISABLED

# alerta independente, depois do fechamento
cp deploy/systemd/opcoes-ia-alerta.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now opcoes-ia-alerta.timer

# 3. O timer de usuário só corre com a sessão aberta. Sem isto, fechar a
#    sessão para o pipeline sem erro nenhum aparecer.
loginctl enable-linger "$USER"
```

Conferir:

```bash
systemctl --user list-timers opcoes-ia-pregao.timer   # próximo disparo
systemctl --user start opcoes-ia-pregao.service       # dispara agora
journalctl --user -u opcoes-ia-pregao.service -n 50   # log do último
journalctl --user -u opcoes-ia-alerta.service -n 50   # alerta/verificação
```

Rodar à mão, sem systemd:

```bash
python -m scripts.rodar_pregao            # respeita a janela
python -m scripts.rodar_pregao --forcar   # ignora (fica marcado no detalhe)
```

## Orçamento: a cadência encolhe a watchlist

Esta é a consequência menos óbvia da automação, e a que morde primeiro.

O `CLAUDE.md` diz que 600 requests/dia comportam **~150 tickers**. Esse número
vale para o regime de UMA coleta diária (cotação + 2 janelas de vela +
opções = 4 requests/ticker/dia). Disparar de 30 em 30 minutos acrescenta 14
coletas de cotação por ticker por dia — e o teto cai para ~33.

| Cadência       | Disparos/dia | Requests/ticker/dia | Teto de tickers |
| -------------- | -----------: | ------------------: | --------------: |
| 30 min         |           14 |                  18 |             ~33 |
| 60 min         |            8 |                  12 |             ~50 |
| 2 h            |            4 |                   8 |             ~75 |
| só diário      |            0 |                   4 |            ~150 |

(“Requests/ticker/dia” = disparos intradiários + 1 cotação do ETL diário + 2
velas + 1 opções.)

**Cadência e tamanho da watchlist são o mesmo botão.** Aumentar os dois ao
mesmo tempo estoura o orçamento, e o sintoma é o `fetch_quotes` cortando a
lista pelo fim — os últimos tickers em ordem alfabética simplesmente param de
ter preço, o que aparece depois como "dado insuficiente" na avaliação.

Em producao, mude `intraday_schedule_expression` no Terraform, revise o plano e
aplique por release. No fallback local, edite os `OnCalendar` do timer e
recarregue:

```bash
systemctl --user daemon-reload && systemctl --user restart opcoes-ia-pregao.timer
```

> ⚠️ O orçamento é medido por **proxy** (`src/etl/budget.py` conta linhas
> gravadas hoje), não por contagem real de requests. Ele **subestima**: candles,
> consultas MCP e requests que falham antes de gravar não entram corretamente
> na conta — e hoje TODA chamada de opções falha com 403 no plano Free, sem
> gravar linha. Na prática o gasto real é maior que o exibido, e a tabela acima
> é o limite otimista.

## Calendário

`src/pregao/feriados_b3.yaml` — feriados e horário da sessão. 2026 foi
conferido contra o calendário oficial da B3 (via BrasilAPI); 2027 e 2028 são
derivados das regras por `python -m src.pregao.derivar`, que reproduz as 14
datas conferidas de 2026 sem sobra nem falta.

Consultar uma data **fora da vigência** levanta `CalendarioVencido` e o
disparo falha — nunca devolve "não é feriado". As duas alternativas são
piores: responder `False` emudeceria o pipeline em dia útil, e responder
`True` o faria avaliar num feriado sobre a cotação de outro dia.

Estender:

```bash
python -m src.pregao.derivar 2026 2029 > src/pregao/feriados_b3.yaml
# depois confira o ano novo contra a fonte e acrescente-o a `conferido.anos`
```

O estado (vigência, anos conferidos, anos derivados) aparece em
`/saude-coleta` → `automacao.calendario`, e na tela de **Mercado**.

## Entrega e alerta

O relatório do agente é persistido no Neon; arquivo e apenas export local. Quando `SMTP_HOST`
e `SMTP_TO` estão configurados, também é enviado por e-mail pelo código
determinístico depois da composição. O agente não possui ferramenta de envio.
Falha no SMTP deixa o serviço do relatório vermelho, mas não apaga o relatório
já persistido.

Em producao, o schedule `alert` e uma verificacao separada as 18h30. No fallback,
`opcoes-ia-alerta.timer` cumpre o mesmo papel. Se não houver uma
execução concluída, houver execução órfã/falha, ou o banco não responder, ela
tenta enviar um alerta pelo mesmo SMTP. Sem SMTP configurado, o serviço falha
explicitamente no journal em vez de fingir que há cobertura.

## O que ainda não está coberto

- **Falha por fonte de coleta continua sem registro.** `fetch_quotes` isola
  falha por ticker num `log.warning` e segue; a execução termina como
  `executado`. Por isso `/saude-coleta` mantém `rastreia_falhas: false` para
  as COLETAS, mesmo agora que a EXECUÇÃO é rastreada — são dois escopos.
- **`opcoes` está vazia** (403 no plano Free da Brapi). O pipeline roda e
  registra tudo corretamente, mas `pares_avaliados` fica em 0 até haver
  cadeia coletada. A automação está pronta para o dia da virada; ela não
  antecipa esse dia.
