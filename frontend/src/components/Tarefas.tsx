import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Ban, Loader2, Play, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { api, type Tarefa } from '../api'
import { ErroCaixa, Markdown } from './ui'

const COR: Record<Tarefa['status'], string> = {
  pendente: 'text-suave border-borda-forte',
  executando: 'text-hema border-hema/40 bg-hema/10',
  concluida: 'text-certo border-certo/40 bg-certo/10',
  erro: 'text-errado border-errado/40 bg-errado/10',
  cancelada: 'text-apagado border-borda',
}

export function NovaTarefa() {
  const qc = useQueryClient()
  const [titulo, setTitulo] = useState('')
  const [instrucoes, setInstrucoes] = useState('')
  const criar = useMutation({
    mutationFn: () => api.post('/api/tarefas', { titulo, instrucoes, agente: 'bibliotecario' }),
    onSuccess: () => { setTitulo(''); setInstrucoes(''); qc.invalidateQueries({ queryKey: ['tarefas'] }) },
  })
  return (
    <div className="space-y-2">
      <input className="campo text-sm" placeholder="Pedido ao bibliotecário (ex.: “PCDT de hipertensão vigente”)" value={titulo} onChange={(e) => setTitulo(e.target.value)} />
      <textarea className="campo text-sm" rows={2} placeholder="Detalhes: o que buscar, para que tema, que nota escrever…" value={instrucoes} onChange={(e) => setInstrucoes(e.target.value)} />
      <div className="flex items-center justify-between">
        <p className="text-[11px] text-apagado">Entra na fila e roda em segundo plano, dentro do orçamento diário.</p>
        <button className="btn btn-primario" disabled={titulo.length < 3 || instrucoes.length < 3 || criar.isPending} onClick={() => criar.mutate()}>Pedir</button>
      </div>
      <ErroCaixa erro={criar.error} />
    </div>
  )
}

export default function ListaTarefas({ limite }: { limite?: number }) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['tarefas'],
    queryFn: () => api.get<Tarefa[]>('/api/tarefas'),
    refetchInterval: (q) => (q.state.data?.some((t) => t.status === 'executando') ? 5000 : 30_000),
  })
  const acao = useMutation({
    mutationFn: ({ id, a }: { id: number; a: string }) => api.post(`/api/tarefas/${id}/${a}`),
    onSettled: () => { qc.invalidateQueries({ queryKey: ['tarefas'] }); qc.invalidateQueries({ queryKey: ['avisos'] }) },
  })
  const itens = (data ?? []).slice(0, limite)
  return (
    <div className="space-y-2">
      <ErroCaixa erro={acao.error} />
      {itens.length === 0 && <p className="text-sm text-suave">Nenhuma tarefa ainda.</p>}
      {itens.map((t) => (
        <details key={t.id} className="rounded-xl border border-borda px-3.5 py-2.5 group">
          <summary className="flex items-center gap-2 cursor-pointer list-none">
            <span className={clsx('chip', COR[t.status])}>{t.status === 'executando' && <Loader2 className="size-3 animate-spin" />}{t.status}</span>
            <span className="text-sm flex-1 truncate">{t.titulo}</span>
            <span className="text-[10px] text-apagado">{t.agente} · por {t.criado_por}</span>
            {t.status === 'pendente' && <>
              <button className="btn btn-fantasma !p-1" title="Executar agora (fora do orçamento de segundo plano)" onClick={(e) => { e.preventDefault(); acao.mutate({ id: t.id, a: 'executar' }) }}><Play className="size-3.5" /></button>
              <button className="btn btn-fantasma !p-1" title="Cancelar" onClick={(e) => { e.preventDefault(); acao.mutate({ id: t.id, a: 'cancelar' }) }}><Ban className="size-3.5" /></button>
            </>}
            {(t.status === 'erro' || t.status === 'cancelada') && (
              <button className="btn btn-fantasma !p-1" title="Recolocar na fila" onClick={(e) => { e.preventDefault(); acao.mutate({ id: t.id, a: 'repetir' }) }}><RotateCcw className="size-3.5" /></button>
            )}
          </summary>
          <div className="mt-2 text-sm space-y-2">
            <p className="text-suave whitespace-pre-wrap text-xs">{t.instrucoes}</p>
            {t.resultado && <div className="rounded-lg bg-lamina-2 p-3"><Markdown className="text-sm">{t.resultado}</Markdown></div>}
            <p className="text-[10px] text-apagado">criada {new Date(t.criado_em).toLocaleString('pt-BR')}{t.concluido_em && ` · concluída ${new Date(t.concluido_em).toLocaleString('pt-BR')}`}</p>
          </div>
        </details>
      ))}
    </div>
  )
}
