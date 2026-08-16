## 1. Fábrica de providers

- [x] 1.1 Implementar em `src/earnings/providers/__init__.py` (hoje vazio) o
      mapa nome → construtor cobrindo `manual`, `cvm` e `yahoo`, com o
      conjunto padrão `["manual"]` (`design.md`, decisão 2).
- [x] 1.2 Implementar a resolução de uma lista de nomes em instâncias,
      levantando erro explícito que nomeie o valor inválido e as fontes
      válidas — antes de qualquer I/O (spec `earnings-calendar`, cenário
      "Fonte desconhecida falha alto").
- [x] 1.3 Rejeitar lista vazia de fontes com o mesmo erro explícito, já que
      `EarningsEventService` cai em `providers=[]` silenciosamente e
      consolidaria zero eventos reportando sucesso (`design.md`, decisão 3).
- [x] 1.4 Testes da fábrica: padrão devolve só `manual`; nome válido
      instancia o provider certo; nome inválido levanta erro citando as
      opções; lista vazia levanta erro.

## 2. Entrypoint de consolidação

- [x] 2.1 Criar `src/earnings/ingest.py` com CLI no padrão de
      `src/earnings/manage.py` (`argparse`, `main(argv=None)`, erro de
      entrada via `parser.exit(2, ...)`) — `design.md`, decisão 1.
- [x] 2.2 Implementar a descoberta do escopo de tickers a partir das posições
      em ação em aberto, o mesmo conjunto que `executar_avaliacao_carteira`
      percorre (`design.md`, decisão 5).
- [x] 2.3 Implementar `--tickers PETR4,VALE3` substituindo o padrão derivado
      da carteira (spec, cenário "Lista explícita substitui o padrão").
- [x] 2.4 Implementar o encerramento com aviso e sem consultar fonte alguma
      quando não houver posição aberta nem `--tickers` (spec, cenário
      "Carteira vazia não vira varredura").
- [x] 2.5 Implementar `--fontes manual,cvm` sobre a fábrica da tarefa 1,
      mantendo `manual` como padrão quando a opção for omitida.
- [x] 2.6 Montar o `EarningsEventService` com os providers resolvidos e
      chamar `ingerir()` — sem reimplementar coleta, agrupamento ou
      resolução (`design.md`, decisão 1: o comando é a manivela).
- [x] 2.7 Reportar na saída, por fonte, quantos eventos vieram e qual falhou
      com que motivo, distinguindo "não conseguimos consultar" de "não há
      evento" (spec, requisito "Falha de fonte é reportada, nunca virada
      ausência de evento").
- [x] 2.8 Encerrar com código diferente de zero quando **todas** as fontes
      pedidas falharem, e com zero quando ao menos uma responder
      (`design.md`, decisão 4).
- [x] 2.9 Testes do entrypoint com serviço e providers fakes: escopo vindo da
      carteira, `--tickers` sobrescrevendo, carteira vazia encerrando sem
      I/O, fonte inválida falhando, falha parcial concluindo com sucesso e
      falha total devolvendo código não zero.

## 3. Mensagem de destravamento do relatório

- [x] 3.1 Atualizar `_renderizar_bloqueios` em `src/report/daily.py` para
      apresentar a sequência completa (registrar **e** consolidar), em vez de
      só `manage add` (spec `daily-portfolio-report`, requisito "Bloqueio
      reportado indica a ação para destravar").
- [x] 3.2 Atualizar o teste correspondente em `tests/test_report_daily.py`
      (`test_bloqueio_por_resultado_aparece_com_criterios_e_acao`), que hoje
      afirma apenas a presença de `src.earnings.manage add`.

## 4. Automação

- [x] 4.1 Adicionar o passo de consolidação ao `.github/workflows/daily-etl.yml`
      entre a coleta e a avaliação de estratégia, sem `continue-on-error`
      (`design.md`, decisão 6).
- [x] 4.2 Conferir que o passo herda `DATABASE_URL` do `env` do job e não
      exige segredo novo — o padrão `manual` não usa rede.

## 5. Documentação

- [x] 5.1 Atualizar "Comandos úteis" em `CLAUDE.md` para mostrar a sequência
      `manage add` → `ingest` → avaliação, deixando claro que registrar não
      é consolidar.
- [x] 5.2 Corrigir em `CLAUDE.md` a afirmação de que registrar a data basta
      para o sistema emitir sugestão, e registrar que a consolidação é o elo
      que faltava.
- [x] 5.3 Acrescentar `ingest.py` à ordem de leitura da seção "Onde olhar
      primeiro" para `src/earnings/`.

## 6. Validação de ponta a ponta

- [x] 6.1 Rodar `pytest` completo e confirmar que a suíte de earnings,
      valorização e relatório segue verde.
- [x] 6.2 No banco local: registrar uma data com `manage add`, rodar a
      consolidação e confirmar que `earnings_events` deixou de estar vazia e
      que `proximo_evento()` devolve a data — o caminho que falhou na
      validação de 2026-08-16.
- [x] 6.3 Com opção sintética (`fonte='sintetico'`, como na change de
      valorização a mercado), confirmar que o critério
      `dias_para_resultado` sai de `indisponivel` para `aprovado` e que a
      sugestão é emitida e persistida em `sugestoes` com a base de
      valorização no `criterios_json`.
- [x] 6.4 Confirmar que a orientação impressa no relatório, seguida ao pé da
      letra e sem conhecimento prévio, destrava a avaliação.
- [x] 6.5 Limpar do banco local os dados sintéticos usados na validação,
      deixando a carteira real como estava.
