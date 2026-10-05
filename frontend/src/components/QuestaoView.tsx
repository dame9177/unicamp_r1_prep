import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { BookMarked, Brain, ChevronDown, FlaskConical, Loader2, MessageSquareText, RotateCcw, ShieldQuestion } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Confianca, type Questao, type Tentativa } from '../api'
import GerarFlashcards from './GerarFlashcards'
import ImagensQuestao from './ImagemZoom'
import { Carregando, ErroCaixa, Markdown, Modal, ROTULO_CONFIANCA, VereditoBadge } from './ui'

const CONFIANCAS: { v: Confianca; tecla: string; cor: string }[] = [
  { v: 'certeza', tecla: '1', cor: 'data-[on=true]:border-certo data-[on=true]:text-certo data-[on=true]:bg-certo/10' },
  { v: 'duvida', tecla: '2', cor: 'data-[on=true]:border-parcial data-[on=true]:text-parcial data-[on=true]:bg-parcial/10' },
  { v: 'chute', tecla: '3', cor: 'data-[on=true]:border-errado data-[on=true]:text-errado data-[on=true]:bg-errado/10' },
]

const digitando = (e: KeyboardEvent) => {
  const el = e.target as HTMLElement
  return el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.isContentEditable
}

function ValoresReferencia({ provaId, aberto, aoFechar }: { provaId: string; aberto: boolean; aoFechar: () => void }) {
  const { data } = useQuery({
    queryKey: ['vr', provaId], enabled: aberto,
    queryFn: () => api.get<{ markdown: string | null }>(`/api/provas/${provaId}/valores-referencia`),
    staleTime: Infinity,
  })
  return (
    <Modal aberto={aberto} aoFechar={aoFechar} titulo="Valores de referência do caderno" largura="max-w-3xl">
      {data?.markdown ? <Markdown className="text-sm">{data.markdown}</Markdown> : <Carregando />}
    </Modal>
  )
}

export interface PropsQuestao {
  questaoId: string
  blocoId?: number
  simuladoAberto?: boolean
  aoAvancar?: () => void
  aoVoltar?: () => void
  tutorAberto: boolean
  alternarTutor: () => void
  aoResponder?: () => void
}

