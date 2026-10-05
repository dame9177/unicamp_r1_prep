import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { BookOpenCheck, Brain, Gauge, Layers, MessageSquareText, Microscope, Search, Settings, Sparkles, Timer, WandSparkles } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { api, type Painel, type Uso } from '../api'

const ITENS = [
  { to: '/', rotulo: 'Painel', icone: Gauge, fim: true },
  { to: '/temas', rotulo: 'Temas', icone: Microscope },
  { to: '/blocos', rotulo: 'Blocos', icone: Layers },
  { to: '/busca', rotulo: 'Buscar', icone: Search },
  { to: '/flashcards', rotulo: 'Flashcards', icone: Brain, badge: 'flash' as const },
  { to: '/simulado', rotulo: 'Simulado', icone: Timer },
  { to: '/coach', rotulo: 'Coach', icone: Sparkles },
  { to: '/tutor', rotulo: 'Tutor livre', icone: MessageSquareText },
  { to: '/curadoria', rotulo: 'Curadoria', icone: WandSparkles },
  { to: '/ajustes', rotulo: 'Ajustes', icone: Settings },
]

function MedidorUso() {
  const { data } = useQuery({ queryKey: ['uso'], queryFn: () => api.get<Uso>('/api/uso'), refetchInterval: 60_000 })
  if (!data) return null
  const tokens = data.hoje.reduce((s, h) => s + (h.tokens || 0), 0)
  const frac = Math.min(1, tokens / (data.aviso_tokens_dia || 1))
  const limite = data.limite
  return (
    <NavLink to="/ajustes#uso" className="block px-3 py-3 rounded-xl hover:bg-lamina-2 transition" title="Uso do Claude hoje">
      <div className="flex justify-between text-[11px] text-apagado mb-1.5">
        <span>Claude hoje</span>
        <span className="num">{(tokens / 1000).toFixed(0)}k tok</span>
      </div>
      <div className="h-1 rounded-full bg-borda overflow-hidden">
        <div className={clsx('h-full', frac > 0.85 ? 'bg-errado' : frac > 0.6 ? 'bg-parcial' : 'bg-hema')}
             style={{ width: `${frac * 100}%` }} />
      </div>
      {limite?.status && limite.status !== 'allowed' && (
        <p className="text-[11px] mt-1.5 text-parcial">
          {limite.status === 'rejected' ? 'Limite do plano atingido' : 'Perto do limite do plano'}
        </p>
      )}
    </NavLink>
  )
}

export default function Layout() {
  const { data: painel } = useQuery({ queryKey: ['painel'], queryFn: () => api.get<Painel>('/api/painel') })
  return (
    <div className="flex h-full">
      <aside className="w-56 shrink-0 border-r border-borda bg-tinta/70 backdrop-blur flex flex-col">
        <div className="px-5 pt-6 pb-5">
          <div className="flex items-center gap-2.5">
            <svg viewBox="0 0 64 64" className="size-8" aria-hidden>
              <rect x="4" y="18" width="56" height="28" rx="6" fill="#12152A" stroke="#8B7CF6" strokeWidth="3" />
              <circle cx="26" cy="32" r="8" fill="#F27BA8" opacity=".9" />
              <circle cx="38" cy="30" r="5" fill="#8B7CF6" />
              <circle cx="33" cy="38" r="3" fill="#8B7CF6" opacity=".7" />
            </svg>
            <div>
              <p className="titulo text-xl leading-none">Lâmina</p>
              <p className="text-[11px] text-apagado mt-1">R1 · Acesso Direto Unicamp</p>
            </div>
          </div>
          {painel && (
            <div className="mt-5 rounded-xl border border-borda bg-lamina/60 px-3 py-2.5">
              <p className="text-[11px] text-apagado uppercase tracking-wider">Prova em</p>
              <p className="titulo text-2xl text-eosina leading-tight">
                <span className="num">D-{painel.dias_ate_prova}</span>
              </p>
            </div>
          )}
        </div>
        <nav className="flex-1 px-3 space-y-0.5">
          {ITENS.map(({ to, rotulo, icone: Icone, fim, badge }) => (
            <NavLink
              key={to} to={to} end={fim}
              className={({ isActive }) => clsx(
                'flex items-center gap-3 px-3 py-2 rounded-xl text-sm transition',
                isActive ? 'bg-hema-escuro/70 text-white' : 'text-suave hover:text-texto hover:bg-lamina-2',
              )}
            >
              <Icone className="size-4" />
              <span className="flex-1">{rotulo}</span>
              {badge === 'flash' && painel && painel.flashcards_vencidos > 0 && (
                <span className="num text-[11px] rounded-full bg-eosina/20 text-eosina px-1.5">{painel.flashcards_vencidos}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t border-borda">
          <MedidorUso />
          <p className="px-3 pt-2 text-[10px] text-apagado flex items-center gap-1.5">
            <BookOpenCheck className="size-3" /> 650 questões · 2022–2026
          </p>
        </div>
      </aside>
      <main className="flex-1 min-w-0 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
