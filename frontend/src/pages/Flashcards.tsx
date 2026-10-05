import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Pause, Play, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Flashcard } from '../api'
import { Cabecalho, Carregando, Markdown, Vazio } from '../components/ui'

const NOTAS = [
  { n: 1, rotulo: 'Errei', cor: 'hover:border-errado hover:text-errado' },
  { n: 2, rotulo: 'Difícil', cor: 'hover:border-parcial hover:text-parcial' },
  { n: 3, rotulo: 'Bom', cor: 'hover:border-certo hover:text-certo' },
  { n: 4, rotulo: 'Fácil', cor: 'hover:border-hema hover:text-hema' },
]

function Revisao() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['flashcards', 'vencidos'], queryFn: () => api.get<{ cartoes: Flashcard[] }>('/api/flashcards?vencidos=true&limite=300') })
  const [fila, setFila] = useState<Flashcard[] | null>(null)
  const [virado, setVirado] = useState(false)
  const [feitos, setFeitos] = useState(0)

  useEffect(() => { if (data && fila === null) setFila(data.cartoes) }, [data, fila])

  const revisar = useMutation({
    mutationFn: ({ id, nota }: { id: number; nota: number }) => api.post<{ due: string }>(`/api/flashcards/${id}/revisar`, { nota }),
    onSuccess: (r, { id }) => {
      setFila((f) => {
        if (!f) return f
        const [atual, ...resto] = f
        // Cartões que voltam ainda hoje (passos de aprendizado) reentram no fim da fila.
        const voltaLogo = new Date(r.due).getTime() - Date.now() < 20 * 60000
        return voltaLogo && atual.id === id ? [...resto, atual] : resto
      })
      setVirado(false)
      setFeitos((n) => n + 1)
      qc.invalidateQueries({ queryKey: ['painel'] })
    },
  })

  const atual = fila?.[0]
  const tecla = useCallback((e: KeyboardEvent) => {
    if (!atual || (e.target as HTMLElement).tagName === 'TEXTAREA') return
    if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); setVirado(true) }
    if (virado && ['1', '2', '3', '4'].includes(e.key)) revisar.mutate({ id: atual.id, nota: Number(e.key) })
  }, [atual, virado, revisar])
  useEffect(() => { window.addEventListener('keydown', tecla); return () => window.removeEventListener('keydown', tecla) }, [tecla])

  if (!fila) return <Carregando />
  if (!atual) {
    return (
      <Vazio titulo={feitos ? `Revisão concluída · ${feitos} cartões` : 'Nada para revisar agora'}>
        Gere flashcards a partir das questões que errou ou acertou no chute — botão “Gerar flashcards” após responder.
      </Vazio>
    )
  }
  return (
    <div className="max-w-2xl mx-auto">
      <p className="text-center text-xs text-apagado mb-3 num">{fila.length} na fila · {feitos} revisados</p>
      <div className={clsx('cartao p-10 min-h-72 flex flex-col justify-center text-center transition', virado && 'border-eosina/40')}
           onClick={() => setVirado(true)}>
        {atual.tema_nome && <p className="text-[11px] uppercase tracking-wider text-apagado mb-4">{atual.tema_nome}</p>}
        <Markdown className="titulo !text-2xl !leading-snug">{atual.frente}</Markdown>
        {virado ? (
          <div className="mt-6 pt-6 border-t border-borda entrar">
            <Markdown className="!text-lg">{atual.verso}</Markdown>
            {atual.questao_id && <Link to={`/questao/${atual.questao_id}`} className="text-xs text-hema mt-4 inline-block" onClick={(e) => e.stopPropagation()}>ver questão de origem →</Link>}
          </div>
        ) : (
          <p className="text-xs text-apagado mt-8">clique ou <kbd>espaço</kbd> para ver a resposta</p>
        )}
      </div>
      {virado && (
        <div className="grid grid-cols-4 gap-2 mt-4">
          {NOTAS.map((n) => (
            <button key={n.n} className={clsx('btn justify-center !py-3', n.cor)} disabled={revisar.isPending}
                    onClick={() => revisar.mutate({ id: atual.id, nota: n.n })}>
              {n.rotulo} <kbd>{n.n}</kbd>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Todos() {
  const qc = useQueryClient()
  const [busca, setBusca] = useState('')
  const { data } = useQuery({ queryKey: ['flashcards', 'todos'], queryFn: () => api.get<{ cartoes: Flashcard[]; total_ativos: number }>('/api/flashcards?limite=1000') })
  const editar = useMutation({
    mutationFn: ({ id, ...corpo }: { id: number; frente?: string; verso?: string; suspenso?: boolean }) => api.patch(`/api/flashcards/${id}`, corpo),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['flashcards'] }),
  })
  const apagar = useMutation({
    mutationFn: (id: number) => api.del(`/api/flashcards/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['flashcards'] }),
  })
  if (!data) return <Carregando />
  const b = busca.toLowerCase()
  const lista = data.cartoes.filter((c) => !b || c.frente.toLowerCase().includes(b) || c.verso.toLowerCase().includes(b) || (c.tema_nome ?? '').toLowerCase().includes(b))
  return (
    <div>
      <input className="campo mb-4" placeholder={`Buscar entre ${data.cartoes.length} cartões…`} value={busca} onChange={(e) => setBusca(e.target.value)} />
      <div className="cartao divide-y divide-borda">
        {lista.map((c) => (
          <div key={c.id} className={clsx('grid grid-cols-[1fr_1fr_auto] gap-3 px-4 py-3 items-start', c.suspenso && 'opacity-50')}>
            <textarea className="campo !text-sm !py-1.5 min-h-12" defaultValue={c.frente}
                      onBlur={(e) => e.target.value !== c.frente && editar.mutate({ id: c.id, frente: e.target.value })} />
            <textarea className="campo !text-sm !py-1.5 min-h-12" defaultValue={c.verso}
                      onBlur={(e) => e.target.value !== c.verso && editar.mutate({ id: c.id, verso: e.target.value })} />
            <div className="flex flex-col gap-1 items-end">
              <span className="text-[10px] text-apagado num whitespace-nowrap">{new Date(c.due).toLocaleDateString('pt-BR')}</span>
              <div className="flex">
                <button className="btn btn-fantasma !p-1.5" title={c.suspenso ? 'Reativar' : 'Suspender'} onClick={() => editar.mutate({ id: c.id, suspenso: !c.suspenso })}>
                  {c.suspenso ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}
                </button>
                <button className="btn btn-fantasma !p-1.5" title="Apagar" onClick={() => confirm('Apagar este cartão?') && apagar.mutate(c.id)}><Trash2 className="size-3.5" /></button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Flashcards() {
  const [aba, setAba] = useState<'revisar' | 'todos'>('revisar')
  return (
    <div className="max-w-5xl mx-auto px-8 py-8 entrar">
      <Cabecalho
        titulo="Flashcards"
        sub="Repetição espaçada (FSRS). Os intervalos nunca passam da data da prova."
        acoes={(['revisar', 'todos'] as const).map((a) => (
          <button key={a} className={clsx('btn', aba === a && '!border-hema !bg-hema-escuro/60')} onClick={() => setAba(a)}>
            {a === 'revisar' ? 'Revisar' : 'Todos os cartões'}
          </button>
        ))}
      />
      {aba === 'revisar' ? <Revisao /> : <Todos />}
    </div>
  )
}
