# Lâmina — estudo para o R1 de Acesso Direto da Unicamp

Lâmina é uma aplicação local para estudar para a prova de Residência Médica da Unicamp (Acesso Direto). O conteúdo vem das provas de 2022 a 2026: 650 questões, todas no formato atual de **resposta curta discursiva**. As antigas de múltipla escolha foram adaptadas.

O núcleo é humano: temas, blocos de questões, aproveitamento, e o tema é "dominado" quando o domínio chega a 80% ou mais. Sobre ele, instâncias do **Claude Code CLI** trabalham como agentes:

| Agente | O que faz | Quando roda |
|---|---|---|
| Juiz | Compara a sua resposta com o gabarito da banca. Se o gabarito puder estar desatualizado, um segundo estágio verifica a recomendação **vigente** (primeiro na biblioteca, depois na web), julga por ela e escreve um adendo ("gabarito da época × hoje") | A cada resposta (Haiku; Sonnet + biblioteca/web só quando necessário) |
| Tutor | Chat lateral (por questão) ou livre. É sempre o mesmo agente: consulta a biblioteca, pesquisa na web, guarda documentos oficiais inteiros e mantém um caderno próprio entre as conversas | Só quando você pergunta |
| Flashcards | Gera cartões de revisão a partir da questão e do seu erro | Só quando você pede |
| Preceptor | Orquestrador nos bastidores: rondas em segundo plano que leem o seu desempenho, planejam a agenda, publicam missões, criam blocos e flashcards, mandam avisos e delegam pesquisa ao bibliotecário. Só você conversa com ele (estratégia e métricas). Tudo pode ser desfeito | Sozinho, dentro de um orçamento diário, e quando você chama |
| Bibliotecário | Busca documentos brasileiros oficiais (MS, CONITEC, sociedades), guarda o **texto integral** na biblioteca, controla a vigência e escreve notas-síntese com citação de página | Tarefas na fila, em segundo plano |

### Biblioteca e cadernos

- **Biblioteca compartilhada** (`app_data/biblioteca/`): o app baixa o documento inteiro, extrai o texto, guarda o original e indexa tudo para busca em texto completo. Isso resolve uma limitação do WebFetch do Claude Code, que entrega só um resumo da página.
  - Cada item registra a fonte, o ano, a confiabilidade (oficial, sociedade, literatura ou nota) e se está vigente ou foi substituído.
  - Todos os agentes consultam a biblioteca antes da web. Você pode ler os documentos no app e citar páginas.
- **Cadernos** (`app_data/agentes/<agente>/`): cada agente tem um diretório próprio e persistente. Ali ele escreve livremente (Write/Edit) e mantém uma `MEMORIA.md` que entra no prompt de toda nova sessão. É assim que o tutor e o Preceptor acumulam conhecimento entre conversas.
  - Você lê os cadernos na Biblioteca. Os agentes não escrevem fora deles.

## Como rodar

