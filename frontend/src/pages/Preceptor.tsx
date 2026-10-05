import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Loader2, MessageSquarePlus, Pause, Play, Stethoscope, Undo2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type Chat, type PreceptorEstado } from '../api'
import Cadernos from '../components/Cadernos'
import ListaTarefas from '../components/Tarefas'
import Tutor from '../components/Tutor'
import { Barra, Cabecalho, Carregando, ErroCaixa, Markdown } from '../components/ui'

const ABAS = ['Rondas', 'Ações', 'Tarefas', 'Caderno'] as const

function haQuanto(iso: string | null) {
  if (!iso) return 'nunca'
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  return min < 1 ? 'agora' : min < 60 ? `há ${min} min` : `há ${Math.round(min / 60)} h`
}

export default function Preceptor() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [aba, setAba] = useState<(typeof ABAS)[number]>('Rondas')
  const [obs, setObs] = useState('')
  const { data } = useQuery({
    queryKey: ['preceptor'],
    queryFn: () => api.get<PreceptorEstado>('/api/preceptor'),
    refetchInterval: (q) => (q.state.data?.maestro.ocupado ? 4000 : 30_000),
  })
  const ronda = useMutation({
    mutationFn: () => api.post('/api/preceptor/ronda', { observacao: obs || null }),
    onSuccess: () => { setObs(''); qc.invalidateQueries({ queryKey: ['preceptor'] }); qc.invalidateQueries({ queryKey: ['avisos'] }) },
  })
  const pausa = useMutation({
    mutationFn: (horas: number) => api.post('/api/preceptor/pausa', { horas }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['preceptor'] }),
  })
  const desfazer = useMutation({
    mutationFn: (id: number) => api.post(`/api/preceptor/acoes/${id}/desfazer`),
    onSuccess: () => { for (const k of ['preceptor', 'painel', 'temas', 'agenda', 'avisos', 'tarefas']) qc.invalidateQueries({ queryKey: [k] }) },
  })
  const novoChat = useMutation({
    mutationFn: () => api.post<Chat>('/api/preceptor/chats'),
    onSuccess: (c) => { qc.invalidateQueries({ queryKey: ['preceptor'] }); setParams({ c: String(c.chat.id) }) },
  })
  // Quando um trabalho termina, várias telas mudam (missões, agenda, pesos, avisos).
  const ocupava = useRef(false)
  useEffect(() => {
    const ocupado = !!data?.maestro.ocupado
    if (ocupava.current && !ocupado) for (const k of ['painel', 'temas', 'agenda', 'avisos', 'tarefas', 'uso']) qc.invalidateQueries({ queryKey: [k] })
    ocupava.current = ocupado
  }, [data?.maestro.ocupado, qc])

  if (!data) return <Carregando />
  const { maestro: m, sinais: s } = data
  const sp = s.segundo_plano
  const pausado = !!s.pausado_ate && new Date(s.pausado_ate) > new Date()
  const chatAtual = params.get('c') ? Number(params.get('c')) : data.chats[0]?.id
  const [ultima, ...anteriores] = data.rondas

  return (
    <div className="max-w-7xl mx-auto px-8 py-8 entrar">
      <Cabecalho
        titulo={<span className="flex items-center gap-3"><Stethoscope className="size-7 text-eosina" /> Preceptor</span>}
        sub="Orquestra o seu estudo nos bastidores: rondas, agenda, avisos, biblioteca e os outros agentes. Tudo pode ser desfeito; marcar domínio continua sendo decisão sua."
      />

      <section className="cartao p-5 grid grid-cols-12 gap-6 items-center">
        <div className="col-span-5 flex items-start gap-3">
          <span className={clsx('size-2.5 rounded-full mt-1.5 shrink-0', m.ocupado ? 'bg-certo animate-pulse' : !m.ativo ? 'bg-apagado' : pausado || !sp.pode_rodar ? 'bg-parcial' : 'bg-hema')} />
          <div className="min-w-0">
            <p className="text-sm">
              {m.ocupado ? <>Trabalhando: <b>{m.ocupado}</b></> : !m.ativo ? 'Ciclo em segundo plano parado (o servidor foi iniciado sem ele).'
                : pausado ? `Pausado até ${new Date(s.pausado_ate!).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`
                : m.ultima_decisao ?? 'Aguardando a primeira verificação…'}
            </p>
            <p className="text-[11px] text-apagado mt-0.5">
              Verifica a cada {Math.round(m.intervalo_seg / 60)} min · última {haQuanto(m.ultimo_tick)} · {sp.pode_rodar ? 'segundo plano liberado' : sp.motivo}
            </p>
            {m.ultimo_erro && <p className="text-[11px] text-errado mt-1 truncate" title={m.ultimo_erro}>Último erro: {m.ultimo_erro}</p>}
          </div>
        </div>
        <div className="col-span-3">
          <div className="flex justify-between text-[11px] text-apagado mb-1.5">
            <span>Orçamento de segundo plano hoje</span>
            <span className="num">{(sp.gasto_hoje / 1000).toFixed(0)}k / {(sp.orcamento / 1000).toFixed(0)}k</span>
          </div>
          <Barra valor={sp.gasto_hoje / Math.max(1, sp.orcamento)} cor="bg-eosina" />
          <p className="text-[11px] text-apagado mt-1.5">{sp.rondas_hoje} ronda(s) hoje · {s.tarefas.pendentes} tarefa(s) na fila · biblioteca: {s.biblioteca.documentos} docs, {s.biblioteca.notas} notas</p>
        </div>
        <div className="col-span-4 flex flex-col gap-2">
          <div className="flex gap-2">
            <input className="campo text-sm" placeholder="Opcional: contexto para a ronda (“hoje só tenho 2h”)" value={obs} onChange={(e) => setObs(e.target.value)} />
            <button className="btn btn-primario shrink-0" disabled={!!m.ocupado || ronda.isPending} onClick={() => ronda.mutate()} title="Roda agora, fora do orçamento de segundo plano">
              {m.ocupado ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />} Ronda agora
            </button>
          </div>
          <div className="flex gap-2 justify-end">
            {pausado ? <button className="btn btn-fantasma text-xs" onClick={() => pausa.mutate(0)}><Play className="size-3.5" /> Retomar segundo plano</button>
              : <>
                <button className="btn btn-fantasma text-xs" onClick={() => pausa.mutate(2)}><Pause className="size-3.5" /> Pausar 2 h</button>
                <button className="btn btn-fantasma text-xs" onClick={() => pausa.mutate(24)}>Pausar 1 dia</button>
              </>}
          </div>
        </div>
        <div className="col-span-12 -mt-2"><ErroCaixa erro={ronda.error} /></div>
      </section>

      <div className="grid grid-cols-12 gap-6 mt-6">
        <section className="col-span-7 cartao p-0 overflow-hidden flex flex-col h-[74vh]">
          <div className="flex items-center gap-1.5 px-3 py-2 border-b border-borda overflow-x-auto">
            <button className="btn btn-fantasma !py-1 !px-2 text-xs shrink-0" onClick={() => novoChat.mutate()} disabled={novoChat.isPending}>
              <MessageSquarePlus className="size-3.5" /> Nova conversa
            </button>
            {data.chats.filter((c) => c.titulo || c.id === chatAtual).slice(0, 8).map((c) => (
              <button key={c.id} onClick={() => setParams({ c: String(c.id) })} title={c.titulo ?? ''}
                      className={clsx('text-xs rounded-lg px-2.5 py-1 shrink-0 max-w-44 truncate transition', c.id === chatAtual ? 'bg-hema-escuro/70 text-white' : 'text-suave hover:bg-lamina-2')}>
                {c.titulo || 'Nova conversa'}
              </button>
            ))}
          </div>
          {chatAtual ? <Tutor key={chatAtual} chatId={chatAtual} agente="preceptor" inteiro /> : (
            <div className="flex-1 grid place-items-center text-center px-8">
              <div>
                <p className="titulo text-xl">Converse com o Preceptor</p>
                <p className="text-sm text-suave mt-2 max-w-md">Estratégia, métricas, plano até a prova, prioridades. Ele lê todos os seus dados e age no app quando você pedir.</p>
                <button className="btn btn-primario mt-4" onClick={() => novoChat.mutate()}><MessageSquarePlus className="size-4" /> Começar</button>
              </div>
            </div>
          )}
        </section>

        <section className="col-span-5">
          <div className="flex gap-1 mb-3">
            {ABAS.map((a) => (
              <button key={a} onClick={() => setAba(a)} className={clsx('text-sm rounded-lg px-3 py-1.5 transition', aba === a ? 'bg-lamina-2 text-texto' : 'text-suave hover:text-texto')}>{a}</button>
            ))}
          </div>
          <div className="max-h-[70vh] overflow-y-auto pr-1">
            {aba === 'Rondas' && (
              <div className="space-y-3">
                {ultima ? (
                  <div className="cartao p-5">
                    <p className="text-[11px] uppercase tracking-wider text-apagado">{ultima.titulo}</p>
                    <Markdown className="mt-2 text-sm">{ultima.conteudo_md}</Markdown>
                  </div>
                ) : <p className="text-sm text-suave">Nenhuma ronda ainda. A primeira roda sozinha a partir do horário definido em Ajustes, ou clique em “Ronda agora”.</p>}
                {anteriores.map((r) => (
                  <details key={r.id} className="cartao p-4">
                    <summary className="cursor-pointer text-sm text-suave">{r.titulo}</summary>
                    <Markdown className="mt-2 text-sm">{r.conteudo_md}</Markdown>
                  </details>
                ))}
              </div>
            )}
            {aba === 'Ações' && (
              <div className="cartao divide-y divide-borda">
                {data.acoes.length === 0 && <p className="p-4 text-sm text-suave">Nenhuma ação ainda.</p>}
                {data.acoes.map((a) => (
                  <div key={a.id} className={clsx('px-4 py-3 flex items-start gap-3', a.desfeita_em && 'opacity-45')}>
                    <div className="flex-1">
                      <p className={clsx('text-sm', a.desfeita_em && 'line-through')}>{a.descricao}</p>
                      <p className="text-[11px] text-apagado">{new Date(a.criado_em).toLocaleString('pt-BR')}</p>
                    </div>
                    {!a.desfeita_em && <button className="btn btn-fantasma !p-1.5" title="Desfazer" onClick={() => desfazer.mutate(a.id)}><Undo2 className="size-4" /></button>}
                  </div>
                ))}
              </div>
            )}
            {aba === 'Tarefas' && <ListaTarefas />}
            {aba === 'Caderno' && <div className="cartao p-4"><Cadernos inicial="preceptor" fixo /></div>}
          </div>
        </section>
      </div>
    </div>
  )
}
