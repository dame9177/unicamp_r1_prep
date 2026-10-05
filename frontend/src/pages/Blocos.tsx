import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Archive, Layers, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, AREAS, AREA_CURTA, pct, type Bloco } from '../api'
import { Barra, Cabecalho, Carregando, ErroCaixa, Vazio } from '../components/ui'

const TIPO: Record<string, string> = { tema: 'Tema', custom: 'Personalizado', coach: 'Coach', refazer: 'Refazer', simulado: 'Simulado' }

export default function Blocos() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [arquivados, setArquivados] = useState(false)
  const { data } = useQuery({ queryKey: ['blocos', arquivados], queryFn: () => api.get<Bloco[]>(`/api/blocos?incluir_arquivados=${arquivados}`) })
  const criar = useMutation({
    mutationFn: (corpo: object) => api.post<{ id: number }>('/api/blocos', corpo),
    onSuccess: (r) => nav(`/blocos/${r.id}`),
  })
  const arquivar = useMutation({
    mutationFn: (id: number) => api.del(`/api/blocos/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['blocos'] }),
  })

  return (
    <div className="max-w-5xl mx-auto px-8 py-8 entrar">
      <Cabecalho
        titulo="Blocos"
        sub="Conjuntos de questões em andamento. Crie por tema (em Temas) ou por área aqui."
        acoes={<button className="btn btn-fantasma" onClick={() => setArquivados((a) => !a)}>{arquivados ? 'Ocultar arquivados' : 'Ver arquivados'}</button>}
      />
      <div className="cartao p-5 mb-6">
        <p className="text-sm font-medium mb-3">Novo bloco por área (inéditas primeiro)</p>
        <div className="flex flex-wrap gap-2">
          {AREAS.map((a) => (
            <span key={a} className="inline-flex">
              <button className="btn rounded-r-none" onClick={() => criar.mutate({ tipo: 'area', area: a, limite: 20 })}>{AREA_CURTA[a]} · 20</button>
              <button className="btn rounded-l-none border-l-0" title="Só questões nunca respondidas"
                      onClick={() => criar.mutate({ tipo: 'area', area: a, limite: 20, modo: 'ineditas', nome: `${a} · inéditas` })}>inéditas</button>
            </span>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-borda">
          <span className="text-sm font-medium mr-1">Interpretação de imagens</span>
          <button className="btn" onClick={() => criar.mutate({ tipo: 'imagens' })}>Todas as questões com imagem</button>
          <button className="btn" onClick={() => criar.mutate({ tipo: 'imagens', modo: 'ineditas', nome: 'Imagens · inéditas' })}>Só inéditas</button>
        </div>
        <ErroCaixa erro={criar.error} />
      </div>
      {!data ? <Carregando /> : data.length === 0 ? (
        <Vazio titulo="Nenhum bloco ainda">Comece por um tema prioritário no Painel ou na página de Temas.</Vazio>
      ) : (
        <div className="space-y-3">
          {data.map((b) => {
            const progresso = (b.respondidas ?? 0) / Math.max(1, b.total ?? 1)
            return (
              <div key={b.id} className={clsx('cartao p-5 flex items-center gap-5', b.arquivado ? 'opacity-50' : '')}>
                <div className="size-10 rounded-xl bg-hema-escuro/60 grid place-items-center shrink-0">
                  {b.criado_por === 'coach' ? <Sparkles className="size-5 text-hema" /> : <Layers className="size-5 text-hema" />}
                </div>
                <Link to={`/blocos/${b.id}`} className="flex-1 min-w-0 group">
                  <p className="text-sm font-medium truncate group-hover:text-hema">{b.nome}</p>
                  <p className="text-[11px] text-apagado mt-0.5">
                    {TIPO[b.tipo]} · {new Date(b.criado_em).toLocaleDateString('pt-BR')}
                    {b.finalizado_em && ' · finalizado'}{b.descricao && ` · ${b.descricao}`}
                  </p>
                  <Barra valor={progresso} className="mt-2 max-w-sm" />
                </Link>
                <div className="text-right">
                  <p className="num text-sm">{b.respondidas}/{b.total}</p>
                  <p className="num text-[11px] text-apagado">domínio {pct(b.estatistica?.aproveitamento_firme)}</p>
                </div>
                {!b.arquivado && (
                  <button className="btn btn-fantasma !p-2" title="Arquivar" onClick={() => arquivar.mutate(b.id)}><Archive className="size-4" /></button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
