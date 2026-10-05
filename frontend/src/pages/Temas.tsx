import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, AREAS, AREA_CURTA, pct, type Tema } from '../api'
import { Barra, Cabecalho, Carregando, StatusChip } from '../components/ui'

type Ordem = 'prioridade' | 'area' | 'dominio'

export default function Temas() {
  const { data } = useQuery({ queryKey: ['temas'], queryFn: () => api.get<Tema[]>('/api/temas') })
  const [ordem, setOrdem] = useState<Ordem>('prioridade')
  const [area, setArea] = useState<string | null>(null)
  if (!data) return <Carregando />

  let temas = area ? data.filter((t) => t.area === area) : [...data]
  if (ordem === 'prioridade') temas.sort((a, b) => b.prioridade - a.prioridade)
  if (ordem === 'dominio') temas.sort((a, b) => (a.aproveitamento_firme ?? -1) - (b.aproveitamento_firme ?? -1))
  if (ordem === 'area') temas = AREAS.flatMap((ar) => temas.filter((t) => t.area === ar))
  const maxPrio = Math.max(...data.map((t) => t.prioridade), 0.0001)
  const dominados = data.filter((t) => t.status === 'dominado').length

  return (
    <div className="max-w-6xl mx-auto px-8 py-8 entrar">
      <Cabecalho
        titulo="Temas"
        sub={<>{data.length} temas · <span className="text-eosina">{dominados} dominados</span> · prioridade = prevalência na banca × lacuna de domínio × peso do Preceptor</>}
      />
      <div className="flex flex-wrap items-center gap-2 mb-5">
        <button className={clsx('chip !py-1 !px-3', !area && '!text-texto !border-hema')} onClick={() => setArea(null)}>Todas</button>
        {AREAS.map((a) => (
          <button key={a} className={clsx('chip !py-1 !px-3', area === a && '!text-texto !border-hema')} onClick={() => setArea(a)}>
            {AREA_CURTA[a]}
          </button>
        ))}
        <span className="flex-1" />
        <span className="text-xs text-apagado">Ordenar:</span>
        {(['prioridade', 'dominio', 'area'] as Ordem[]).map((o) => (
          <button key={o} className={clsx('chip !py-1 !px-3', ordem === o && '!text-texto !border-hema')} onClick={() => setOrdem(o)}>
            {o === 'prioridade' ? 'Prioridade' : o === 'dominio' ? 'Menor domínio' : 'Área'}
          </button>
        ))}
      </div>
      <div className="cartao divide-y divide-borda">
        <div className="grid grid-cols-12 gap-4 px-5 py-2.5 text-[11px] uppercase tracking-wider text-apagado">
          <span className="col-span-5">Tema</span>
          <span className="col-span-2">Cobertura</span>
          <span className="col-span-1 text-right">Domínio</span>
          <span className="col-span-2">Prioridade</span>
          <span className="col-span-2">Status</span>
        </div>
        {temas.map((t) => (
          <Link key={t.id} to={`/temas/${t.id}`} className="grid grid-cols-12 gap-4 px-5 py-3.5 items-center hover:bg-lamina-2/60 transition">
            <div className="col-span-5 min-w-0">
              <p className={clsx('text-sm truncate', t.geral && 'text-suave italic')}>{t.geral ? `${t.area} — não classificadas` : t.nome}</p>
              <p className="text-[11px] text-apagado truncate">{AREA_CURTA[t.area]} · {t.total} questões{t.peso_coach !== 1 && <span className="text-hema"> · peso coach ×{t.peso_coach}</span>}</p>
            </div>
            <div className="col-span-2">
              <Barra valor={t.cobertura} />
              <p className="num text-[11px] text-apagado mt-1">{t.respondidas}/{t.total}</p>
            </div>
            <p className={clsx('col-span-1 text-right num text-sm', (t.aproveitamento_firme ?? 0) >= 0.8 ? 'text-eosina' : 'text-texto')}>
              {pct(t.aproveitamento_firme)}
            </p>
            <div className="col-span-2"><Barra valor={t.prioridade / maxPrio} cor="bg-parcial/80" /></div>
            <div className="col-span-2"><StatusChip s={t.status} revisar={t.revisar} manual={!!t.status_manual} /></div>
          </Link>
        ))}
      </div>
    </div>
  )
}
