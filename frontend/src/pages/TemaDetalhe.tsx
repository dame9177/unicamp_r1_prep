import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, Image as ImagemIcone, Play, RotateCcw, Sparkles } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, pct, type Tema, type Veredito } from '../api'
import { Anel, Carregando, ErroCaixa, StatusChip } from '../components/ui'

interface Detalhe {
  tema: Tema
  questoes: { id: string; prova_id: string; processo: number; numero: number; subtopico: string | null; tipo_cognitivo: string | null;
    formato_original: string; adaptada: number; tem_imagem: number; trecho: string; ultimo_veredito: Veredito | null; ultima_confianca: string | null }[]
  blocos: { id: number; nome: string; tipo: string; criado_em: string; finalizado_em: string | null }[]
}

const COR_PONTO: Record<string, string> = { correto: 'bg-certo', parcial: 'bg-parcial', incorreto: 'bg-errado' }

export default function TemaDetalhe() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const nav = useNavigate()
  const { data, error } = useQuery({ queryKey: ['tema', id], queryFn: () => api.get<Detalhe>(`/api/temas/${id}`) })
  const criar = useMutation({
    mutationFn: (corpo: object) => api.post<{ id: number }>('/api/blocos', corpo),
    onSuccess: (r) => nav(`/blocos/${r.id}`),
  })
  const marcar = useMutation({
    mutationFn: (status_manual: string | null) => api.patch(`/api/temas/${id}`, { status_manual }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tema', id] }); qc.invalidateQueries({ queryKey: ['temas'] }); qc.invalidateQueries({ queryKey: ['painel'] }) },
  })
  if (error) return <div className="p-8"><ErroCaixa erro={error} /></div>
  if (!data) return <Carregando />
  const t = data.tema
  const ineditas = data.questoes.filter((q) => !q.ultimo_veredito).length

  return (
    <div className="max-w-5xl mx-auto px-8 py-8 entrar">
      <Link to="/temas" className="text-sm text-suave hover:text-texto inline-flex items-center gap-1.5 mb-5"><ArrowLeft className="size-4" /> Temas</Link>
      <section className="cartao p-7 flex gap-8 items-center">
        <Anel valor={t.aproveitamento_firme} tamanho={120} espessura={9} cor={t.status === 'dominado' ? 'var(--color-eosina)' : 'var(--color-hema)'}>
          <div className="text-center">
            <p className="num text-2xl">{pct(t.aproveitamento_firme)}</p>
            <p className="text-[10px] text-apagado">domínio firme</p>
          </div>
        </Anel>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-apagado uppercase tracking-wider">{t.area}</p>
          <h1 className="titulo text-3xl mt-1">{t.geral ? 'Questões não classificadas' : t.nome}</h1>
          {t.descricao && <p className="text-suave text-sm mt-2">{t.descricao}</p>}
          <div className="flex flex-wrap items-center gap-3 mt-4 text-sm">
            <StatusChip s={t.status} revisar={t.revisar} manual={!!t.status_manual} />
            <span className="text-suave num">{t.respondidas}/{t.total} respondidas</span>
            <span className="text-suave">bruto {pct(t.aproveitamento_bruto)}</span>
            {t.chutes > 0 && <span className="text-parcial">{t.acertos_no_chute}/{t.chutes} chutes certos</span>}
          </div>
          {t.peso_motivo && (
            <p className="text-xs text-hema mt-3 flex items-center gap-1.5"><Sparkles className="size-3.5" /> Preceptor (peso ×{t.peso_coach}): {t.peso_motivo}</p>
          )}
        </div>
      </section>

      <div className="flex flex-wrap gap-2 mt-5">
        <button className="btn btn-primario" disabled={criar.isPending} onClick={() => criar.mutate({ tipo: 'tema', tema_id: id })}>
          <Play className="size-4" /> Resolver tema ({t.total})
        </button>
        {ineditas > 0 && ineditas < t.total && (
          <button className="btn" onClick={() => criar.mutate({ tipo: 'tema', tema_id: id, modo: 'ineditas' })}>Só inéditas ({ineditas})</button>
        )}
        <button className="btn" disabled={!t.n_refazer} onClick={() => criar.mutate({ tipo: 'refazer', tema_id: id })}>
          <RotateCcw className="size-4" /> Refazer erros e chutes ({t.n_refazer})
        </button>
        <span className="flex-1" />
        {t.status_manual ? (
          <button className="btn btn-fantasma" onClick={() => marcar.mutate(null)}>Voltar ao cálculo automático</button>
        ) : t.status === 'dominado' ? (
          <button className="btn btn-fantasma" onClick={() => marcar.mutate('nao_dominado')}>Ainda não domino</button>
        ) : (
          <button className="btn" onClick={() => marcar.mutate('dominado')}>Marcar como dominado</button>
        )}
      </div>
      <ErroCaixa erro={criar.error} />

      <section className="mt-6 cartao divide-y divide-borda">
        {data.questoes.map((q) => (
          <Link key={q.id} to={`/questao/${q.id}`} className="flex items-center gap-4 px-5 py-3 hover:bg-lamina-2/60 transition">
            <span className={clsx('size-2.5 rounded-full shrink-0', q.ultimo_veredito ? COR_PONTO[q.ultimo_veredito] : 'border border-borda-forte')}
                  title={q.ultimo_veredito ?? 'não respondida'} />
            <span className="num text-xs text-apagado w-28 shrink-0">{q.processo} · Q{q.numero}</span>
            <div className="flex-1 min-w-0">
              <p className="text-sm truncate">{q.subtopico || q.trecho}</p>
              <p className="text-[11px] text-apagado truncate">{q.trecho}</p>
            </div>
            {q.tem_imagem ? <ImagemIcone className="size-4 text-apagado" /> : null}
            {q.formato_original === 'multipla_escolha' && <span className="chip">{q.adaptada ? 'MC adaptada' : 'MC'}</span>}
            {q.ultima_confianca === 'chute' && <span className="chip text-parcial border-parcial/40">chute</span>}
          </Link>
        ))}
      </section>
    </div>
  )
}
