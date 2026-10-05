# Lâmina: decisões de design

Este documento registra as decisões de arquitetura da Lâmina (aprovadas em 05/10/2026) e o motivo de cada uma. Para saber como usar o app, veja o [README](../README.md).

## Objetivo e restrições

- **Objetivo:** maximizar a nota no R1 de Acesso Direto da Unicamp (prova em 15/11/2026). A prova tem 100 questões discursivas curtas, em 2 cadernos de 50, com 20 questões de cada área.
- **Base humana:** temas, blocos, aproveitamento e "dominado" com 80% ou mais. O Claude atua por cima, sem substituir essa base.
- **Tokens escassos:** o app usa um plano de assinatura com limite de uso. Nada roda sem motivo: tutor e flashcards só sob demanda, o juiz usa um modelo barato e o segundo plano tem orçamento diário e respeita a janela do plano.
- **Repositório público:** dados pessoais ficam em `app_data/`, fora do git.

## Arquitetura

```
React + TS (Vite, Tailwind) ──HTTP/SSE──▶ FastAPI (Python 3.12, uv) ──▶ SQLite (WAL) em app_data/
                                               └─▶ claude-agent-sdk ──▶ claude CLI (login do usuário)
                                                     ├─ tools in-process (MCP do SDK) com acesso direto ao banco
                                                     ├─ WebSearch/WebFetch; Read/Grep/Glob no caderno, biblioteca e banco; Write/Edit no caderno
                                                     └─ cwd = app_data/agentes/<agente> (caderno + MEMORIA.md)
               Maestro (asyncio, 5 min) ──▶ sentinela (sem LLM) ──▶ avisos · ronda do Preceptor · fila de tarefas
```

- **Camada Claude** (`backend/lamina/claude/runner.py`):
  - **Isolamento:** `setting_sources=[]` e `strict_mcp_config=True`, com prompt de sistema próprio. Assim nenhum plugin, hook ou CLAUDE.md do usuário entra no contexto: cerca de 1,3k tokens de base por chamada, contra dezenas de milhares no preset padrão.
  - **Ambiente limpo:** o backend remove as variáveis `ANTHROPIC_*` e `CLAUDE*` herdadas, para que nenhum gateway ou token alheio seja usado. O login do CLI (`claude auth login`) é a única credencial.
  - **Registro de uso:** cada chamada vira uma linha em `llm_jobs`, com tokens, custo-equivalente, duração e erro. Os eventos de limite de uso são guardados em `limite_uso`.
- **`FakeRunner`:** permite testar toda a lógica sem gastar tokens.

## Agentes

| Agente | Modelo padrão | Ferramentas do app (MCP) | Observações |
|---|---|---|---|
| Juiz (estágio 1) | Haiku 4.5, raciocínio desligado | nenhuma | Compara com o gabarito da banca e sinaliza `verificar_atualizacao` quando houver nota de atualização ou indício de conduta mais nova. No simulado, corrige em lotes de 10 |
| Juiz (estágio 2) | Sonnet 5.5, esforço médio | terminal, ver_questao, leitura da biblioteca, `biblioteca_capturar` | Verifica a recomendação vigente, primeiro na biblioteca e depois na web (com captura do documento oficial). Julga por ela e escreve o `adendo` "gabarito da época × hoje". Também atende o "Rejulgar" |
| Tutor | Sonnet 5.5, esforço baixo | + `buscar_questoes`, `criar_flashcards`, `historico_conversas`, escrita na biblioteca | É sempre o mesmo agente: tem caderno e MEMORIA.md. Ordem de pesquisa: biblioteca → caderno/conversas → web com captura integral. Registra notas e anotações quando agregam |
| Flashcards | Sonnet 5.5, esforço baixo | terminal, ver_questao, leitura da biblioteca | O verso traz a recomendação atual e, entre parênteses, o gabarito da época |
| Preceptor | Sonnet 5.5, esforço médio | todas (admin) | Substituiu o coach. Faz rondas em segundo plano ou a pedido e conversa com o aluno (estratégia e métricas). Planeja a agenda, publica missões, avisos e insights, cria blocos e flashcards e delega tarefas. Não marca domínio nem apaga dados do aluno |
| Bibliotecário | Sonnet 5.5, esforço médio | biblioteca completa (incluindo `biblioteca_marcar`), panorama, banco de questões, terminal | Executa tarefas da fila: captura documentos oficiais integrais, controla a vigência e escreve notas-síntese com citação de página |
| Curadoria | Sonnet 5.5 | — | Roda uma vez, por script |

### Ambiente de cada instância

Todas as instâncias com ferramentas recebem o mesmo "kit", e o papel define quais ferramentas MCP entram.
- **Caderno:** `app_data/agentes/<agente>/` é o `cwd` da instância.
  - O agente lê e busca ali (Read, Grep, Glob) e escreve só ali (Write e Edit, pela regra de permissão `Edit(//caderno/**)`).
  - A `MEMORIA.md` do caderno, limitada a 6 mil caracteres, entra no prompt de sistema do tutor, do Preceptor e do bibliotecário. É ela que dá continuidade entre sessões.
