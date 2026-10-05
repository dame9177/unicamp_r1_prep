# Lâmina — estudo para o R1 de Acesso Direto da Unicamp

Lâmina é uma aplicação local para estudar para a prova de Residência Médica da Unicamp (Acesso Direto). O conteúdo vem das provas de 2022 a 2026: 650 questões, todas no formato atual de **resposta curta discursiva**. As antigas de múltipla escolha foram adaptadas.

O núcleo é humano: temas, blocos de questões, aproveitamento, e o tema é "dominado" quando o domínio chega a 80% ou mais. Sobre ele, o **Claude Code CLI** cumpre quatro papéis:

| Papel | O que faz | Quando roda |
|---|---|---|
| Juiz | Compara a sua resposta com o gabarito da banca. Se o gabarito puder estar desatualizado, um segundo estágio pesquisa a recomendação **vigente** do Ministério da Saúde, julga por ela e escreve um adendo ("gabarito da época × hoje") | A cada resposta (Haiku; Sonnet + web só quando necessário) |
| Tutor | Chat lateral (por questão) ou livre, que explica com busca na web em literatura brasileira atual. A primeira resposta sempre pesquisa | Só quando você pergunta |
| Flashcards | Gera cartões de revisão a partir da questão e do seu erro | Só quando você pede |
| Coach | Lê o seu desempenho, monta missões, cria blocos e ajusta prioridades (tudo pode ser desfeito) | Só quando você pede (ou 1×/dia, se ativar) |

## Como rodar

Requisitos: Linux ou macOS, [uv](https://docs.astral.sh/uv/), Node 20 ou mais recente, e o [Claude Code](https://claude.com/claude-code) logado na sua conta.

```bash
./scripts/bootstrap.sh      # instala dependências e cria app_data/perfil.json
claude auth login           # uma vez; usa a sua conta Claude (Pro/Max)
./scripts/start.sh          # abre em http://127.0.0.1:8765
```

Para abrir com um clique, `./scripts/instalar_atalho.sh` cria o item **Lâmina** no menu de aplicativos: ele sobe o servidor em segundo plano e abre o navegador. Para encerrar o servidor, use `./scripts/parar.sh`.

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
  - WebSearch e WebFetch;
  - leitura do banco de questões;
  - um **terminal isolado** com bubblewrap: python3, grep e o banco de questões, mais um snapshot dos seus dados, todos somente leitura. Esse terminal não tem internet nem acesso à sua home, o que protege contra instruções maliciosas vindas de páginas da web.
  - O coach e o tutor também agem no app: criam blocos, flashcards e missões.
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
app_data/         SEUS dados (banco, perfil, sessões): fora do git
```

Para refazer a curadoria (gasta tokens):

```bash
uv run --project backend python scripts/curadoria.py temas --refazer
uv run --project backend python scripts/curadoria.py adaptar --refazer
```

## Privacidade

Tudo o que é pessoal fica em `app_data/`, que está no `.gitignore`: desempenho, respostas, chats, flashcards, perfil e especialidade-alvo. O repositório guarda apenas código, prompts e a curadoria derivada das provas.

O conteúdo das provas pertence à Unicamp (Comvest/FCM) e aqui foi apenas convertido de formato, para estudo pessoal.