export default function QuestaoView({ questaoId, blocoId, simuladoAberto, aoAvancar, aoVoltar, tutorAberto, alternarTutor, aoResponder }: PropsQuestao) {
  const qc = useQueryClient()
  const chave = ['questao', questaoId, blocoId ?? null]
  const { data: q, error } = useQuery({
    queryKey: chave,
    queryFn: () => api.get<Questao>(`/api/questoes/${questaoId}${blocoId ? `?bloco_id=${blocoId}` : ''}`),
  })
  const [resposta, setResposta] = useState('')
  const [confianca, setConfianca] = useState<Confianca | null>(null)
  const [refazendo, setRefazendo] = useState(false)
  const [registrada, setRegistrada] = useState<Tentativa | null>(null)
  const [vr, setVr] = useState(false)
  const [flash, setFlash] = useState(false)
  const [contestar, setContestar] = useState(false)
  const inicio = useRef(Date.now())
  const caixa = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setResposta(''); setConfianca(null); setRefazendo(false); setRegistrada(null); setContestar(false)
    inicio.current = Date.now()
  }, [questaoId])

  const respondida = !!q?.gabarito && !refazendo
  const registradaEfetiva = registrada ?? (simuladoAberto && q?.ultima_tentativa?.bloco_id === blocoId ? q?.ultima_tentativa ?? null : null)
  const tentativaAtual = respondida ? q?.ultima_tentativa ?? null : null

  // Acompanha a correção enquanto estiver pendente.
  const { data: tAtual } = useQuery({
    queryKey: ['tentativa', tentativaAtual?.id],
    enabled: !!tentativaAtual,
    initialData: tentativaAtual ?? undefined,
    queryFn: () => api.get<Tentativa>(`/api/tentativas/${tentativaAtual!.id}`),
    refetchInterval: (query) => (query.state.data?.veredito === 'pendente' ? 1500 : false),
  })

  useEffect(() => {
    if (tAtual && tAtual.veredito !== 'pendente') {
      qc.invalidateQueries({ queryKey: ['painel'] })
      qc.invalidateQueries({ queryKey: ['temas'] })
      if (blocoId) qc.invalidateQueries({ queryKey: ['bloco', blocoId] })
    }
  }, [tAtual?.veredito]) // eslint-disable-line react-hooks/exhaustive-deps

  const enviar = useMutation({
    mutationFn: () => api.post<{ tentativa: Tentativa }>('/api/tentativas', {
      questao_id: questaoId, resposta, confianca, bloco_id: blocoId ?? null,
      tempo_seg: Math.round((Date.now() - inicio.current) / 1000),
    }),
    onSuccess: async (r) => {
      setRefazendo(false)
      if (simuladoAberto) setRegistrada(r.tentativa)
      await qc.invalidateQueries({ queryKey: chave })
      if (blocoId) qc.invalidateQueries({ queryKey: ['bloco', blocoId] })
      aoResponder?.()
    },
  })

  const manual = useMutation({
    mutationFn: (veredito: string) => api.patch<Tentativa>(`/api/tentativas/${tAtual!.id}`, { veredito }),
    onSuccess: (t) => { qc.setQueryData(['tentativa', t.id], t); qc.invalidateQueries({ queryKey: chave }); setContestar(false) },
  })
  const rejulgar = useMutation({
    mutationFn: (revisao: boolean) => api.post(`/api/tentativas/${tAtual!.id}/rejulgar`, { revisao }),
    onSuccess: () => { qc.setQueryData(['tentativa', tAtual!.id], { ...tAtual!, veredito: 'pendente' }); setContestar(false) },
  })

  const podeEnviar = resposta.trim().length > 0 && confianca !== null && !enviar.isPending

  const teclas = useCallback((e: KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && podeEnviar && !respondida) { e.preventDefault(); enviar.mutate(); return }
    if (e.altKey && ['1', '2', '3'].includes(e.key)) { e.preventDefault(); setConfianca(CONFIANCAS[Number(e.key) - 1].v); return }
    if (digitando(e) || e.ctrlKey || e.metaKey || e.altKey) return
    if ((e.key === 'j' || e.key === 'ArrowRight') && aoAvancar) aoAvancar()
    else if ((e.key === 'k' || e.key === 'ArrowLeft') && aoVoltar) aoVoltar()
    else if (e.key === 't') alternarTutor()
    else if (['1', '2', '3'].includes(e.key) && !respondida) setConfianca(CONFIANCAS[Number(e.key) - 1].v)
  }, [podeEnviar, respondida, aoAvancar, aoVoltar, alternarTutor, enviar])

  useEffect(() => {
    window.addEventListener('keydown', teclas)
    return () => window.removeEventListener('keydown', teclas)
  }, [teclas])

  if (error) return <ErroCaixa erro={error} />
  if (!q) return <Carregando />

  const g = q.gabarito
  return (
    <article className="entrar">
      {/* Metadados */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <span className="chip !text-texto">{q.area}</span>
        {q.tema_nome && <span className="chip">{q.tema_nome}</span>}
        <span className="chip num">{q.processo} · {q.turno?.replace(/ \(.*\)/, '')} · Q{q.numero}</span>
        {q.formato_original === 'multipla_escolha' && <span className="chip text-hema border-hema/40">{q.adaptada ? 'MC adaptada para discursiva' : 'MC (adaptação provisória)'}</span>}
        {q.n_tentativas > 0 && <span className="chip">{q.n_tentativas}ª vez vista</span>}
        <span className="flex-1" />
        <button className="btn btn-fantasma !py-1 !text-xs" onClick={() => setVr(true)}><FlaskConical className="size-3.5" /> Valores de referência</button>
        <button className={clsx('btn !py-1 !text-xs', tutorAberto && '!border-hema')} onClick={alternarTutor}>
          <MessageSquareText className="size-3.5" /> Tutor <kbd>T</kbd>
        </button>
      </div>

      {q.enunciado_compartilhado && (
        <div className="border-l-2 border-eosina/70 pl-4 mb-4">
          <p className="text-[11px] uppercase tracking-wider text-eosina/80 mb-1">Caso compartilhado</p>
          <Markdown className="text-texto/90">{q.enunciado_compartilhado}</Markdown>
        </div>
      )}
      <Markdown className="text-[1.02rem]">{q.enunciado}</Markdown>
      <ImagensQuestao imagens={q.imagens} />
      {q.alternativas_provisorias && (
        <div className="cartao p-4 my-4">
          <p className="text-[11px] text-apagado mb-2">Alternativas originais (esta questão ainda aguarda adaptação; responda por extenso):</p>
          {Object.entries(q.alternativas_provisorias).map(([k, v]) => <p key={k} className="text-sm"><b className="text-hema">{k.toUpperCase()})</b> {v}</p>)}
        </div>
      )}

      {/* Resposta */}
      {!respondida && !registradaEfetiva && (
        <section className="mt-6">
          <textarea
            ref={caixa} autoFocus value={resposta} onChange={(e) => setResposta(e.target.value)} rows={3}
            className="campo text-base" placeholder="Sua resposta curta, como escreveria na prova…"
          />
          <div className="flex flex-wrap items-center gap-2 mt-3">
            <span className="text-xs text-apagado mr-1">Confiança:</span>
            {CONFIANCAS.map((c) => (
              <button key={c.v} data-on={confianca === c.v} onClick={() => setConfianca(c.v)} className={clsx('btn !py-1.5', c.cor)}>
                {ROTULO_CONFIANCA[c.v]} <kbd>{c.tecla}</kbd>
              </button>
            ))}
            <span className="flex-1" />
            <button className="btn btn-primario" disabled={!podeEnviar} onClick={() => enviar.mutate()}>
              {enviar.isPending ? <Loader2 className="size-4 animate-spin" /> : null} Responder <kbd className="!bg-transparent !text-white/70 !border-white/30">Ctrl ↵</kbd>
            </button>
          </div>
          {!confianca && resposta.trim() && <p className="text-[11px] text-apagado mt-2">Marque a confiança — acertos no chute não contam para domínio.</p>}
          <ErroCaixa erro={enviar.error} />
        </section>
      )}

      {registradaEfetiva && (
        <section className="cartao p-5 mt-6">
          <p className="text-sm">Resposta registrada. O gabarito e a correção aparecem ao finalizar o simulado.</p>
          <p className="text-sm text-suave mt-2 italic">“{registradaEfetiva.resposta}”</p>
          {aoAvancar && <button className="btn btn-primario mt-4" onClick={aoAvancar}>Próxima <kbd className="!bg-transparent !text-white/70">J</kbd></button>}
        </section>
      )}

      {respondida && g && tAtual && (
        <section className="mt-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="cartao p-5">
              <p className="text-[11px] uppercase tracking-wider text-apagado mb-2">Sua resposta · {ROTULO_CONFIANCA[tAtual.confianca]}</p>
              <p className="text-[0.97rem] whitespace-pre-wrap">{tAtual.resposta}</p>
            </div>
            <div className="cartao p-5 border-hema/40">
              <p className="text-[11px] uppercase tracking-wider text-apagado mb-2 flex items-center gap-1.5">
                <BookMarked className="size-3.5" /> {g.adaptada ? 'Gabarito (adaptado da MC)' : 'Gabarito oficial'}
                {g.ampliado && <span className="chip !text-[10px] text-parcial border-parcial/40">ampliado após recursos</span>}
              </p>
              <Markdown className="!text-[0.95rem]">{g.resposta_esperada ?? '—'}</Markdown>
              {g.aceitaveis.length > 0 && <p className="text-xs text-suave mt-2">Também pontua: {g.aceitaveis.join('; ')}</p>}
              {g.nota_atualizacao && (
                <p className="text-xs text-parcial mt-3 rounded-lg border border-parcial/30 bg-parcial/5 px-3 py-2">⚠ Atualização: {g.nota_atualizacao}</p>
              )}
              {g.alternativas_originais && (
                <details className="mt-3 text-xs text-suave">
                  <summary className="cursor-pointer">Questão original (múltipla escolha)</summary>
                  {g.enunciado_original && <p className="mt-2">{g.enunciado_original}</p>}
                  {Object.entries(g.alternativas_originais).map(([k, v]) => (
                    <p key={k} className={clsx('mt-1', k.toUpperCase() === g.letra_original && 'text-certo')}>{k.toUpperCase()}) {v}</p>
                  ))}
                </details>
              )}
            </div>
          </div>

          <div className={clsx('cartao p-5', tAtual.veredito === 'correto' && 'border-certo/40', tAtual.veredito === 'incorreto' && 'border-errado/40', tAtual.veredito === 'parcial' && 'border-parcial/40')}>
            <div className="flex items-center gap-3">
              <VereditoBadge v={tAtual.veredito} grande />
              {tAtual.fonte_veredito && <span className="text-[11px] text-apagado">{tAtual.fonte_veredito === 'manual' ? 'corrigido por você' : 'corrigido pelo Claude conforme o gabarito'}</span>}
              {tAtual.veredito === 'correto' && tAtual.confianca === 'chute' && <span className="chip text-parcial border-parcial/40">acerto no chute — não conta para domínio</span>}
              <span className="flex-1" />
              {tAtual.veredito !== 'pendente' && (
                <button className="btn btn-fantasma !py-1 !text-xs" onClick={() => setContestar((c) => !c)}>
                  <ShieldQuestion className="size-3.5" /> Contestar <ChevronDown className="size-3" />
                </button>
              )}
            </div>
            {tAtual.veredito === 'pendente' && <p className="text-sm text-suave mt-3 pulsar">Comparando sua resposta com o gabarito da banca…</p>}
            {tAtual.justificativa && <p className="text-sm mt-3">{tAtual.justificativa}</p>}
            {tAtual.faltou && <p className="text-sm text-suave mt-1.5"><b className="text-texto/80">Faltou:</b> {tAtual.faltou}</p>}
            {tAtual.resposta_modelo && <p className="text-sm text-suave mt-1.5"><b className="text-texto/80">Resposta que pontua:</b> {tAtual.resposta_modelo}</p>}
            {tAtual.adendo && (
              <div className="mt-3 rounded-lg border border-parcial/30 bg-parcial/5 px-3 py-2">
                <p className="text-[11px] uppercase tracking-wider text-parcial mb-1">Gabarito da época × recomendação atual</p>
                <Markdown className="!text-sm">{tAtual.adendo}</Markdown>
              </div>
            )}
            {(contestar || tAtual.veredito === 'erro') && (
              <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-borda">
                <span className="text-xs text-apagado self-center">Marcar como:</span>
                {(['correto', 'parcial', 'incorreto'] as const).map((v) => (
                  <button key={v} className="btn !py-1 !text-xs" onClick={() => manual.mutate(v)}>{v}</button>
                ))}
                <span className="flex-1" />
                <button className="btn !py-1 !text-xs" onClick={() => rejulgar.mutate(tAtual.veredito !== 'erro')}>
                  {tAtual.veredito === 'erro' ? 'Tentar corrigir de novo' : 'Rejulgar pela literatura atual'}
                </button>
              </div>
            )}
          </div>

          {q.explicacao && (
            <details className="cartao p-5" open>
              <summary className="cursor-pointer text-sm font-medium flex items-center gap-2"><BookMarked className="size-4 text-eosina" /> Explicação fixada</summary>
              <Markdown className="mt-3 text-[0.93rem]">{q.explicacao.explicacao_md}</Markdown>
            </details>
          )}

          <div className="flex flex-wrap gap-2">
            <button className="btn" onClick={alternarTutor}><MessageSquareText className="size-4" /> Perguntar ao tutor</button>
            <button className="btn" onClick={() => setFlash(true)}><Brain className="size-4" /> Gerar flashcards</button>
            <button className="btn btn-fantasma" onClick={() => { setRefazendo(true); setResposta('') ; setConfianca(null); inicio.current = Date.now() }}>
              <RotateCcw className="size-4" /> Responder de novo
            </button>
            <span className="flex-1" />
            {aoAvancar && <button className="btn btn-primario" onClick={aoAvancar}>Próxima <kbd className="!bg-transparent !text-white/70">J</kbd></button>}
          </div>
        </section>
      )}

      <ValoresReferencia provaId={q.prova_id} aberto={vr} aoFechar={() => setVr(false)} />
      <GerarFlashcards questaoId={q.id} aberto={flash} aoFechar={() => setFlash(false)} />
    </article>
  )
}
