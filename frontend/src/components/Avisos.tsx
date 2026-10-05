import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bell, BellRing, CalendarClock, Lightbulb, ScrollText, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type Aviso } from '../api'

interface RespostaAvisos { itens: Aviso[]; nao_lidos: number; agendados: Aviso[]; maestro: { ocupado: string | null; ativo: boolean } }

const ICONE = { lembrete: CalendarClock, sugestao: Lightbulb, alerta: TriangleAlert, relatorio: ScrollText }

export function useAvisos() {
  return useQuery({ queryKey: ['avisos'], queryFn: () => api.get<RespostaAvisos>('/api/avisos?todos=true'), refetchInterval: 30_000 })
}

export default function Sino() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [aberto, setAberto] = useState(false)
  const caixa = useRef<HTMLDivElement>(null)
  const { data } = useAvisos()
  const lido = useMutation({
    mutationFn: (id: number) => api.post(`/api/avisos/${id}/lido`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['avisos'] }),
  })
  const todos = useMutation({
    mutationFn: () => api.post('/api/avisos/lidos'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['avisos'] }),
  })
  useEffect(() => {
    if (!aberto) return
    const fora = (e: MouseEvent) => { if (!caixa.current?.contains(e.target as Node)) setAberto(false) }
    document.addEventListener('mousedown', fora)
    return () => document.removeEventListener('mousedown', fora)
  }, [aberto])

  const n = data?.nao_lidos ?? 0
  return (
    <div className="relative" ref={caixa}>
      <button className={clsx('btn btn-fantasma !p-2 relative', n > 0 && 'text-eosina')} onClick={() => setAberto(!aberto)} title="Avisos do Preceptor">
        {n > 0 ? <BellRing className="size-4" /> : <Bell className="size-4" />}
        {n > 0 && <span className="absolute -top-0.5 -right-0.5 num text-[10px] rounded-full bg-eosina text-tinta px-1 leading-4">{n}</span>}
      </button>
      {aberto && (
        <div className="absolute left-0 top-10 z-40 w-80 cartao p-0 shadow-2xl entrar">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-borda">
            <p className="text-sm font-medium">Avisos</p>
            {n > 0 && <button className="text-[11px] text-hema hover:underline" onClick={() => todos.mutate()}>marcar todos como lidos</button>}
          </div>
          <div className="max-h-96 overflow-y-auto divide-y divide-borda">
            {(data?.itens ?? []).length === 0 && <p className="px-4 py-6 text-sm text-suave text-center">Nenhum aviso.</p>}
            {data?.itens.map((a) => {
              const Icone = ICONE[a.tipo] ?? Bell
              return (
                <button key={a.id} className={clsx('w-full text-left px-4 py-3 flex gap-2.5 hover:bg-lamina-2 transition', a.status === 'lido' && 'opacity-55')}
                        onClick={() => { if (a.status === 'entregue') lido.mutate(a.id); if (a.link) { nav(a.link); setAberto(false) } }}>
                  <Icone className={clsx('size-4 mt-0.5 shrink-0', a.tipo === 'alerta' ? 'text-parcial' : 'text-hema')} />
                  <div className="min-w-0">
                    <p className="text-sm">{a.titulo}</p>
                    {a.texto && <p className="text-xs text-suave mt-0.5">{a.texto}</p>}
                    <p className="text-[10px] text-apagado mt-1">{new Date(a.entregue_em ?? a.quando).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })} · {a.origem === 'sentinela' ? 'automático' : a.origem}</p>
                  </div>
                </button>
              )
            })}
          </div>
          {(data?.agendados.length ?? 0) > 0 && (
            <p className="px-4 py-2 border-t border-borda text-[11px] text-apagado">{data!.agendados.length} aviso(s) agendado(s) pelo Preceptor</p>
          )}
        </div>
      )}
    </div>
  )
}
