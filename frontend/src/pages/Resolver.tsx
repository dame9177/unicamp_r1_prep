import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, Flag, RotateCcw, Timer } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, AREA_CURTA, pct, type BlocoDetalhe } from '../api'
import QuestaoView from '../components/QuestaoView'
import Tutor from '../components/Tutor'
import { Anel, Carregando, ErroCaixa } from '../components/ui'

const COR: Record<string, string> = {
  correto: 'bg-certo border-certo', parcial: 'bg-parcial border-parcial', incorreto: 'bg-errado border-errado',
  pendente: 'bg-suave/40 border-suave', erro: 'bg-errado/40 border-errado',
}

function Cronometro({ inicio, duracaoMin }: { inicio: string; duracaoMin: number }) {
  const [agora, setAgora] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setAgora(Date.now()), 1000); return () => clearInterval(t) }, [])
  const restante = Math.max(0, new Date(inicio).getTime() + duracaoMin * 60000 - agora)
  const h = Math.floor(restante / 3600000), m = Math.floor((restante % 3600000) / 60000), s = Math.floor((restante % 60000) / 1000)
  return (
    <span className={clsx('chip num !text-sm', restante < 15 * 60000 ? 'text-errado border-errado/50' : 'text-texto')}>
      <Timer className="size-3.5" /> {h}:{String(m).padStart(2, '0')}:{String(s).padStart(2, '0')}
    </span>
  )
}

export default function Resolver() {
  const { id } = useParams()
  const blocoId = Number(id)
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [tutor, setTutor] = useState(false)
  const { data, error } = useQuery({ queryKey: ['bloco', blocoId], queryFn: () => api.get<BlocoDetalhe>(`/api/blocos/${blocoId}`) })

  const finalizar = useMutation({
    mutationFn: () => api.post(`/api/blocos/${blocoId}/finalizar`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['bloco', blocoId] }); qc.invalidateQueries({ queryKey: ['painel'] }) },
  })
  const refazer = useMutation({
    mutationFn: () => api.post<{ id: number }>('/api/blocos', { tipo: 'refazer', bloco_origem_id: blocoId }),
    onSuccess: (r) => nav(`/blocos/${r.id}`),
  })

  const b = data?.bloco
  const simuladoAberto = b?.tipo === 'simulado' && !b.finalizado_em
  // Durante a correção em lote do simulado, recarrega até não haver pendentes.
  const pendentes = data?.questoes.some((q) => q.veredito === 'pendente') ?? false
  useEffect(() => {
    if (!pendentes) return
    const t = setInterval(() => qc.invalidateQueries({ queryKey: ['bloco', blocoId] }), 2500)
    return () => clearInterval(t)
  }, [pendentes, blocoId, qc])

  // Fixa o índice inicial na URL para que a tela não "pule" quando o bloco é recarregado após responder.
  useEffect(() => {
    if (data && !params.get('i')) {
      const aberta = data.questoes.findIndex((q) => !q.respondida)
      setParams({ i: String(aberta >= 0 ? aberta : 0) }, { replace: true })
    }
  }, [data, params, setParams])

  if (error) return <div className="p-8"><ErroCaixa erro={error} /></div>
  if (!data || !b) return <Carregando />

  const total = data.questoes.length
  const i = Math.min(total - 1, Math.max(0, Number(params.get('i') ?? 0)))
  const ir = (n: number) => setParams({ i: String(Math.min(total - 1, Math.max(0, n))) })
  const atual = data.questoes[i]
  const terminou = data.respondidas === total
  const est = data.estatistica_no_bloco

  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0 overflow-y-auto">
        <div className="sticky top-0 z-10 bg-tinta/85 backdrop-blur border-b border-borda px-8 py-3">
          <div className="flex items-center gap-3">
            <Link to="/blocos" className="btn btn-fantasma !p-1.5"><ArrowLeft className="size-4" /></Link>
            <div className="min-w-0">
              <p className="titulo text-lg leading-tight truncate">{b.nome}</p>
              <p className="text-[11px] text-apagado">
                {b.criado_por === 'coach' && <span className="text-hema">criado pelo coach · </span>}
                questão <span className="num">{i + 1}/{total}</span> · <span className="num">{data.respondidas}</span> respondidas
                {est && est.respondidas > 0 && <> · aproveitamento no bloco <span className="num text-texto">{pct(est.aproveitamento_bruto)}</span></>}
              </p>
            </div>
            <span className="flex-1" />
            {b.tipo === 'simulado' && simuladoAberto && b.iniciado_em && <Cronometro inicio={b.iniciado_em} duracaoMin={b.config.duracao_min ?? 240} />}
            {simuladoAberto && (
              <button className="btn btn-primario" disabled={finalizar.isPending}
                      onClick={() => confirm(`Finalizar e corrigir ${data.respondidas} respostas?`) && finalizar.mutate()}>
                <Flag className="size-4" /> Finalizar e corrigir
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-1 mt-3">
            {data.questoes.map((q, j) => (
              <button
                key={q.id} onClick={() => ir(j)} title={`${j + 1} · ${AREA_CURTA[q.area]}`}
                className={clsx(
                  'size-3.5 rounded-[4px] border transition',
                  q.veredito ? COR[q.veredito] : q.respondida ? 'bg-hema/60 border-hema' : 'border-borda-forte hover:border-hema',
                  j === i && 'ring-2 ring-texto/80 ring-offset-1 ring-offset-tinta',
                )}
              />
            ))}
          </div>
        </div>

        <div className="max-w-3xl mx-auto px-8 py-8">
          {terminou && !simuladoAberto && est && i === total - 1 && atual.veredito && (
            <div className="cartao p-6 mb-8 flex items-center gap-6 entrar">
              <Anel valor={est.aproveitamento_firme} tamanho={84} cor="var(--color-eosina)">
                <span className="num text-sm">{pct(est.aproveitamento_firme)}</span>
              </Anel>
              <div className="flex-1">
                <p className="titulo text-xl">Bloco concluído</p>
                <p className="text-sm text-suave mt-1">
                  {est.corretas} corretas · {est.parciais} parciais · {est.incorretas} incorretas · {est.chutes} chutes.
                  Domínio firme {pct(est.aproveitamento_firme)} {(est.aproveitamento_firme ?? 0) >= 0.8 ? '— dominado! 🎯' : '— abaixo de 80%.'}
                </p>
              </div>
              {est.n_refazer > 0 && (
                <button className="btn" onClick={() => refazer.mutate()}><RotateCcw className="size-4" /> Refazer {est.n_refazer}</button>
              )}
            </div>
          )}
          {b.tipo === 'simulado' && b.finalizado_em && pendentes && (
            <p className="cartao p-4 mb-6 text-sm text-suave pulsar">Corrigindo o simulado em lote com o Claude…</p>
          )}
          <QuestaoView
            key={atual.id}
            questaoId={atual.id}
            blocoId={blocoId}
            simuladoAberto={simuladoAberto}
            aoAvancar={i < total - 1 ? () => ir(i + 1) : undefined}
            aoVoltar={i > 0 ? () => ir(i - 1) : undefined}
            tutorAberto={tutor}
            alternarTutor={() => !simuladoAberto && setTutor((t) => !t)}
          />
        </div>
      </div>
      {tutor && !simuladoAberto && <Tutor questaoId={atual.id} aoFechar={() => setTutor(false)} />}
    </div>
  )
}
