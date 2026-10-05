-- Esquema do banco local da Lâmina (SQLite). Idempotente: roda a cada inicialização.

CREATE TABLE IF NOT EXISTS temas (
  id              TEXT PRIMARY KEY,
  area            TEXT NOT NULL,
  nome            TEXT NOT NULL,
  descricao       TEXT,
  ordem           INTEGER NOT NULL DEFAULT 0,
  peso_coach      REAL NOT NULL DEFAULT 1.0,
  peso_motivo     TEXT,
  status_manual   TEXT CHECK (status_manual IN ('dominado', 'nao_dominado')),
  status_manual_em TEXT
);

CREATE TABLE IF NOT EXISTS questoes (
  id                      TEXT PRIMARY KEY,
  prova_id                TEXT NOT NULL,
  processo                INTEGER NOT NULL,
  turno                   TEXT,
  tipo_prova              TEXT,
  numero                  INTEGER,
  area                    TEXT NOT NULL,
  formato_original        TEXT NOT NULL,
  enunciado_compartilhado TEXT,
  enunciado               TEXT NOT NULL,   -- versão efetiva (discursiva)
  enunciado_original      TEXT NOT NULL,
  alternativas_json       TEXT,
  letra_original          TEXT,
  resposta_esperada       TEXT,            -- versão efetiva (texto da banca ou adaptação)
  aceitaveis_json         TEXT,
  ampliado                INTEGER NOT NULL DEFAULT 0,
  anulada                 INTEGER NOT NULL DEFAULT 0,
  adaptada                INTEGER NOT NULL DEFAULT 0,
  obs_curadoria           TEXT,
  imagens_json            TEXT NOT NULL DEFAULT '[]',
  fonte_json              TEXT,
  tema_id                 TEXT REFERENCES temas(id),
  temas_secundarios_json  TEXT NOT NULL DEFAULT '[]',
  subtopico               TEXT,
  tipo_cognitivo          TEXT,
  peso_prevalencia        REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_questoes_tema ON questoes(tema_id);
CREATE INDEX IF NOT EXISTS ix_questoes_area ON questoes(area);

CREATE TABLE IF NOT EXISTS questao_notas (
  questao_id    TEXT PRIMARY KEY REFERENCES questoes(id),
  explicacao_md TEXT,
  fixada_em     TEXT
);

CREATE TABLE IF NOT EXISTS blocos (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  nome          TEXT NOT NULL,
  tipo          TEXT NOT NULL CHECK (tipo IN ('tema', 'custom', 'coach', 'refazer', 'simulado')),
  tema_id       TEXT REFERENCES temas(id),
  descricao     TEXT,
  criado_por    TEXT NOT NULL DEFAULT 'user' CHECK (criado_por IN ('user', 'coach')),
  config_json   TEXT NOT NULL DEFAULT '{}',
  criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  iniciado_em   TEXT,
  finalizado_em TEXT,
  arquivado     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bloco_questoes (
  bloco_id   INTEGER NOT NULL REFERENCES blocos(id) ON DELETE CASCADE,
  questao_id TEXT NOT NULL REFERENCES questoes(id),
  ordem      INTEGER NOT NULL,
  PRIMARY KEY (bloco_id, questao_id)
);

CREATE TABLE IF NOT EXISTS tentativas (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  questao_id      TEXT NOT NULL REFERENCES questoes(id),
  bloco_id        INTEGER REFERENCES blocos(id) ON DELETE SET NULL,
  resposta        TEXT NOT NULL,
  confianca       TEXT NOT NULL CHECK (confianca IN ('certeza', 'duvida', 'chute')),
  veredito        TEXT NOT NULL DEFAULT 'pendente'
                  CHECK (veredito IN ('pendente', 'correto', 'parcial', 'incorreto', 'erro')),
  fonte_veredito  TEXT CHECK (fonte_veredito IN ('llm', 'manual')),
  justificativa   TEXT,
  faltou          TEXT,
  resposta_modelo TEXT,
  adendo          TEXT,
  tempo_seg       INTEGER,
  criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  julgado_em      TEXT
);
CREATE INDEX IF NOT EXISTS ix_tentativas_questao ON tentativas(questao_id, criado_em);
CREATE INDEX IF NOT EXISTS ix_tentativas_bloco ON tentativas(bloco_id);

CREATE TABLE IF NOT EXISTS flashcards (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  questao_id  TEXT REFERENCES questoes(id),
  tema_id     TEXT REFERENCES temas(id),
  frente      TEXT NOT NULL,
  verso       TEXT NOT NULL,
  origem      TEXT NOT NULL DEFAULT 'manual' CHECK (origem IN ('llm', 'manual', 'coach', 'tutor')),
  fsrs_json   TEXT NOT NULL,
  due         TEXT NOT NULL,
  suspenso    INTEGER NOT NULL DEFAULT 0,
  criado_em   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS ix_flashcards_due ON flashcards(suspenso, due);

CREATE TABLE IF NOT EXISTS revisoes (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  flashcard_id INTEGER NOT NULL REFERENCES flashcards(id) ON DELETE CASCADE,
  nota         INTEGER NOT NULL CHECK (nota BETWEEN 1 AND 4),
  revisado_em  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS chats (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  questao_id    TEXT REFERENCES questoes(id),
  session_id    TEXT,
  modelo        TEXT,
  criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  atualizado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS ix_chats_questao ON chats(questao_id);

CREATE TABLE IF NOT EXISTS mensagens (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id      INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  papel        TEXT NOT NULL CHECK (papel IN ('user', 'assistant')),
  conteudo     TEXT NOT NULL,
  atividades_json TEXT NOT NULL DEFAULT '[]',
  job_id       INTEGER REFERENCES llm_jobs(id),
  criado_em    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS coach_insights (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo         TEXT NOT NULL CHECK (tipo IN ('missao', 'insight', 'alerta', 'analise')),
  titulo       TEXT NOT NULL,
  conteudo_md  TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  job_id       INTEGER REFERENCES llm_jobs(id),
  criado_em    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  arquivado    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS coach_acoes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id        INTEGER REFERENCES llm_jobs(id),
  tipo          TEXT NOT NULL,
  descricao     TEXT NOT NULL,
  payload_json  TEXT NOT NULL DEFAULT '{}',
  desfazer_json TEXT NOT NULL DEFAULT '{}',
  criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  desfeita_em   TEXT
);

CREATE TABLE IF NOT EXISTS llm_jobs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  papel         TEXT NOT NULL,
  modelo        TEXT,
  ref           TEXT,
  status        TEXT NOT NULL DEFAULT 'rodando' CHECK (status IN ('rodando', 'ok', 'erro', 'cancelado')),
  input_tokens  INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read    INTEGER NOT NULL DEFAULT 0,
  cache_write   INTEGER NOT NULL DEFAULT 0,
  custo_usd     REAL NOT NULL DEFAULT 0,
  duracao_ms    INTEGER,
  erro          TEXT,
  criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  finalizado_em TEXT
);

CREATE TABLE IF NOT EXISTS ajustes (
  chave      TEXT PRIMARY KEY,
  valor_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS limite_uso (
  id            INTEGER PRIMARY KEY CHECK (id = 1),
  status        TEXT,
  utilizacao    REAL,
  reseta_em     INTEGER,
  tipo          TEXT,
  atualizado_em TEXT
);

-- ------------------------------------------------------------------------------------------------
-- Biblioteca compartilhada pelos agentes (documentos integrais + notas verificadas)
-- Os arquivos ficam em app_data/biblioteca/; aqui ficam metadados e o índice de busca.
-- ------------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS biblioteca (
  id             TEXT PRIMARY KEY,
  tipo           TEXT NOT NULL CHECK (tipo IN ('documento', 'nota')),
  titulo         TEXT NOT NULL,
  orgao          TEXT,
  ano            INTEGER,
  categoria      TEXT,
  confiabilidade TEXT NOT NULL DEFAULT 'literatura'
                 CHECK (confiabilidade IN ('oficial', 'sociedade', 'literatura', 'nota')),
  status         TEXT NOT NULL DEFAULT 'vigente' CHECK (status IN ('vigente', 'substituido', 'em_revisao')),
  status_motivo  TEXT,
  url            TEXT,
  formato        TEXT,
  paginas        INTEGER,
  caracteres     INTEGER NOT NULL DEFAULT 0,
  sha256         TEXT,
  temas_json     TEXT NOT NULL DEFAULT '[]',
  fontes_json    TEXT NOT NULL DEFAULT '[]',
  resumo         TEXT,
  criado_por     TEXT NOT NULL,
  acessos        INTEGER NOT NULL DEFAULT 0,
  criado_em      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  atualizado_em  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS ix_biblioteca_url ON biblioteca(url);

CREATE VIRTUAL TABLE IF NOT EXISTS biblioteca_fts USING fts5(
  doc_id UNINDEXED, local UNINDEXED, titulo, texto, tokenize = 'unicode61 remove_diacritics 2'
);

-- ------------------------------------------------------------------------------------------------
-- Orquestração (Preceptor): fila de tarefas dos agentes, avisos, agenda e estado interno
-- ------------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tarefas (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  agente       TEXT NOT NULL,
  titulo       TEXT NOT NULL,
  instrucoes   TEXT NOT NULL,
  prioridade   INTEGER NOT NULL DEFAULT 2 CHECK (prioridade BETWEEN 1 AND 3),
  status       TEXT NOT NULL DEFAULT 'pendente'
               CHECK (status IN ('pendente', 'executando', 'concluida', 'erro', 'cancelada')),
  criado_por   TEXT NOT NULL DEFAULT 'preceptor',
  resultado    TEXT,
  job_id       INTEGER REFERENCES llm_jobs(id),
  tentativas   INTEGER NOT NULL DEFAULT 0,
  criado_em    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  iniciado_em  TEXT,
  concluido_em TEXT
);

CREATE TABLE IF NOT EXISTS avisos (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo        TEXT NOT NULL DEFAULT 'lembrete' CHECK (tipo IN ('lembrete', 'sugestao', 'alerta', 'relatorio')),
  titulo      TEXT NOT NULL,
  texto       TEXT NOT NULL DEFAULT '',
  link        TEXT,
  origem      TEXT NOT NULL DEFAULT 'preceptor',
  chave       TEXT,
  quando      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  status      TEXT NOT NULL DEFAULT 'agendado' CHECK (status IN ('agendado', 'entregue', 'lido', 'descartado')),
  entregue_em TEXT,
  criado_em   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_avisos_chave ON avisos(chave) WHERE chave IS NOT NULL;

CREATE TABLE IF NOT EXISTS agenda (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  dia       TEXT NOT NULL,
  titulo    TEXT NOT NULL,
  detalhe   TEXT,
  tipo      TEXT NOT NULL DEFAULT 'estudo'
            CHECK (tipo IN ('estudo', 'revisao', 'simulado', 'flashcards', 'leitura', 'descanso')),
  tema_id   TEXT REFERENCES temas(id),
  bloco_id  INTEGER REFERENCES blocos(id) ON DELETE SET NULL,
  minutos   INTEGER,
  status    TEXT NOT NULL DEFAULT 'planejado' CHECK (status IN ('planejado', 'feito', 'pulado')),
  origem    TEXT NOT NULL DEFAULT 'preceptor',
  criado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS ix_agenda_dia ON agenda(dia);

CREATE TABLE IF NOT EXISTS estado (
  chave      TEXT PRIMARY KEY,
  valor_json TEXT NOT NULL
);
