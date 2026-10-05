# Lâmina: decisões de design

Este documento registra as decisões de arquitetura da Lâmina (aprovadas em 05/10/2026) e o motivo de cada uma. Para saber como usar o app, veja o [README](../README.md).

## Objetivo e restrições

- **Objetivo:** maximizar a nota no R1 de Acesso Direto da Unicamp (prova em 15/11/2026). A prova tem 100 questões discursivas curtas, em 2 cadernos de 50, com 20 questões de cada área.
- **Base humana:** temas, blocos, aproveitamento e "dominado" com 80% ou mais. O Claude atua por cima, sem substituir essa base.
- **Tokens escassos:** o app usa um plano de assinatura com limite de uso. Nada roda sem motivo: tutor, flashcards e coach só rodam sob demanda, e o juiz usa um modelo barato.
- **Repositório público:** dados pessoais ficam em `app_data/`, fora do git.

## Arquitetura

```
React + TS (Vite, Tailwind) ──HTTP/SSE──▶ FastAPI (Python 3.12, uv) ──▶ SQLite (WAL) em app_data/
                                               └─▶ claude-agent-sdk ──▶ claude CLI (login do usuário)
                                                     ├─ tools in-process (MCP do SDK) com acesso direto ao banco
                                                     └─ WebSearch/WebFetch/Read(imagens) conforme o papel
```

- **Camada Claude** (`backend/lamina/claude/runner.py`):
  - **Isolamento:** `setting_sources=[]` e `strict_mcp_config=True`, com prompt de sistema próprio. Assim nenhum plugin, hook ou CLAUDE.md do usuário entra no contexto: cerca de 1,3k tokens de base por chamada, contra dezenas de milhares no preset padrão.
  - **Ambiente limpo:** o backend remove as variáveis `ANTHROPIC_*` e `CLAUDE*` herdadas, para que nenhum gateway ou token alheio seja usado. O login do CLI (`claude auth login`) é a única credencial.
  - **Registro de uso:** cada chamada vira uma linha em `llm_jobs`, com tokens, custo-equivalente, duração e erro. Os eventos de limite de uso são guardados em `limite_uso`.
- **`FakeRunner`:** permite testar toda a lógica sem gastar tokens.

## Papéis do Claude

| Papel | Modelo padrão | Ferramentas | Observações |
|---|---|---|---|
| Juiz (estágio 1) | Haiku 4.5, raciocínio desligado | nenhuma | Compara com o gabarito da banca e sinaliza `verificar_atualizacao` quando houver nota de atualização ou indício de conduta mais nova. No simulado, corrige em lotes de 10 |
| Juiz (estágio 2) | Sonnet 5.5, esforço médio | kit completo | Busca obrigatória da recomendação vigente (MS/sociedades); julga por ela e escreve o `adendo` "gabarito da época × hoje". Também atende o "Rejulgar" |
| Tutor | Sonnet 5.5, esforço baixo | kit + `buscar_questoes` e `criar_flashcards` | Busca obrigatória na primeira resposta; sessões retomadas com `resume`; também em modo livre, sem questão |
| Flashcards | Sonnet 5.5, esforço baixo | kit | O verso traz a recomendação atual e, entre parênteses, o gabarito da época |
| Coach | Sonnet 5.5, esforço médio | kit + todas as ferramentas MCP de leitura e ação | Toda ação de escrita é registrada e reversível. Não marca domínio |

O "kit" de todas as instâncias inclui:
- WebSearch e WebFetch;
- `Read` restrito a `banco_questoes/`;
- o MCP in-process `terminal`: bash isolado com bubblewrap, `--unshare-all`, sem home e sem rede, com `/trabalho` gravável e, em `/dados`, o banco de questões, a curadoria e um snapshot do SQLite, todos somente leitura.

O sandbox nativo do Claude Code não se aplicou nesta máquina (falta o `socat`), por isso o app usa o próprio. O motivo é segurança: páginas lidas pelo WebFetch podem conter injeção de instruções.
| Curadoria | Sonnet 5.5 | — | Roda uma vez, por script |

## Regras de domínio (determinísticas)

- **Pontuação:** correto vale 1, parcial 0,5 e incorreto 0. Acerto com confiança "chute" vale 0 para domínio, mas conta no placar bruto.
- **Base do cálculo:** a última tentativa julgada de cada questão.
- **Dominado:** domínio firme ≥ 80% com cobertura de 100%, ou marcação manual do aluno. O selo "revisar" aparece 14 dias depois da última atividade.
- **Prevalência:** peso por ano (2026 = 1,0, 2025 = 0,9, 2024 = 0,8, 2023 = 0,6, 2022 = 0,5) e ×0,8 para as MC adaptadas.
- **Prioridade:** prevalência normalizada × (0,35 + 0,65 × lacuna) × peso do coach.
- **SRS:** FSRS com intervalo máximo limitado a `dias_até_prova − 1`.

## Curadoria

`scripts/curadoria.py` gera os arquivos versionados em `curadoria/`:
- **`temas`:** uma chamada por área, que cria de 10 a 14 temas e classifica todas as questões (tema principal, secundários, subtópico e tipo cognitivo). Usa referências curtas (Q1…Qn) para economizar saída.
- **`adaptar`:** MC → discursiva em lotes de 20. O modelo devolve só a nova pergunta final e o trecho que ela substitui, e o script recompõe o enunciado. A nota de atualização (`obs`) aponta gabaritos desatualizados frente às recomendações atuais e aparece no app junto do gabarito.

As edições feitas na página Curadoria do app gravam direto nesses JSON e reimportam o banco.

## Gabarito desatualizado

Decisão do aluno: prevalece a recomendação vigente do Ministério da Saúde e das sociedades brasileiras na data atual, com um adendo que explica o gabarito da época e o que mudou. Exemplo validado: na profilaxia do meningococo, o gabarito de 2023 dava ceftriaxona; o juiz aceita rifampicina e cita o Guia de Vigilância em Saúde.
