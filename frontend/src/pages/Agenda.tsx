import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Check, CornerUpRight, Plus, RotateCcw, Stethoscope, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type ItemAgenda, type Painel, type TipoAgenda } from '../api'
import { Cabecalho, Carregando, ErroCaixa } from '../components/ui'

const TIPOS: { id: TipoAgenda; rotulo: string; cor: string }[] = [
  { id: 'estudo', rotulo: 'Estudo', cor: 'text-hema border-hema/40 bg-hema/10' },
  { id: 'revisao', rotulo: 'Revisão', cor: 'text-parcial border-parcial/40 bg-parcial/10' },
  { id: 'simulado', rotulo: 'Simulado', cor: 'text-eosina border-eosina/40 bg-eosina/10' },
  { id: 'flashcards', rotulo: 'Flashcards', cor: 'text-certo border-certo/40 bg-certo/10' },
  { id: 'leitura', rotulo: 'Leitura', cor: 'text-suave border-borda-forte' },
  { id: 'descanso', rotulo: 'Descanso', cor: 'text-apagado border-borda' },
]
const COR = Object.fromEntries(TIPOS.map((t) => [t.id, t]))

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const somar = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)

function NovoItem({ dia, aoFechar }: { dia: string; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [titulo, setTitulo] = useState('')
  const [tipo, setTipo] = useState<TipoAgenda>('estudo')
  const [minutos, setMinutos] = useState<number | ''>('')
  const criar = useMutation({
    mutationFn: () => api.post('/api/agenda', { dia, titulo, tipo, minutos: minutos || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['agenda'] }); qc.invalidateQueries({ queryKey: ['painel'] }); aoFechar() },
  })
  return (
    <div className="flex gap-2 items-center mt-2">
      <input autoFocus className="campo text-sm !py-1.5" placeholder="O que fazer" value={titulo} onChange={(e) => setTitulo(e.target.value)}
             onKeyDown={(e) => { if (e.key === 'Enter' && titulo) criar.mutate(); if (e.key === 'Escape') aoFechar() }} />
      <select className="campo text-sm !py-1.5 !w-32" value={tipo} onChange={(e) => setTipo(e.target.value as TipoAgenda)}>
        {TIPOS.map((t) => <option key={t.id} value={t.id}>{t.rotulo}</option>)}
      </select>
      <input type="number" className="campo text-sm !py-1.5 !w-20 num" placeholder="min" value={minutos} onChange={(e) => setMinutos(e.target.value ? Number(e.target.value) : '')} />
      <button className="btn btn-primario !py-1.5" disabled={!titulo || criar.isPending} onClick={() => criar.mutate()}>Adicionar</button>
    </div>
  )
}

function Item({ it }: { it: ItemAgenda }) {
  const qc = useQueryClient()
  const atualizar = () => { qc.invalidateQueries({ queryKey: ['agenda'] }); qc.invalidateQueries({ queryKey: ['painel'] }) }
  const status = useMutation({ mutationFn: (s: string) => api.patch(`/api/agenda/${it.id}`, { status: s }), onSuccess: atualizar })
  const apagar = useMutation({ mutationFn: () => api.del(`/api/agenda/${it.id}`), onSuccess: atualizar })
  const t = COR[it.tipo] ?? TIPOS[0]
  return (
    <li className={clsx('flex items-start gap-3 py-2 group', it.status !== 'planejado' && 'opacity-55')}>
      <button onClick={() => status.mutate(it.status === 'feito' ? 'planejado' : 'feito')} title={it.status === 'feito' ? 'Desmarcar' : 'Marcar como feito'}
              className={clsx('size-5 rounded-md border grid place-items-center shrink-0 mt-0.5 transition', it.status === 'feito' ? 'bg-certo/20 border-certo text-certo' : 'border-borda-forte hover:border-hema')}>
        {it.status === 'feito' && <Check className="size-3.5" />}
      </button>
      <div className="flex-1 min-w-0">
        <p className={clsx('text-sm', it.status === 'feito' && 'line-through')}>
          {it.titulo}
          {it.status === 'pulado' && <span className="text-[11px] text-apagado ml-2">(pulado)</span>}
        </p>
        <div className="flex flex-wrap items-center gap-2 mt-1">
          <span className={clsx('chip', t.cor)}>{t.rotulo}</span>
          {it.minutos && <span className="text-[11px] text-apagado num">{it.minutos} min</span>}
          {it.tema_id && <Link to={`/temas/${it.tema_id}`} className="text-[11px] text-hema hover:underline">{it.tema_nome ?? it.tema_id}</Link>}
          {it.bloco_id && <Link to={`/blocos/${it.bloco_id}`} className="text-[11px] text-hema hover:underline">abrir bloco{it.bloco_nome ? `: ${it.bloco_nome}` : ''}</Link>}
          <span className="text-[10px] text-apagado">{it.origem === 'preceptor' ? 'Preceptor' : 'você'}</span>
        </div>
        {it.detalhe && <p className="text-xs text-suave mt-1">{it.detalhe}</p>}
      </div>
      <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition">
        {it.status === 'planejado'
          ? <button className="btn btn-fantasma !p-1" title="Pular" onClick={() => status.mutate('pulado')}><CornerUpRight className="size-3.5" /></button>
          : <button className="btn btn-fantasma !p-1" title="Voltar a planejado" onClick={() => status.mutate('planejado')}><RotateCcw className="size-3.5" /></button>}
        <button className="btn btn-fantasma !p-1" title="Remover" onClick={() => apagar.mutate()}><Trash2 className="size-3.5" /></button>
      </div>
    </li>
  )
}

