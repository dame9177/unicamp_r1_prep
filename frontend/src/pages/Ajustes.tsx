import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, type Ajustes as TAjustes, type Perfil, type Uso } from '../api'
import { Cabecalho, Carregando, ErroCaixa } from '../components/ui'

const PAPEIS: { id: string; rotulo: string; dica: string }[] = [
  { id: 'juiz', rotulo: 'Juiz (correção)', dica: 'Roda a cada resposta. Haiku é rápido e barato.' },
  { id: 'juiz_revisao', rotulo: 'Juiz de revisão', dica: 'Só quando você clica em “Rejulgar”.' },
  { id: 'tutor', rotulo: 'Tutor', dica: 'Chat lateral com busca na web.' },
  { id: 'flashcards', rotulo: 'Flashcards', dica: 'Geração sob demanda.' },
  { id: 'coach', rotulo: 'Coach', dica: 'Análise estratégica.' },
  { id: 'curadoria', rotulo: 'Curadoria', dica: 'Script de temas/adaptação.' },
]

interface Resposta { ajustes: TAjustes; modelos_disponiveis: { id: string; nome: string }[]; perfil: Perfil }

function Painel({ titulo, children, id }: { titulo: string; children: React.ReactNode; id?: string }) {
  return (
    <section id={id} className="cartao p-6">
      <h2 className="titulo text-lg mb-4">{titulo}</h2>
      {children}
    </section>
  )
}

