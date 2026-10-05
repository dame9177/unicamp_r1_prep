import { useMutation, useQuery } from '@tanstack/react-query'
import { Timer } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, pct, type Bloco } from '../api'
import { Anel, Cabecalho, ErroCaixa } from '../components/ui'

export default function Simulado() {
  const nav = useNavigate()
  const [duracao, setDuracao] = useState(240)
  const { data } = useQuery({ queryKey: ['blocos', true], queryFn: () => api.get<Bloco[]>('/api/blocos?incluir_arquivados=true') })
  const criar = useMutation({
    mutationFn: () => api.post<{ id: number }>('/api/blocos', { tipo: 'simulado', duracao_min: duracao }),
    onSuccess: (r) => nav(`/blocos/${r.id}`),
  })
  const simulados = (data ?? []).filter((b) => b.tipo === 'simulado')

  return (
    <div className="max-w-4xl mx-auto px-8 py-8 entrar">
      <Cabecalho titulo="Simulado" sub="50 questões no formato da prova: 10 por área, na ordem do caderno, priorizando as que você nunca viu." />
      <section className="cartao p-7 flex gap-8 items-center">
        <div className="size-20 rounded-2xl bg-eosina-escuro/60 grid place-items-center"><Timer className="size-9 text-eosina" /></div>
        <div className="flex-1">
          <p className="titulo text-xl">Novo simulado</p>
          <p className="text-sm text-suave mt-1">Sem gabarito nem tutor até finalizar. A correção sai em lote no fim (mais econômico).</p>
          <label className="flex items-center gap-3 mt-4 text-sm">
            Duração
            <input type="number" min={30} max={360} step={15} className="campo !w-24 num" value={duracao} onChange={(e) => setDuracao(Number(e.target.value))} />
            minutos
          </label>
        </div>
        <button className="btn btn-primario !px-6 !py-3" disabled={criar.isPending} onClick={() => criar.mutate()}>Começar</button>
      </section>
      <ErroCaixa erro={criar.error} />

      {simulados.length > 0 && (
        <section className="mt-8 space-y-3">
          <h2 className="titulo text-lg">Anteriores</h2>
          {simulados.map((s) => (
            <Link key={s.id} to={`/blocos/${s.id}`} className="cartao p-5 flex items-center gap-5 hover:border-hema transition">
              <Anel valor={s.finalizado_em ? s.estatistica_no_bloco?.aproveitamento_bruto ?? null : null} tamanho={56} cor="var(--color-eosina)">
                <span className="num text-xs">{s.finalizado_em ? pct(s.estatistica_no_bloco?.aproveitamento_bruto) : '…'}</span>
              </Anel>
              <div className="flex-1">
                <p className="font-medium">{s.nome}</p>
                <p className="text-xs text-apagado">{new Date(s.criado_em).toLocaleString('pt-BR')} · {s.respondidas}/{s.total} respondidas · {s.finalizado_em ? 'finalizado' : 'em andamento'}</p>
              </div>
            </Link>
          ))}
        </section>
      )}
    </div>
  )
}
