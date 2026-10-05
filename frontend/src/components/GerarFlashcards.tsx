import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { ErroCaixa, Modal } from './ui'

interface Cartao { frente: string; verso: string }

export default function GerarFlashcards({ questaoId, aberto, aoFechar }: { questaoId: string; aberto: boolean; aoFechar: () => void }) {
  const qc = useQueryClient()
  const [foco, setFoco] = useState('')
  const [cartoes, setCartoes] = useState<Cartao[]>([])
  const [salvos, setSalvos] = useState(false)

  const gerar = useMutation({
    mutationFn: () => api.post<{ cartoes: Cartao[] }>(`/api/questoes/${questaoId}/flashcards/gerar`, { foco: foco || null }),
    onSuccess: (r) => setCartoes((c) => [...c, ...r.cartoes]),
  })
  const salvar = useMutation({
    mutationFn: () => api.post('/api/flashcards', {
      cartoes: cartoes.filter((c) => c.frente.trim() && c.verso.trim()).map((c) => ({ ...c, questao_id: questaoId, origem: 'llm' })),
    }),
    onSuccess: () => { setSalvos(true); qc.invalidateQueries({ queryKey: ['painel'] }); qc.invalidateQueries({ queryKey: ['flashcards'] }) },
  })

  useEffect(() => {
    if (aberto) { setCartoes([]); setSalvos(false); setFoco('') }
  }, [aberto, questaoId])

  const editar = (i: number, campo: keyof Cartao, v: string) =>
    setCartoes((cs) => cs.map((c, j) => (j === i ? { ...c, [campo]: v } : c)))

  return (
    <Modal aberto={aberto} aoFechar={aoFechar} titulo="Flashcards desta questão" largura="max-w-3xl">
      {salvos ? (
        <div className="text-center py-6">
          <p className="titulo text-xl text-eosina">{cartoes.length} cartões salvos</p>
          <p className="text-suave text-sm mt-1">Eles já entram na fila de revisão de hoje.</p>
          <button className="btn mt-5" onClick={aoFechar}>Fechar</button>
        </div>
      ) : (
        <>
          <div className="flex gap-2">
            <input className="campo" placeholder="Foco opcional (ex.: doses, critérios, a pegadinha que me pegou)"
                   value={foco} onChange={(e) => setFoco(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && gerar.mutate()} />
            <button className="btn btn-primario shrink-0" disabled={gerar.isPending} onClick={() => gerar.mutate()}>
              {gerar.isPending ? <><Loader2 className="size-4 animate-spin" /> Gerando…</> : cartoes.length ? 'Gerar mais' : 'Gerar com Claude'}
            </button>
          </div>
          <p className="text-[11px] text-apagado mt-2">Usa a questão, o gabarito, sua resposta e a explicação fixada (se houver). Sem busca na web, para economizar.</p>
          <ErroCaixa erro={gerar.error} />
          <div className="space-y-3 mt-5">
            {cartoes.map((c, i) => (
              <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2 items-start">
                <textarea className="campo text-sm min-h-20" value={c.frente} onChange={(e) => editar(i, 'frente', e.target.value)} />
                <textarea className="campo text-sm min-h-20" value={c.verso} onChange={(e) => editar(i, 'verso', e.target.value)} />
                <button className="btn btn-fantasma !p-2" onClick={() => setCartoes((cs) => cs.filter((_, j) => j !== i))} aria-label="Remover">
                  <Trash2 className="size-4" />
                </button>
              </div>
            ))}
          </div>
          <div className="flex justify-between mt-5">
            <button className="btn btn-fantasma" onClick={() => setCartoes((cs) => [...cs, { frente: '', verso: '' }])}>
              <Plus className="size-4" /> Cartão manual
            </button>
            <button className="btn btn-primario" disabled={!cartoes.length || salvar.isPending} onClick={() => salvar.mutate()}>
              Salvar {cartoes.length || ''} cartões
            </button>
          </div>
          <ErroCaixa erro={salvar.error} />
        </>
      )}
    </Modal>
  )
}
