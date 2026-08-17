# Execução automática em pregão

Como o pipeline (`cotação → avaliação`) passa a rodar sozinho durante o
pregão da B3, e o que isso custa.

## O que roda

`scripts/rodar_pregao.py`, uma vez por disparo, sempre nesta ordem:

1. **Janela** — `src/pregao/calendario.py` diz se há pregão agora. Se não
   houver, registra `pulado_fora_de_pregao` com o motivo e sai. Fim.
2. **Cotação** — `src/etl/fetch_quotes.py` sobre o universo (carteira ∪
   vigiados).
3. **Avaliação** — `executar_avaliacao_carteira()`, sem nenhuma mudança.

Cada disparo grava uma linha em `execucao_pipeline` **antes** de começar e a
fecha com o desfecho. Ver `src/pregao/execucao.py` para por que a linha abre
antes (resumo: é o único jeito de um processo morto no meio deixar rastro).

### Por que a cotação vem junto, e não só a avaliação

Sem ela, uma avaliação disparada às 14h leria a cotação do **fechamento
anterior** — que tem menos de 72h e portanto passa na janela de frescor de
`params.yaml`. Não daria "dado insuficiente": daria uma sugestão calculada
sobre o preço de ontem, sem nada na tela indicando isso.

## Instalação (unidade de usuário)

```bash
# 1. Segredos FORA do repositório, com permissão restrita.
mkdir -p ~/.config/opcoes-ia
cat > ~/.config/opcoes-ia/env <<'EOF'
DATABASE_URL=postgresql://.../neondb?sslmode=require
BRAPI_TOKEN=...
OPLAB_TOKEN=...
EOF
chmod 600 ~/.config/opcoes-ia/env

# 2. Unidades.
mkdir -p ~/.config/systemd/user
cp deploy/systemd/opcoes-ia-pregao.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now opcoes-ia-pregao.timer

# 3. O timer de usuário só corre com a sessão aberta. Sem isto, fechar a
#    sessão para o pipeline sem erro nenhum aparecer.
loginctl enable-linger "$USER"
```

Conferir:

```bash
systemctl --user list-timers opcoes-ia-pregao.timer   # próximo disparo
systemctl --user start opcoes-ia-pregao.service       # dispara agora
journalctl --user -u opcoes-ia-pregao.service -n 50   # log do último
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
opções = 4 requests/ticker/dia). Disparar de 30 em 30 minutos acrescenta 13
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

Para mudar a cadência, edite os `OnCalendar` do timer e recarregue:

```bash
systemctl --user daemon-reload && systemctl --user restart opcoes-ia-pregao.timer
```

> ⚠️ O orçamento é medido por **proxy** (`src/etl/budget.py` conta linhas
> gravadas hoje), não por contagem real de requests. Ele **subestima**: um
> request que falha antes de gravar não é contado — e hoje TODA chamada de
> opções falha com 403 no plano Free, sem gravar linha. Na prática o gasto
> real é maior que o exibido, e a tabela acima é o limite otimista.

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

## O que ainda não está coberto

- **Alerta de "não rodou hoje" não sai sozinho.** A tela mostra, mas ninguém
  é avisado. Um log que vive no banco não consegue registrar a queda do
  próprio banco — o alerta precisa de um caminho independente. É a Fase 5 do
  plano de automação.
- **Falha por fonte de coleta continua sem registro.** `fetch_quotes` isola
  falha por ticker num `log.warning` e segue; a execução termina como
  `executado`. Por isso `/saude-coleta` mantém `rastreia_falhas: false` para
  as COLETAS, mesmo agora que a EXECUÇÃO é rastreada — são dois escopos.
- **`opcoes` está vazia** (403 no plano Free da Brapi). O pipeline roda e
  registra tudo corretamente, mas `pares_avaliados` fica em 0 até haver
  cadeia coletada. A automação está pronta para o dia da virada; ela não
  antecipa esse dia.