export default function Ajustes() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['ajustes'], queryFn: () => api.get<Resposta>('/api/ajustes') })
  const { data: uso } = useQuery({ queryKey: ['uso'], queryFn: () => api.get<Uso>('/api/uso') })
  const [aj, setAj] = useState<TAjustes | null>(null)
  const [perfil, setPerfil] = useState<Perfil | null>(null)
  useEffect(() => { if (data) { setAj(data.ajustes); setPerfil(data.perfil) } }, [data])

  const salvar = useMutation({
    mutationFn: async () => {
      await api.put('/api/ajustes', aj)
      await api.put('/api/perfil', perfil)
    },
    onSuccess: () => { qc.invalidateQueries() },
  })
  if (!data || !aj || !perfil) return <Carregando />
  const set = <K extends keyof TAjustes>(k: K, v: TAjustes[K]) => setAj({ ...aj, [k]: v })

  return (
    <div className="max-w-4xl mx-auto px-8 py-8 space-y-6 entrar">
      <Cabecalho
        titulo="Ajustes"
        sub="Perfil e preferências ficam só na sua máquina (app_data/, fora do git)."
        acoes={<button className="btn btn-primario" disabled={salvar.isPending} onClick={() => salvar.mutate()}>{salvar.isSuccess ? 'Salvo ✓' : 'Salvar'}</button>}
      />
      <ErroCaixa erro={salvar.error} />

      <Painel titulo="Perfil">
        <div className="grid grid-cols-3 gap-4">
          <label className="text-sm text-suave">Nome<input className="campo mt-1" value={perfil.nome} onChange={(e) => setPerfil({ ...perfil, nome: e.target.value })} /></label>
          <label className="text-sm text-suave">Especialidade-alvo<input className="campo mt-1" value={perfil.especialidade_alvo} onChange={(e) => setPerfil({ ...perfil, especialidade_alvo: e.target.value })} /></label>
          <label className="text-sm text-suave">Data da prova<input type="date" className="campo mt-1" value={perfil.data_prova} onChange={(e) => setPerfil({ ...perfil, data_prova: e.target.value })} /></label>
        </div>
        <p className="text-[11px] text-apagado mt-2">O tutor e o coach usam essas informações para personalizar o tom e as prioridades.</p>
      </Painel>

      <Painel titulo="Modelos por papel">
        <div className="space-y-3">
          {PAPEIS.map((p) => (
            <div key={p.id} className="grid grid-cols-[180px_1fr_140px] gap-4 items-center">
              <div><p className="text-sm">{p.rotulo}</p><p className="text-[11px] text-apagado">{p.dica}</p></div>
              <select className="campo" value={aj.modelos[p.id]} onChange={(e) => set('modelos', { ...aj.modelos, [p.id]: e.target.value })}>
                {data.modelos_disponiveis.map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
              </select>
              {p.id in aj.esforco ? (
                <select className="campo" value={aj.esforco[p.id]} onChange={(e) => set('esforco', { ...aj.esforco, [p.id]: e.target.value })}>
                  {['low', 'medium', 'high'].map((x) => <option key={x} value={x}>esforço {x}</option>)}
                </select>
              ) : <span />}
            </div>
          ))}
        </div>
      </Painel>

      <Painel titulo="Automação e limites">
        <div className="space-y-3 text-sm">
          <label className="flex items-center gap-3"><input type="checkbox" checked={aj.correcao_automatica} onChange={(e) => set('correcao_automatica', e.target.checked)} />
            Corrigir automaticamente cada resposta com o juiz</label>
          <label className="flex items-center gap-3"><input type="checkbox" checked={aj.coach_automatico} onChange={(e) => set('coach_automatico', e.target.checked)} />
            Coach automático ao abrir o app (no máximo 1×/dia) após
            <input type="number" className="campo !w-20 num !py-1" value={aj.coach_min_tentativas_novas} onChange={(e) => set('coach_min_tentativas_novas', Number(e.target.value))} />
            respostas novas</label>
          <label className="flex items-center gap-3">Meta diária
            <input type="number" className="campo !w-24 num !py-1" value={aj.meta_diaria} onChange={(e) => set('meta_diaria', Number(e.target.value))} /> questões</label>
          <label className="flex items-center gap-3">Duração padrão do simulado
            <input type="number" className="campo !w-24 num !py-1" value={aj.simulado_duracao_min} onChange={(e) => set('simulado_duracao_min', Number(e.target.value))} /> min</label>
          <label className="flex items-center gap-3">Aviso de consumo diário
            <input type="number" step={50000} className="campo !w-32 num !py-1" value={aj.aviso_tokens_dia} onChange={(e) => set('aviso_tokens_dia', Number(e.target.value))} /> tokens</label>
        </div>
      </Painel>

      {uso && (
        <Painel titulo="Uso do Claude" id="uso">
          {uso.limite?.reseta_em && (
            <p className="text-sm text-suave mb-4">
              Janela do plano ({uso.limite.tipo}): <b className="text-texto">{uso.limite.status}</b>
              {uso.limite.utilizacao != null && <> · {Math.round(uso.limite.utilizacao * 100)}% usado</>}
              {' '}· reinicia {new Date(uso.limite.reseta_em * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
            </p>
          )}
          <div className="grid grid-cols-4 gap-3 mb-5">
            {uso.hoje.map((h) => (
              <div key={h.papel} className="rounded-xl border border-borda p-3">
                <p className="text-xs text-apagado">{h.papel}</p>
                <p className="num text-lg">{(h.tokens / 1000).toFixed(1)}k</p>
                <p className="num text-[11px] text-apagado">{h.chamadas} chamadas · US$ {h.custo_usd.toFixed(3)} eq.</p>
              </div>
            ))}
            {uso.hoje.length === 0 && <p className="text-sm text-suave col-span-4">Nenhuma chamada hoje.</p>}
          </div>
          <table className="w-full text-xs">
            <thead className="text-apagado text-left"><tr><th className="py-1">Quando</th><th>Papel</th><th>Modelo</th><th className="text-right">Tokens</th><th className="text-right">Tempo</th><th>Status</th></tr></thead>
            <tbody>
              {uso.recentes.map((j) => (
                <tr key={j.id} className="border-t border-borda" title={j.erro ?? ''}>
                  <td className="py-1.5 num">{new Date(j.criado_em).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</td>
                  <td>{j.papel}</td><td className="text-suave">{j.modelo}</td>
                  <td className="text-right num">{j.tokens.toLocaleString('pt-BR')}</td>
                  <td className="text-right num">{j.duracao_ms ? `${(j.duracao_ms / 1000).toFixed(1)}s` : '—'}</td>
                  <td className={j.status === 'erro' ? 'text-errado' : 'text-suave'}>{j.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[11px] text-apagado mt-3">“US$ eq.” é o custo equivalente de API informado pelo CLI; no plano Pro o que conta é a janela de uso.</p>
        </Painel>
      )}
    </div>
  )
}
