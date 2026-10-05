// Cliente da API da Lâmina (FastAPI em 127.0.0.1:8765; o Vite faz proxy de /api e /imagens).

export type Veredito = 'pendente' | 'correto' | 'parcial' | 'incorreto' | 'erro'
export type Confianca = 'certeza' | 'duvida' | 'chute'
export type StatusTema = 'nao_iniciado' | 'em_progresso' | 'dominado'

export interface Tentativa {
  id: number
  questao_id: string
  bloco_id: number | null
  resposta: string
  confianca: Confianca
  veredito: Veredito
  fonte_veredito: 'llm' | 'manual' | null
  justificativa: string | null
  faltou: string | null
  resposta_modelo: string | null
  adendo: string | null
  tempo_seg: number | null
  criado_em: string
  julgado_em: string | null
}

export interface Gabarito {
  resposta_esperada: string | null
  aceitaveis: string[]
  ampliado: boolean
  adaptada: boolean
  nota_atualizacao: string | null
  letra_original: string | null
  alternativas_originais: Record<string, string> | null
  enunciado_original: string | null
}

export interface Imagem {
  url: string
  legenda: string | null
  rotulo: string | null
}

export interface Questao {
  id: string
  prova_id: string
  processo: number
  turno: string | null
  numero: number
  area: string
  tema_id: string
  tema_nome: string | null
  subtopico: string | null
  tipo_cognitivo: string | null
  formato_original: 'resposta_curta' | 'multipla_escolha'
  adaptada: boolean
  alternativas_provisorias: Record<string, string> | null
  enunciado_compartilhado: string | null
  enunciado: string
  imagens: Imagem[]
  fonte: { pdf: string; pagina: number | null } | null
  anulada: boolean
  n_tentativas: number
  ultima_tentativa: Tentativa | null
  explicacao: { explicacao_md: string; fixada_em: string } | null
  gabarito: Gabarito | null
}

export interface Estatistica {
  total: number
  respondidas: number
  corretas: number
  parciais: number
  incorretas: number
  chutes: number
  acertos_no_chute: number
  cobertura: number
  aproveitamento_bruto: number | null
  aproveitamento_firme: number | null
  status: StatusTema
  status_manual: 'dominado' | 'nao_dominado' | null
  revisar: boolean
  ultima_atividade: string | null
  n_refazer: number
}

export interface Tema extends Estatistica {
  id: string
  area: string
  nome: string
  descricao: string | null
  peso_coach: number
  peso_motivo: string | null
  geral: boolean
  prevalencia: number
  prevalencia_norm: number
  prioridade: number
}

export interface AreaStat extends Estatistica {
  area: string
}

export interface Bloco {
  id: number
  nome: string
  tipo: 'tema' | 'custom' | 'coach' | 'refazer' | 'simulado'
  tema_id: string | null
  descricao: string | null
  criado_por: 'user' | 'coach'
  config: { duracao_min?: number }
  criado_em: string
  iniciado_em: string | null
  finalizado_em: string | null
  arquivado: number
  total?: number
  respondidas?: number
  estatistica?: Estatistica
  estatistica_no_bloco?: Estatistica
}

export interface BlocoDetalhe {
  bloco: Bloco
  questoes: { id: string; ordem: number; area: string; processo: number; respondida: boolean; veredito: Veredito | null; confianca: Confianca | null }[]
  respondidas: number
  estatistica: Estatistica | null
  estatistica_no_bloco: Estatistica | null
}

export interface Insight {
  id: number
  tipo: 'missao' | 'insight' | 'alerta' | 'analise'
  titulo: string
  conteudo_md: string
  payload_json: string
  criado_em: string
  arquivado: number
}

export interface Painel {
  dias_ate_prova: number
  data_prova: string
  nome: string
  totais: { tentativas: number; corretas: number; parciais: number; incorretas: number; chutes: number; questoes_distintas: number; hoje: number; questoes_banco: number }
  areas: AreaStat[]
  prioritarios: Tema[]
  revisar: Tema[]
  mapa: Pick<Tema, 'id' | 'nome' | 'area' | 'status' | 'aproveitamento_firme' | 'cobertura' | 'revisar' | 'prioridade' | 'total' | 'respondidas' | 'geral'>[]
  flashcards_vencidos: number
  missoes: Insight[]
  insights: Insight[]
  ultima_analise: Insight | null
  meta_diaria: number
  coach_sugerido: boolean
  tentativas_desde_analise: number
  serie: { dia: string; n: number; pontos: number }[]
  blocos_abertos: { id: number; nome: string; tipo: string; criado_por: string; total: number; respondidas: number }[]
}

