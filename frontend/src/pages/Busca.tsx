import { useMutation, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Image as ImagemIcone, Layers, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, AREAS, AREA_CURTA, type Veredito } from '../api'
import { Cabecalho, Carregando } from '../components/ui'

interface Resultado { id: string; area: string; processo: number; numero: number; tema_nome: string | null; subtopico: string | null; tem_imagem: number; trecho: string; ultimo_veredito: Veredito | null }
const COR: Record<string, string> = { correto: 'bg-certo', parcial: 'bg-parcial', incorreto: 'bg-errado' }

export default function Busca() {
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const [texto, setTexto] = useState(params.get('q') ?? '')
  const q = params.get('q') ?? ''
  const area = params.get('area') ?? ''
  useEffect(() => { setTexto(q) }, [q])
  const { data, isFetching } = useQuery({
    queryKey: ['busca', q, area], enabled: q.trim().length > 1,
    queryFn: () => api.get<Resultado[]>(`/api/busca?q=${encodeURIComponent(q)}${area ? `&area=${encodeURIComponent(area)}` : ''}`),
  })
  const bloco = useMutation({
    mutationFn: () => api.post<{ id: number }>('/api/blocos', { tipo: 'custom', nome: `Busca: ${q}`, questao_ids: data!.map((r) => r.id) }),
    onSuccess: (r) => nav(`/blocos/${r.id}`),
  })
  return (
    <div className="max-w-5xl mx-auto px-8 py-8 entrar">
      <Cabecalho titulo="Buscar questões" sub="Busca local no banco (enunciado, gabarito, subtópico e tema). Não gasta tokens." />
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setParams(area ? { q: texto, area } : { q: texto }) }}>
        <div className="relative flex-1">
          <Search className="size-4 absolute left-3 top-3.5 text-apagado" />
          <input autoFocus className="campo !pl-9" placeholder="ex.: pré-eclâmpsia sulfato, bronquiolite, Kawasaki…" value={texto} onChange={(e) => setTexto(e.target.value)} />
        </div>
        <button className="btn btn-primario">Buscar</button>
      </form>
      <div className="flex flex-wrap gap-2 mt-3">
        <button className={clsx('chip !py-1 !px-3', !area && '!text-texto !border-hema')} onClick={() => setParams({ q })}>Todas</button>
        {AREAS.map((a) => (
          <button key={a} className={clsx('chip !py-1 !px-3', area === a && '!text-texto !border-hema')} onClick={() => setParams({ q, area: a })}>{AREA_CURTA[a]}</button>
        ))}
      </div>
      {isFetching && <Carregando texto="Buscando…" />}
      {data && (
        <>
          <div className="flex items-center justify-between mt-6 mb-3">
            <p className="text-sm text-suave">{data.length} resultado(s)</p>
            {data.length > 0 && <button className="btn" onClick={() => bloco.mutate()} disabled={bloco.isPending}><Layers className="size-4" /> Resolver como bloco</button>}
          </div>
          <div className="cartao divide-y divide-borda">
            {data.map((r) => (
              <Link key={r.id} to={`/questao/${r.id}`} className="flex items-center gap-4 px-5 py-3 hover:bg-lamina-2/60 transition">
                <span className={clsx('size-2.5 rounded-full shrink-0', r.ultimo_veredito ? COR[r.ultimo_veredito] : 'border border-borda-forte')} />
                <span className="num text-xs text-apagado w-28 shrink-0">{r.processo} · Q{r.numero}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm truncate">{r.subtopico || r.tema_nome}</p>
                  <p className="text-[11px] text-apagado truncate">{AREA_CURTA[r.area]} · {r.trecho}</p>
                </div>
                {r.tem_imagem ? <ImagemIcone className="size-4 text-apagado" /> : null}
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