- **Biblioteca e banco de questões:** entram como `add_dirs`, só para leitura.
- **Validação (05/10/2026):** com `permission_mode="dontAsk"`, tudo fora dessas regras é negado, inclusive Grep e Glob em outros caminhos.
- **Web:** WebSearch e WebFetch. Para guardar um documento inteiro, `biblioteca_capturar`.
- **Terminal bubblewrap:** `/trabalho` é o caderno; `/biblioteca` e `/dados` ficam somente leitura; sem rede.
- **Retomada de conversa:** se uma sessão do CLI não puder ser retomada (por exemplo, porque o cwd mudou), a conversa recomeça com a transcrição recente, sem erro para o aluno.

## Biblioteca compartilhada

- **Por quê:** o WebFetch do Claude Code devolve ao modelo um resumo da página, e esse conhecimento se perde no fim da sessão. A biblioteca guarda o documento inteiro, de forma persistente, para todos os agentes. Isso reduz a dependência da memória do modelo, treinada sobretudo em literatura estadunidense.
- **Captura** (`lamina/biblioteca/captura.py`): download pelo próprio backend, só http/https para endereços públicos (verificados a cada redirecionamento), até 80 MB.
  - PDF via pypdfium2, com marcas `[[página N]]`.
  - HTML via trafilatura, em Markdown, devolvendo também os links de PDF de páginas-índice.
- **Armazém** (`armazem.py`): os arquivos ficam em `app_data/biblioteca/` (`docs/<id>/texto.md`, `original.*`, `meta.json`; `notas/<id>.md`; `CATALOGO.md`). No SQLite, a tabela `biblioteca` guarda os metadados e `biblioteca_fts` é um índice FTS5 sem acentos, em trechos de cerca de 1.500 caracteres com página ou seção.
  - A busca usa BM25 com prefixos, que dão um stemming leve.
  - O documento vigente vem antes do substituído.
  - Duplicatas são barradas por URL e por sha256.
- **Notas-síntese:** exigem fontes (ids da biblioteca ou URLs). A interface transforma citações `[id, p. N]` em links para o leitor.
- **Fora do git:** documentos de sociedades têm direitos autorais.

## Orquestração (Preceptor)

- **Maestro** (`lamina/orquestra/maestro.py`): ciclo asyncio iniciado com o servidor, a cada 5 minutos.
  1. A sentinela (`sentinela.py`) coleta sinais sem LLM: meta do dia, flashcards vencidos, dias sem estudar, agenda, temas a revisar, fila e orçamento.
  2. Cria lembretes óbvios (meta, flashcards, agenda), no máximo um de cada por dia, a partir da `hora_lembrete`.
  3. Entrega os avisos vencidos pelo sino do app e pelo `notify-send`, respeitando o silêncio noturno.
  4. Se o segundo plano estiver liberado, roda uma ronda do Preceptor quando houver motivo (primeira do dia a partir da `hora_ronda`, ou N respostas novas); se não, executa a próxima tarefa da fila.
  5. Um trabalho por vez, em uma task separada. A fila do runner também é separada, para nunca ocupar a vez do aluno.
- **Orçamento:** o segundo plano roda se estiver ligado, sem pausa, com gasto do dia abaixo de `orcamento_fundo_dia` (em tokens efetivos, com a leitura de cache valendo 1/10) e com folga na janela do plano (status do `RateLimitEvent`). Rondas e tarefas disparadas pelo aluno não contam no orçamento de segundo plano.
- **Dados:**
  - `tarefas`: fila dos agentes; tarefas interrompidas voltam para a fila, com até 3 tentativas;
  - `avisos`: idempotentes por `chave`;
  - `agenda`;
  - `estado`: pausa.
- **Reversibilidade:** as ações do Preceptor e do tutor ficam em `coach_acoes` e podem ser desfeitas (bloco, peso, missões, insights, flashcards, agenda, aviso, tarefa). A agenda restaura os itens com o id original, para que o desfazer funcione em cadeia.
- **Serviço opcional:** `scripts/instalar_servico.sh` instala um serviço systemd de usuário, para o ciclo rodar com o navegador fechado.

## Segurança (injeção vinda da web)

Páginas lidas podem conter instruções maliciosas. As defesas:
- os agentes só escrevem no próprio caderno;
- o terminal não tem rede nem home;
- a captura bloqueia a rede local;
- as ações no app são limitadas e reversíveis;
- os prompts tratam texto da web como dado.

O que sobra de risco é o vazamento, via WebFetch, de dados de estudo (desempenho e perfil) que o agente consegue ler. Aceito por ser um app local e pessoal.

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