export interface Flashcard {
  id: number
  questao_id: string | null
  tema_id: string | null
  tema_nome: string | null
  frente: string
  verso: string
  origem: string
  due: string
  suspenso: number
  criado_em: string
  estado: { state: number; stability: number | null; difficulty: number | null; last_review: string | null }
}

export interface MensagemChat {
  id: number
  papel: 'user' | 'assistant'
  conteudo: string
  atividades: string[]
  criado_em: string
}

export interface Chat {
  chat: { id: number; questao_id: string; session_id: string | null; modelo: string | null }
  mensagens: MensagemChat[]
}

export interface EventoTutor {
  tipo: 'texto' | 'atividade' | 'fim' | 'erro'
  delta?: string
  detalhe?: string
  texto?: string
  mensagem?: string
  mensagem_id?: number
  uso?: { total_tokens: number; custo_usd: number }
}

export interface Ajustes {
  modelos: Record<string, string>
  esforco: Record<string, string>
  correcao_automatica: boolean
  coach_automatico: boolean
  coach_min_tentativas_novas: number
  simulado_duracao_min: number
  meta_diaria: number
  aviso_tokens_dia: number
}

export interface Perfil {
  nome: string
  especialidade_alvo: string
  data_prova: string
  instituicao: string
}

export interface Uso {
  hoje: { papel: string; chamadas: number; tokens: number; custo_usd: number }[]
  limite: { status: string | null; utilizacao: number | null; reseta_em: number | null; tipo: string | null; atualizado_em: string } | null
  recentes: { id: number; papel: string; modelo: string; status: string; tokens: number; custo_usd: number; duracao_ms: number | null; erro: string | null; criado_em: string }[]
  aviso_tokens_dia: number
}

export interface CoachEstado {
  rodando: boolean
  erro: string | null
  analises: Insight[]
  acoes: { id: number; tipo: string; descricao: string; criado_em: string; desfeita_em: string | null }[]
  insights: Insight[]
}

export interface QuestaoCuradoria {
  id: string
  area: string
  tema_id: string
  subtopico: string | null
  tipo_cognitivo: string | null
  formato_original: string
  adaptada: number
  enunciado: string
  enunciado_original: string
  alternativas: Record<string, string> | null
  letra_original: string | null
  resposta_esperada: string | null
  aceitaveis: string[]
}

export class ErroApi extends Error {
  status: number
  constructor(status: number, mensagem: string) {
    super(mensagem)
    this.status = status
  }
}

async function req<T>(metodo: string, url: string, corpo?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: metodo,
    headers: corpo !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: corpo !== undefined ? JSON.stringify(corpo) : undefined,
  })
  if (!r.ok) {
    let msg = r.statusText
    try {
      const j = await r.json()
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* corpo não-JSON */
    }
    throw new ErroApi(r.status, msg)
  }
  return r.json() as Promise<T>
}

export const api = {
  get: <T>(url: string) => req<T>('GET', url),
  post: <T>(url: string, corpo: unknown = {}) => req<T>('POST', url, corpo),
  put: <T>(url: string, corpo: unknown) => req<T>('PUT', url, corpo),
  patch: <T>(url: string, corpo: unknown) => req<T>('PATCH', url, corpo),
  del: <T>(url: string) => req<T>('DELETE', url),
}

/** POST com resposta em Server-Sent Events (o tutor). */
export async function transmitir(url: string, corpo: unknown, aoEvento: (ev: EventoTutor) => void, sinal?: AbortSignal) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corpo),
    signal: sinal,
  })
  if (!r.ok || !r.body) throw new ErroApi(r.status, r.statusText)
  const leitor = r.body.getReader()
  const dec = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await leitor.read()
    if (done) break
    buffer += dec.decode(value, { stream: true })
    let i: number
    while ((i = buffer.indexOf('\n\n')) >= 0) {
      const bloco = buffer.slice(0, i)
      buffer = buffer.slice(i + 2)
      const linha = bloco.split('\n').find((l) => l.startsWith('data: '))
      if (linha) aoEvento(JSON.parse(linha.slice(6)))
    }
  }
}

export const pct = (v: number | null | undefined, casas = 0) =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(casas)}%`

export const AREAS = ['Clínica Médica', 'Cirurgia', 'Pediatria', 'Ginecologia e Obstetrícia', 'Saúde Coletiva'] as const

export const AREA_CURTA: Record<string, string> = {
  'Clínica Médica': 'Clínica',
  Cirurgia: 'Cirurgia',
  Pediatria: 'Pediatria',
  'Ginecologia e Obstetrícia': 'GO',
  'Saúde Coletiva': 'Coletiva',
}
