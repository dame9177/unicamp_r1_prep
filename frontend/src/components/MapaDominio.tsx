import clsx from 'clsx'
import { useNavigate } from 'react-router-dom'
import { AREAS, AREA_CURTA, pct, type Painel } from '../api'

type Item = Painel['mapa'][number]

function estilo(t: Item): React.CSSProperties {
  if (t.status === 'dominado') {
    return {
      background: 'radial-gradient(circle at 30% 25%, rgb(255 190 215 / .55), rgb(242 123 168 / .55) 45%, rgb(122 40 80 / .55))',
      borderColor: 'rgb(242 123 168 / .7)',
      boxShadow: '0 0 18px -4px rgb(242 123 168 / .55)',
    }
  }
  if (t.status === 'em_progresso') {
    const a = 0.12 + 0.55 * (t.aproveitamento_firme ?? 0)
    return {
      background: `radial-gradient(circle at 30% 25%, rgb(180 168 255 / ${a}), rgb(109 92 224 / ${a}) 60%, rgb(43 37 96 / ${a + 0.1}))`,
      borderColor: `rgb(139 124 246 / ${0.3 + a / 2})`,
    }
  }
  return { background: 'transparent', borderStyle: 'dashed' }
}

export default function MapaDominio({ mapa }: { mapa: Item[] }) {
  const nav = useNavigate()
  return (
    <div className="grid grid-cols-5 gap-4">
      {AREAS.map((area) => {
        const temas = mapa.filter((t) => t.area === area).sort((a, b) => Number(a.geral) - Number(b.geral))
        const dominados = temas.filter((t) => t.status === 'dominado').length
        return (
          <div key={area}>
            <div className="flex items-baseline justify-between mb-2">
              <p className="text-xs font-medium text-suave uppercase tracking-wider">{AREA_CURTA[area]}</p>
              <p className="num text-[11px] text-apagado">{dominados}/{temas.length}</p>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {temas.map((t) => (
                <button
                  key={t.id}
                  onClick={() => nav(`/temas/${t.id}`)}
                  title={`${t.nome}\n${t.respondidas}/${t.total} respondidas · domínio ${pct(t.aproveitamento_firme)}`}
                  className={clsx(
                    'relative text-left rounded-xl border border-borda-forte p-2 min-h-[64px] transition',
                    'hover:-translate-y-0.5 hover:border-hema',
                    t.revisar && 'ring-2 ring-parcial/70',
                    t.geral && 'opacity-60',
                  )}
                  style={estilo(t)}
                >
                  <p className="text-[11px] leading-tight line-clamp-3 text-texto/90">
                    {t.geral ? 'Não classificadas' : t.nome}
                  </p>
                  <p className="num text-[10px] text-texto/60 mt-1">
                    {t.respondidas ? pct(t.aproveitamento_firme) : `${t.total}q`}
                  </p>
                </button>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
