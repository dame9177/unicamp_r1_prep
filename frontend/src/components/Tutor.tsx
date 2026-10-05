import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Database, Globe, Library, Loader2, NotebookPen, Pin, RotateCcw, Send, Square, SquareTerminal, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, transmitir, type Chat } from '../api'
import { Markdown } from './ui'

export function IconeAtividade({ texto }: { texto: string }) {
  const cls = 'size-3 shrink-0'
  if (texto.startsWith('Biblioteca')) return <Library className={clsx(cls, 'text-certo')} />
  if (texto.includes('na web')) return <Globe className={clsx(cls, 'text-hema')} />
  if (texto.startsWith('Caderno') || texto.startsWith('Procurando') || texto.startsWith('Listando')) return <NotebookPen className={clsx(cls, 'text-eosina')} />
  if (texto.startsWith('Terminal')) return <SquareTerminal className={clsx(cls, 'text-parcial')} />
  return <Database className={clsx(cls, 'text-suave')} />
}

function Atividades({ itens }: { itens: string[] }) {
  if (!itens.length) return null
  const bib = itens.filter((a) => a.startsWith('Biblioteca')).length
  const web = itens.filter((a) => a.includes('na web')).length
  return (
    <details className="mb-1.5 group/at">
      <summary className="text-[11px] text-apagado cursor-pointer list-none hover:text-suave">
        {itens.length} consulta(s){bib ? ` · ${bib} na biblioteca` : ''}{web ? ` · ${web} na web` : ''} <span className="group-open/at:hidden">▸</span><span className="hidden group-open/at:inline">▾</span>
      </summary>
      <ul className="mt-1 space-y-0.5">
        {itens.map((a, i) => <li key={i} className="text-[11px] text-suave flex items-start gap-1.5"><IconeAtividade texto={a} /><span className="break-all">{a}</span></li>)}
      </ul>
    </details>
  )
}

const ATALHOS_PRECEPTOR = [
  'Como estou indo? Faça um balanço franco, com números.',
  'Monte meu plano de estudo até a prova.',
  'Quais temas devo priorizar esta semana e por quê?',
  'O que a biblioteca ainda não cobre dos meus temas mais fracos?',
]

const ATALHOS = [
  'Explique a questão inteira e o raciocínio que a banca espera.',
  'Por que minha resposta não pontuou? O que faltou?',
  'Quais os diagnósticos diferenciais e como distingui-los?',
  'Quais as pegadinhas desse tema em provas?',
  'O gabarito ainda vale pelas diretrizes atuais?',
]

