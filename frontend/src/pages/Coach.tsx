import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Loader2, Sparkles, Undo2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type CoachEstado } from '../api'
import { Cabecalho, Carregando, ErroCaixa, Markdown } from '../components/ui'

export default function Coach() {
  const qc = useQueryClient()
  const [obs, setObs] = useState('')
  const { data } = useQuery({
    queryKey: ['coach'],
    queryFn: () => api.get<CoachEstado>('/api/coach'),
    refetchInterval: (q) => (q.state.data?.rodando ? 3000 : false),
  })
  const analisar = useMutation({
    mutationFn: () => api.post('/api/coach/analisar', { observacao: obs || null }),
    onSuccess: () => { setObs(''); qc.invalidateQueries({ queryKey: ['coach'] }) },
  })
  const desfazer = useMutation({
    mutationFn: (id: number) => api.post(`/api/coach/acoes/${id}/desfazer`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['coach'] }); qc.invalidateQueries({ queryKey: ['painel'] }); qc.invalidateQueries({ queryKey: ['temas'] }) },
  })
  // Quando a análise termina, o painel (missões, insights, pesos) precisa ser recarregado.
  const rodava = useRef(false)
  useEffect(() => {
    if (rodava.current && data && !data.rodando) {
      qc.invalidateQueries({ queryKey: ['painel'] })
      qc.invalidateQueries({ queryKey: ['temas'] })
      qc.invalidateQueries({ queryKey: ['uso'] })
    }
    rodava.current = !!data?.rodando
  }, [data?.rodando, data, qc])

  if (!data) return <Carregando />
  const [ultima, ...anteriores] = data.analises

  return (
    <div className="max-w-5xl mx-auto px-8 py-8 entrar">
      <Cabecalho
        titulo="Coach"
        sub="O Claude lê seu desempenho, monta missões, cria blocos e ajusta prioridades. Tudo pode ser desfeito; marcar domínio continua sendo decisão sua."
      />
      <section className="cartao p-6">
        <div className="flex gap-3 items-start">
          <textarea className="campo text-sm" rows={2} placeholder="Opcional: contexto para o coach (ex.: “hoje só tenho 2h”, “quero focar em GO”)"
                    value={obs} onChange={(e) => setObs(e.target.value)} disabled={data.rodando} />
          <button className="btn btn-primario shrink-0 !py-3" disabled={data.rodando || analisar.isPending} onClick={() => analisar.mutate()}>
            {data.rodando ? <><Loader2 className="size-4 animate-spin" /> Analisando…</> : <><Sparkles className="size-4" /> Analisar meu desempenho</>}
          </button>
        </div>
        <p className="text-[11px] text-apagado mt-2">Usa Sonnet com esforço médio, sem busca na web. Leva ~1 minuto.</p>
        {data.erro && <div className="mt-3"><ErroCaixa erro={data.erro} /></div>}
        <ErroCaixa erro={analisar.error} />
      </section>

      <div className="grid grid-cols-12 gap-6 mt-6">
        <section className="col-span-7 space-y-4">
          {ultima ? (
            <div className="cartao p-6">
              <p className="text-[11px] uppercase tracking-wider text-apagado">{ultima.titulo} · {new Date(ultima.criado_em).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</p>
              <Markdown className="mt-3">{ultima.conteudo_md}</Markdown>
            </div>
          ) : <p className="text-suave text-sm">Nenhuma análise ainda.</p>}
          {anteriores.map((a) => (
            <details key={a.id} className="cartao p-5">
              <summary className="cursor-pointer text-sm text-suave">{a.titulo}</summary>
              <Markdown className="mt-3 text-sm">{a.conteudo_md}</Markdown>
            </details>
          ))}
        </section>
        <section className="col-span-5">
          <h2 className="titulo text-lg mb-3">Ações do coach</h2>
          <div className="cartao divide-y divide-borda">
            {data.acoes.length === 0 && <p className="p-4 text-sm text-suave">Nenhuma ação ainda.</p>}
            {data.acoes.map((a) => (
              <div key={a.id} className={clsx('px-4 py-3 flex items-start gap-3', a.desfeita_em && 'opacity-45')}>
                <div className="flex-1">
                  <p className={clsx('text-sm', a.desfeita_em && 'line-through')}>{a.descricao}</p>
                  <p className="text-[11px] text-apagado">{new Date(a.criado_em).toLocaleString('pt-BR')}</p>
                </div>
                {!a.desfeita_em && (
                  <button className="btn btn-fantasma !p-1.5" title="Desfazer" onClick={() => desfazer.mutate(a.id)}><Undo2 className="size-4" /></button>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
