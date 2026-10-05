import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useState } from 'react'
import { api, AREAS, AREA_CURTA, type QuestaoCuradoria, type Tema } from '../api'
import { Cabecalho, Carregando, ErroCaixa } from '../components/ui'

interface Resumo { temas: number; classificadas: number; questoes: number; mc_adaptadas: number; mc_total: number }

function Linha({ q, temas }: { q: QuestaoCuradoria; temas: Tema[] }) {
  const qc = useQueryClient()
  const [tema, setTema] = useState(q.tema_id)
  const [sub, setSub] = useState(q.subtopico ?? '')
  const [enun, setEnun] = useState(q.enunciado)
  const [resp, setResp] = useState(q.resposta_esperada ?? '')
  const mc = q.formato_original === 'multipla_escolha'
  const mudou = tema !== q.tema_id || sub !== (q.subtopico ?? '') || (mc && (enun !== q.enunciado || resp !== (q.resposta_esperada ?? '')))
  const salvar = useMutation({
    mutationFn: () => api.put(`/api/curadoria/questoes/${q.id}`, {
      tema_id: tema !== q.tema_id ? tema : null,
      subtopico: sub !== (q.subtopico ?? '') ? sub : null,
      ...(mc ? { enunciado_discursivo: enun, resposta_esperada: resp, aceitaveis: q.aceitaveis } : {}),
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['curadoria'] }); qc.invalidateQueries({ queryKey: ['temas'] }) },
  })
  return (
    <div className="px-5 py-4 space-y-2">
      <div className="flex items-center gap-3">
        <span className="num text-[11px] text-apagado w-48 shrink-0">{q.id.replace('unicamp-', '')}</span>
        <select className="campo !py-1 !text-sm" value={tema} onChange={(e) => setTema(e.target.value)}>
          {temas.filter((t) => t.area === q.area).map((t) => <option key={t.id} value={t.id}>{t.geral ? '— não classificada —' : t.nome}</option>)}
        </select>
        <input className="campo !py-1 !text-sm" placeholder="subtópico" value={sub} onChange={(e) => setSub(e.target.value)} />
        <button className={clsx('btn !py-1 shrink-0', mudou && 'btn-primario')} disabled={!mudou || salvar.isPending} onClick={() => salvar.mutate()}>Salvar</button>
      </div>
      {mc ? (
        <div className="grid grid-cols-2 gap-3">
          <textarea className="campo !text-xs min-h-28" value={enun} onChange={(e) => setEnun(e.target.value)} />
          <div className="space-y-2">
            <textarea className="campo !text-xs min-h-16" value={resp} onChange={(e) => setResp(e.target.value)} />
            <details className="text-[11px] text-suave">
              <summary className="cursor-pointer">Alternativas originais {q.adaptada ? '' : '(ainda não adaptada)'}</summary>
              {q.alternativas && Object.entries(q.alternativas).map(([k, v]) => (
                <p key={k} className={clsx(k.toUpperCase() === q.letra_original && 'text-certo')}>{k.toUpperCase()}) {v}</p>
              ))}
            </details>
          </div>
        </div>
      ) : (
        <p className="text-xs text-suave line-clamp-2">{q.enunciado.slice(-260)}</p>
      )}
      <ErroCaixa erro={salvar.error} />
    </div>
  )
}

export default function Curadoria() {
  const [area, setArea] = useState<string>(AREAS[0])
  const [soMc, setSoMc] = useState(false)
  const { data: resumo } = useQuery({ queryKey: ['curadoria', 'resumo'], queryFn: () => api.get<Resumo>('/api/curadoria/resumo') })
  const { data: temas } = useQuery({ queryKey: ['temas'], queryFn: () => api.get<Tema[]>('/api/temas') })
  const { data: qs } = useQuery({
    queryKey: ['curadoria', area, soMc],
    queryFn: () => api.get<QuestaoCuradoria[]>(`/api/curadoria/questoes?area=${encodeURIComponent(area)}&so_mc=${soMc}&limite=200`),
  })
  return (
    <div className="max-w-6xl mx-auto px-8 py-8 entrar">
      <Cabecalho
        titulo="Curadoria"
        sub={resumo && <>{resumo.temas} temas · {resumo.classificadas}/{resumo.questoes} questões classificadas · {resumo.mc_adaptadas}/{resumo.mc_total} MC adaptadas. Edições vão para <code>curadoria/*.json</code> (versionado).</>}
      />
      <div className="flex flex-wrap gap-2 mb-4">
        {AREAS.map((a) => (
          <button key={a} className={clsx('chip !py-1 !px-3', area === a && '!text-texto !border-hema')} onClick={() => setArea(a)}>{AREA_CURTA[a]}</button>
        ))}
        <label className="chip !py-1 !px-3 cursor-pointer"><input type="checkbox" checked={soMc} onChange={(e) => setSoMc(e.target.checked)} /> só múltipla escolha</label>
      </div>
      {!qs || !temas ? <Carregando /> : (
        <div className="cartao divide-y divide-borda">
          {qs.map((q) => <Linha key={`${q.id}-${q.tema_id}-${q.adaptada}`} q={q} temas={temas} />)}
        </div>
      )}
    </div>
  )
}