export default function Tutor({ questaoId, chatId, aoFechar, inteiro, agente = 'tutor' }: {
  questaoId?: string
  chatId?: number
  aoFechar?: () => void
  inteiro?: boolean
  agente?: 'tutor' | 'preceptor'
}) {
  const preceptor = agente === 'preceptor'
  const atalhos = preceptor ? ATALHOS_PRECEPTOR : questaoId ? ATALHOS : []
  const qc = useQueryClient()
  const chave = questaoId ? ['chat', questaoId] : ['chat-geral', chatId]
  const { data } = useQuery({
    queryKey: chave,
    queryFn: () => (questaoId ? api.post<Chat>(`/api/questoes/${questaoId}/chat`) : api.get<Chat>(`/api/chats/${chatId}`)),
  })
  const [texto, setTexto] = useState('')
  const [pergunta, setPergunta] = useState<string | null>(null)
  const [parcial, setParcial] = useState('')
  const [atividades, setAtividades] = useState<string[]>([])
  const [erro, setErro] = useState<string | null>(null)
  const [uso, setUso] = useState<string | null>(null)
  const abortar = useRef<AbortController | null>(null)
  const fim = useRef<HTMLDivElement>(null)
  const transmitindo = pergunta !== null

  useEffect(() => { fim.current?.scrollIntoView({ behavior: 'smooth' }) }, [data?.mensagens.length, parcial, atividades.length])
  useEffect(() => () => abortar.current?.abort(), [])

  async function enviar(msg: string) {
    if (!data || !msg.trim() || transmitindo) return
    setPergunta(msg); setParcial(''); setAtividades([]); setErro(null); setTexto('')
    abortar.current = new AbortController()
    try {
      await transmitir(`/api/chats/${data.chat.id}/mensagens`, { texto: msg }, (ev) => {
        if (ev.tipo === 'texto') setParcial((p) => p + (ev.delta ?? ''))
        if (ev.tipo === 'atividade') setAtividades((a) => [...a, ev.detalhe ?? ''])
        if (ev.tipo === 'erro') setErro(ev.mensagem ?? 'erro')
        if (ev.tipo === 'fim' && ev.uso) setUso(`${(ev.uso.total_tokens / 1000).toFixed(1)}k tokens`)
      }, abortar.current.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setErro((e as Error).message)
    }
    await qc.invalidateQueries({ queryKey: chave })
    qc.invalidateQueries({ queryKey: ['uso'] })
    qc.invalidateQueries({ queryKey: ['chats-gerais'] })
    if (preceptor) { qc.invalidateQueries({ queryKey: ['preceptor'] }); qc.invalidateQueries({ queryKey: ['painel'] }); qc.invalidateQueries({ queryKey: ['agenda'] }) }
    setPergunta(null); setParcial(''); setAtividades([])
  }

  async function novaConversa() {
    const novo = await api.post<Chat>(`/api/questoes/${questaoId}/chat?novo=true`)
    qc.setQueryData(chave, novo)
    setUso(null)
  }

  async function fixar(mensagemId: number) {
    if (!questaoId) return
    await api.put(`/api/questoes/${questaoId}/explicacao`, { mensagem_id: mensagemId })
    qc.invalidateQueries({ queryKey: ['questao', questaoId] })
  }

  const msgs = data?.mensagens ?? []
  return (
    <aside className={clsx('flex flex-col h-full', inteiro ? 'flex-1 min-w-0' : 'w-[460px] shrink-0 border-l border-borda bg-lamina/80 backdrop-blur')}>
      <header className="flex items-center gap-2 px-4 py-3 border-b border-borda">
        <div className="flex-1">
          <p className="titulo text-lg leading-none">{preceptor ? 'Preceptor' : 'Tutor'}</p>
          <p className="text-[11px] text-apagado mt-1 flex items-center gap-1">
            {preceptor ? <><Database className="size-3" /> estratégia · métricas · plano</> : <><Library className="size-3" /> biblioteca + literatura atual · caderno próprio</>}
          </p>
        </div>
        {uso && <span className="num text-[11px] text-apagado">{uso}</span>}
        {questaoId && <button className="btn btn-fantasma !p-1.5" title="Nova conversa" onClick={novaConversa} disabled={transmitindo}><RotateCcw className="size-4" /></button>}
        {aoFechar && <button className="btn btn-fantasma !p-1.5" title="Fechar (T)" onClick={aoFechar}><X className="size-4" /></button>}
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {msgs.length === 0 && !transmitindo && (
          <div className="space-y-2">
            <p className="text-sm text-suave">{preceptor ? 'Discuta estratégia, métricas e plano. Ele age no app quando você pedir.' : questaoId ? 'Pergunte o que quiser sobre esta questão.' : 'Tire qualquer dúvida de estudo.'} Nada é gasto até você enviar.</p>
            {atalhos.map((a) => (
              <button key={a} onClick={() => enviar(a)} className="block w-full text-left text-sm rounded-xl border border-borda px-3 py-2 hover:border-hema hover:bg-lamina-2 transition">
                {a}
              </button>
            ))}
          </div>
        )}
        {msgs.map((m) => (
          <div key={m.id} className={clsx(m.papel === 'user' ? 'ml-10' : '')}>
            {m.papel === 'user' ? (
              <p className="text-sm rounded-2xl rounded-br-sm bg-hema-escuro/70 border border-hema/30 px-3.5 py-2.5">{m.conteudo}</p>
            ) : (
              <div className="group">
                <Atividades itens={m.atividades} />
                <Markdown className="text-[0.92rem]">{m.conteudo}</Markdown>
                {questaoId && <button onClick={() => fixar(m.id)} className="mt-1 text-[11px] text-apagado hover:text-eosina inline-flex items-center gap-1 opacity-0 group-hover:opacity-100 transition">
                  <Pin className="size-3" /> Fixar como explicação da questão
                </button>}
              </div>
            )}
          </div>
        ))}
        {transmitindo && (
          <>
            <p className="ml-10 text-sm rounded-2xl rounded-br-sm bg-hema-escuro/70 border border-hema/30 px-3.5 py-2.5">{pergunta}</p>
            <div>
              {atividades.map((a, i) => (
                <p key={i} className="text-[11px] text-suave flex items-center gap-1.5"><IconeAtividade texto={a} /> <span className="truncate">{a}</span></p>
              ))}
              {parcial ? <Markdown className="text-[0.92rem]">{parcial}</Markdown> : (
                <p className="text-sm text-suave flex items-center gap-2 mt-1"><Loader2 className="size-4 animate-spin" /> pensando…</p>
              )}
            </div>
          </>
        )}
        {erro && <p className="text-sm text-errado">{erro}</p>}
        <div ref={fim} />
      </div>

      <footer className="p-3 border-t border-borda">
        <div className="flex gap-2 items-end">
          <textarea
            className="campo text-sm resize-none" rows={2} placeholder={preceptor ? 'Fale com o Preceptor… (Enter envia)' : 'Pergunte ao tutor… (Enter envia)'}
            value={texto} onChange={(e) => setTexto(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar(texto) } e.stopPropagation() }}
          />
          {transmitindo ? (
            <button className="btn !p-2.5" onClick={() => abortar.current?.abort()} title="Parar"><Square className="size-4" /></button>
          ) : (
            <button className="btn btn-primario !p-2.5" onClick={() => enviar(texto)} disabled={!texto.trim()} title="Enviar"><Send className="size-4" /></button>
          )}
        </div>
      </footer>
    </aside>
  )
}