function Dia({ dia, itens, prova, adicionando, setAdicionando }: {
  dia: string
  itens: ItemAgenda[]
  prova: Date
  adicionando: string | null
  setAdicionando: (d: string | null) => void
}) {
  const d = new Date(`${dia}T12:00:00`)
  const feitos = itens.filter((i) => i.status === 'feito').length
  const ehHoje = dia === iso(new Date())
  const faltam = Math.round((prova.getTime() - d.getTime()) / 86400000)
  return (
    <section className={clsx('cartao p-5', ehHoje && 'border-hema/70')}>
      <div className="flex items-baseline justify-between">
        <p className="titulo text-lg">
          {(() => { const t = d.toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: '2-digit' }); return t[0].toUpperCase() + t.slice(1) })()}
          {ehHoje && <span className="chip text-hema border-hema/40 bg-hema/10 ml-2 align-middle">hoje</span>}
        </p>
        <span className="text-[11px] text-apagado num">{itens.length ? `${feitos}/${itens.length} · ` : ''}D-{faltam}</span>
      </div>
      {itens.length > 0 ? <ul className="divide-y divide-borda mt-1">{itens.map((it) => <Item key={it.id} it={it} />)}</ul>
        : <p className="text-sm text-apagado mt-2">Nada planejado.</p>}
      {adicionando === dia ? <NovoItem dia={dia} aoFechar={() => setAdicionando(null)} />
        : <button className="text-[11px] text-suave hover:text-hema mt-2 inline-flex items-center gap-1" onClick={() => setAdicionando(dia)}><Plus className="size-3" /> adicionar</button>}
    </section>
  )
}

export default function Agenda() {
  const qc = useQueryClient()
  const hoje = new Date()
  const [adicionando, setAdicionando] = useState<string | null>(null)
  const { data: painel } = useQuery({ queryKey: ['painel'], queryFn: () => api.get<Painel>('/api/painel') })
  const de = iso(somar(hoje, -7))
  const ate = iso(somar(hoje, 27))
  const { data, error } = useQuery({ queryKey: ['agenda', de, ate], queryFn: () => api.get<ItemAgenda[]>(`/api/agenda?de=${de}&ate=${ate}`) })
  const replanejar = useMutation({
    mutationFn: () => api.post('/api/preceptor/ronda', { observacao: 'Replaneje a agenda dos próximos 7 dias com base no meu desempenho atual.' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['avisos'] }),
  })
  if (error) return <div className="p-8"><ErroCaixa erro={error} /></div>
  if (!data || !painel) return <Carregando />

  const prova = new Date(`${painel.data_prova}T12:00:00`)
  const porDia = new Map<string, ItemAgenda[]>()
  for (const it of data) porDia.set(it.dia, [...(porDia.get(it.dia) ?? []), it])
  const futuros: string[] = []
  for (let i = 0; i < 28; i++) {
    const d = somar(hoje, i)
    if (d > prova) break
    futuros.push(iso(d))
  }
  const passados = [...porDia.keys()].filter((d) => d < iso(hoje)).sort().reverse()

  return (
    <div className="max-w-4xl mx-auto px-8 py-8 entrar">
      <Cabecalho
        titulo="Agenda"
        sub="O Preceptor planeja os próximos dias nas rondas. Você marca o que fez e ajusta ou acrescenta à vontade."
        acoes={<button className="btn" disabled={replanejar.isPending || replanejar.isSuccess} onClick={() => replanejar.mutate()}>
          <Stethoscope className="size-4" /> {replanejar.isSuccess ? 'Preceptor replanejando…' : 'Pedir replanejamento'}
        </button>}
      />
      <ErroCaixa erro={replanejar.error} />
      <div className="space-y-4">
        {futuros.map((d) => <Dia key={d} dia={d} itens={porDia.get(d) ?? []} prova={prova} adicionando={adicionando} setAdicionando={setAdicionando} />)}
      </div>
      {passados.length > 0 && (
        <details className="mt-8">
          <summary className="cursor-pointer text-sm text-suave">Dias anteriores</summary>
          <div className="space-y-4 mt-4">{passados.map((d) => <Dia key={d} dia={d} itens={porDia.get(d) ?? []} prova={prova} adicionando={adicionando} setAdicionando={setAdicionando} />)}</div>
        </details>
      )}
    </div>
  )
}
