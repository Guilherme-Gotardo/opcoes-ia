## MODIFIED Requirements

### Requirement: Bloqueio reportado indica a ação para destravar
Ao reportar uma avaliação bloqueada por data de resultado desconhecida, o
relatório SHALL indicar a sequência completa de ações humanas que destrava a
avaliação — registrar a data **e** consolidá-la — e SHALL NOT indicar apenas
o registro, que sozinho não torna a data consultável pela avaliação.

#### Scenario: Relatório orienta o registro da data
- **WHEN** o relatório lista uma avaliação bloqueada por falta de data de
  resultado
- **THEN** a entrada indica que registrar a data de divulgação do ativo
  destrava a avaliação

#### Scenario: Orientação inclui a consolidação
- **WHEN** o relatório lista uma avaliação bloqueada por falta de data de
  resultado
- **THEN** a orientação apresenta também o passo de consolidação, de modo que
  seguir a instrução ao pé da letra torne a data efetivamente consultável na
  avaliação seguinte