Requisitos: Linux ou macOS, [uv](https://docs.astral.sh/uv/), Node 20 ou mais recente, e o [Claude Code](https://claude.com/claude-code) logado na sua conta.

```bash
./scripts/bootstrap.sh      # instala dependências e cria app_data/perfil.json
claude auth login           # uma vez; usa a sua conta Claude (Pro/Max)
./scripts/start.sh          # abre em http://127.0.0.1:8765
```

Para abrir com um clique, `./scripts/instalar_atalho.sh` cria o item **Lâmina** no menu de aplicativos: ele sobe o servidor em segundo plano e abre o navegador. Para encerrar o servidor, use `./scripts/parar.sh`.

O Preceptor só trabalha enquanto o servidor estiver rodando. Para mantê-lo sempre ligado, inclusive depois de reiniciar o computador, há um script opcional: `./scripts/instalar_servico.sh` cria um serviço de usuário do systemd. Para desfazer, use `./scripts/instalar_servico.sh --remover`.

Para desenvolver, `./scripts/dev.sh` sobe o backend com reload e o Vite com hot reload em http://127.0.0.1:5173.

Testes do backend (não gastam tokens, usam um runner falso):

```bash
cd backend && uv run pytest
```

## Como funciona

- **Domínio:**
  - correto vale 1, parcial vale 0,5 e incorreto vale 0;
  - o domínio usa a última tentativa de cada questão;
  - **acerto marcado como "chute" não conta para domínio**;
  - dominado = domínio ≥ 80% com todas as questões do tema respondidas. Você pode sobrescrever manualmente.
- **Prioridade de um tema** = prevalência na banca (com peso maior para provas recentes) × lacuna de domínio × peso do coach.
- **Flashcards:** repetição espaçada com FSRS; nenhum intervalo passa da data da prova.
- **Simulado:** 50 questões, 10 por área na ordem do caderno, cronometrado. A correção é feita em lote no fim.
- **Busca** local no banco de questões, **blocos de imagens** (as 117 questões com imagem) e **meta diária** no painel.
- **Ferramentas das instâncias do Claude:**
  - WebSearch e WebFetch, e captura de documentos inteiros para a biblioteca;
  - Read, Grep e Glob no próprio caderno, na biblioteca e no banco de questões; Write e Edit só no próprio caderno;
  - um **terminal isolado** com bubblewrap: o caderno do agente é o `/trabalho`; a biblioteca, o banco de questões e um snapshot dos seus dados ficam somente leitura. Esse terminal não tem internet nem acesso à sua home, o que protege contra instruções maliciosas vindas de páginas da web.
  - A captura só aceita endereços públicos (http/https): rede local e loopback são bloqueados a cada redirecionamento.
  - O Preceptor e o tutor também agem no app (blocos, flashcards, missões, agenda, avisos). Toda ação fica registrada e pode ser desfeita.
- **Segundo plano:** a cada 5 minutos, um ciclo sem custo de tokens confere os sinais (meta do dia, flashcards, agenda, ritmo) e envia lembretes no desktop e no sino do app. Quando há motivo, ele acorda o Preceptor ou executa a próxima tarefa da fila.
  - O segundo plano respeita um orçamento diário (em tokens efetivos, com a leitura de cache valendo 1/10) e para quando a janela do plano está apertada.
  - Em *Ajustes* você define o orçamento, os horários e o silêncio noturno, e pode pausá-lo.
- **Economia de tokens:**
  - o app chama o CLI isolado (`setting_sources=[]`, sem plugins, hooks ou MCPs pessoais) e com prompt de sistema enxuto;
  - cada chamada aparece em *Ajustes → Uso*.

## Estrutura

```
banco_questoes/   provas, gabaritos e imagens (somente leitura)
curadoria/        temas, classificação e adaptação das MC (gerados com o Claude, revisáveis na página Curadoria)
backend/          FastAPI + SQLite + claude-agent-sdk (lamina/)
frontend/         React + TypeScript + Vite + Tailwind
scripts/          bootstrap, start, dev, curadoria
app_data/         SEUS dados (banco, perfil, biblioteca, cadernos dos agentes): fora do git
```

Para refazer a curadoria (gasta tokens):

```bash
uv run --project backend python scripts/curadoria.py temas --refazer
uv run --project backend python scripts/curadoria.py adaptar --refazer
```

## Privacidade

Tudo o que é pessoal fica em `app_data/`, que está no `.gitignore`: desempenho, respostas, chats, flashcards, perfil, especialidade-alvo, a biblioteca e os cadernos dos agentes. A biblioteca fica fora do git porque documentos de sociedades médicas têm direitos autorais. O repositório guarda apenas código, prompts e a curadoria derivada das provas.

O conteúdo das provas pertence à Unicamp (Comvest/FCM) e aqui foi apenas convertido de formato, para estudo pessoal.
