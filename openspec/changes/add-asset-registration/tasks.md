## 1. Domínio e CLI de ativos

- [x] 1.1 Criar `src/assets/__init__.py` e `src/assets/manage.py`, espelhando
      a estrutura de `src/portfolio/manage.py` (`design.md`, decisão 1).
- [x] 1.2 Implementar `AtivoInvalido` no padrão de `PosicaoInvalida` e
      `EntradaInvalida`: falha alto, nomeia o campo, nunca ajusta a entrada.
- [x] 1.3 Implementar o registro de ativo (ticker, nome, tipo, `cnpj_raiz`
      opcional) como upsert por ticker, para que recadastrar corrija em vez
      de duplicar ou falhar (`design.md`, decisão 6).
- [x] 1.4 Validar: ticker obrigatório e normalizado para maiúsculas, nome
      obrigatório e não vazio, tipo dentro dos valores aceitos (spec
      `asset-registry`, requisito "Rejeição de cadastro inválido").
- [x] 1.5 Implementar a consulta que lista os ativos cadastrados distinguindo
      quem tem `cnpj_raiz` de quem não tem, e informando explicitamente
      quando não há nenhum (spec, requisito "Consulta dos ativos
      cadastrados").
- [x] 1.6 Expor a CLI `python -m src.assets.manage` com `add` e `list`, com
      `--cnpj-raiz` opcional no `add`.
- [x] 1.7 Testes de `assets/manage.py`: cadastro válido, ticker vazio
      rejeitado, nome ausente rejeitado, tipo inválido rejeitado, recadastro
      corrigindo sem duplicar, listagem distinguindo com/sem `cnpj_raiz`,
      listagem vazia informando.

## 2. Registro de posição exige ativo cadastrado

- [x] 2.1 Em `src/portfolio/manage.py`, recusar posição em `ACAO` cujo ticker
      não esteja cadastrado, com mensagem que nomeia o ticker e cita
      `python -m src.assets.manage add` (spec `portfolio-tracking`, cenário
      "Posição em ativo não cadastrado é recusada").
- [x] 2.2 Não aplicar a validação a `OPCAO`: `posicoes.ticker` guarda o
      código da opção, que não é linha de `ativos` (`design.md`, decisão 3).
      Registrar a limitação em comentário no código, para não parecer
      esquecimento.
- [x] 2.3 Testes em `tests/test_portfolio_manage.py`: posição em ativo
      cadastrado grava; posição em ativo desconhecido é recusada com a
      mensagem acionável; posição em `OPCAO` não é bloqueada pela validação.

## 3. Coleta reporta ativo não cadastrado

- [x] 3.1 Em `src/etl/fetch_quotes.py`, verificar quais tickers estão
      cadastrados **antes** de inserir, numa consulta só, e reportar os não
      cadastrados como falha nomeada (`design.md`, decisão 4 — não traduzir
      `ForeignKeyViolation`, que acopla a mensagem ao nome da constraint).
- [x] 3.2 Garantir que o isolamento de falha por ticker continua: um ticker
      não cadastrado não pode impedir a coleta dos demais (spec
      `market-data-collection`, requisito modificado).
- [x] 3.3 Testes em `tests/test_fetch_quotes.py`: ticker não cadastrado
      aparece no resumo como ativo não cadastrado, com a ação citada, e os
      demais tickers seguem coletados.

## 4. Aviso da CVM cita o comando

- [x] 4.1 Trocar em `src/earnings/providers/cvm.py` o texto que sugere
      `UPDATE ativos SET cnpj_raiz = ...` pelo comando de cadastro
      (`design.md`, decisão 5). Comportamento não muda: continua pulando o
      ticker sem CNPJ.
- [x] 4.2 Ajustar o teste que cobre esse aviso, se ele afirma o texto atual.

## 5. Documentação

- [x] 5.1 Adicionar o comando de cadastro de ativo a "Comandos úteis" no
      `CLAUDE.md`, **antes** do comando de posição, deixando a ordem
      explícita: cadastrar ativo → cadastrar posição.
- [x] 5.2 Fechar em `CLAUDE.md` a pendência de `ativos.cnpj_raiz`, que hoje
      está registrada como item aberto orientando `UPDATE` manual.
- [x] 5.3 Atualizar `docs/RUNBOOK-POSTGRES.md`: a seção "Cadastrar a
      carteira" precisa começar pelo cadastro dos ativos, senão o runbook
      leva ao mesmo erro que esta change conserta.

## 6. Validação de ponta a ponta

- [x] 6.1 Rodar `pytest` completo apontando para o banco descartável.
- [x] 6.2 Contra uma base limpa (banco local recriado com
      `python -m src.db.bootstrap`), reproduzir o caminho de onboarding
      completo: cadastrar ativo → cadastrar posição → coletar cotação, e
      confirmar que funciona sem nenhum `INSERT` manual.
- [x] 6.3 Confirmar que, sem cadastrar o ativo, o erro que aparece é a
      mensagem acionável e não a violação de chave estrangeira — o sintoma
      que originou esta change.
- [x] 6.4 Confirmar que os ativos já cadastrados no Neon continuam válidos e
      que recadastrar um deles corrige sem duplicar.
