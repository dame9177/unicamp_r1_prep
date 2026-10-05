import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Brain, CalendarDays, CheckCircle2, Circle, Flame, Lightbulb, Sparkles, Stethoscope, Target, TriangleAlert } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { api, AREA_CURTA, pct, type Painel as TPainel } from '../api'
import MapaDominio from '../components/MapaDominio'
import { Anel, Barra, Carregando, ErroCaixa, Markdown } from '../components/ui'

function saudacao() {
  const h = new Date().getHours()
  return h < 5 ? 'Madrugada de estudo' : h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite'
}

function Serie({ serie }: { serie: TPainel['serie'] }) {
  const dias: { dia: string; n: number; pontos: number }[] = []
  for (let i = 20; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10)
    dias.push(serie.find((s) => s.dia === d) ?? { dia: d, n: 0, pontos: 0 })
  }
  const max = Math.max(10, ...dias.map((d) => d.n))
  return (
    <div className="flex items-end gap-1 h-24">
      {dias.map((d) => (
        <div key={d.dia} className="flex-1 flex flex-col justify-end h-full group relative"
             title={`${d.dia.slice(8)}/${d.dia.slice(5, 7)}: ${d.n} questões, ${d.n ? Math.round((d.pontos / d.n) * 100) : 0}%`}>
          <div className="rounded-t bg-hema/25 relative" style={{ height: `${(d.n / max) * 100}%` }}>
            <div className="absolute bottom-0 inset-x-0 rounded-t bg-hema" style={{ height: `${d.n ? (d.pontos / d.n) * 100 : 0}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

export default function Painel() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const { data: p, error } = useQuery({ queryKey: ['painel'], queryFn: () => api.get<TPainel>('/api/painel') })
  const iniciar = useMutation({
    mutationFn: (tema_id: string) => api.post<{ id: number }>('/api/blocos', { tipo: 'tema', tema_id }),
    onSuccess: (r) => nav(`/blocos/${r.id}`),
  })
  const ronda = useMutation({
    mutationFn: () => api.post('/api/preceptor/ronda', {}),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['preceptor'] }); nav('/preceptor') },
  })
  const marcar = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api.patch(`/api/agenda/${id}`, { status }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['painel'] }); qc.invalidateQueries({ queryKey: ['agenda'] }) },
  })
  if (error) return <div className="p-8"><ErroCaixa erro={error} /></div>
  if (!p) return <Carregando />

  const t = p.totais
  const firmeGeral = p.areas.length
    ? p.areas.reduce((s, a) => s + (a.aproveitamento_firme ?? 0) * a.respondidas, 0) / Math.max(1, p.areas.reduce((s, a) => s + a.respondidas, 0))
    : null
  const proximo = p.prioritarios[0]

  return (
    <div className="max-w-6xl mx-auto px-8 py-8 space-y-6 entrar">
      {/* Linha 1: contagem regressiva + próximo passo */}
      <section className="grid grid-cols-12 gap-6">
        <div className="cartao col-span-7 p-7 relative overflow-hidden">
          <div className="absolute -right-16 -top-16 size-64 rounded-full bg-eosina/10 blur-3xl" />
          <p className="text-suave text-sm">{saudacao()}{p.nome ? `, ${p.nome}` : ''}.</p>
          <div className="flex items-end gap-4 mt-2">
            <p className="titulo text-7xl leading-none text-eosina num">{p.dias_ate_prova}</p>
            <p className="titulo text-2xl text-texto/90 pb-1.5">dias até a prova<br />
              <span className="text-base text-suave font-sans">15 de novembro · Unicamp</span></p>
          </div>
          <div className="grid grid-cols-3 gap-4 mt-7">
            <div>
              <p className="text-[11px] uppercase tracking-wider text-apagado">Questões feitas</p>
              <p className="num text-xl mt-1">{t.questoes_distintas}<span className="text-apagado text-sm">/{t.questoes_banco}</span></p>
              <Barra valor={t.questoes_distintas / t.questoes_banco} className="mt-2" />
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-apagado">Domínio firme</p>
              <p className="num text-xl mt-1">{pct(firmeGeral)}</p>
              <p className="text-[11px] text-apagado mt-1">sem contar chutes</p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-apagado">Hoje · meta {p.meta_diaria}</p>
              <p className="num text-xl mt-1 flex items-center gap-1.5">{t.hoje}<span className="text-apagado text-sm">/{p.meta_diaria}</span>
                {t.hoje >= p.meta_diaria && <Flame className="size-4 text-parcial" />}</p>
              <Barra valor={t.hoje / Math.max(1, p.meta_diaria)} cor={t.hoje >= p.meta_diaria ? 'bg-eosina' : 'bg-hema'} className="mt-2" />
            </div>
          </div>
        </div>

        <div className="cartao col-span-5 p-6 flex flex-col">
          <p className="text-[11px] uppercase tracking-wider text-apagado flex items-center gap-1.5"><Target className="size-3.5" /> Próximo passo</p>
          {proximo ? (
            <>
              <p className="titulo text-2xl mt-2 leading-snug">{proximo.nome}</p>
              <p className="text-suave text-sm mt-1">{proximo.area} · {proximo.total} questões · domínio {pct(proximo.aproveitamento_firme)}</p>
              <button className="btn btn-primario mt-5 self-start" disabled={iniciar.isPending} onClick={() => iniciar.mutate(proximo.id)}>
                Começar bloco <ArrowRight className="size-4" />
              </button>
              <div className="mt-auto pt-5 space-y-2">
                {p.prioritarios.slice(1).map((t) => (
                  <Link key={t.id} to={`/temas/${t.id}`} className="flex items-center justify-between text-sm text-suave hover:text-texto">
                    <span className="truncate">{t.nome}</span>
                    <span className="num text-xs text-apagado">{AREA_CURTA[t.area]}</span>
                  </Link>
                ))}
              </div>
            </>
          ) : <p className="text-suave mt-3">Tudo dominado. Hora dos simulados!</p>}
        </div>
      </section>

      {/* Linha 2: missões e agenda de hoje, flashcards, Preceptor */}
      <section className="grid grid-cols-12 gap-6">
        <div className="cartao col-span-6 p-6">
          <p className="text-[11px] uppercase tracking-wider text-apagado flex items-center gap-1.5"><Sparkles className="size-3.5" /> Missões de hoje</p>
          {p.missoes.length ? (
            <ul className="mt-3 space-y-2.5">
              {p.missoes.map((m) => (
                <li key={m.id} className="flex gap-2.5">
                  <Circle className="size-4 text-hema mt-0.5 shrink-0" />
                  <div>
                    <p className="text-sm">{m.titulo}</p>
                    {m.conteudo_md && <p className="text-xs text-suave mt-0.5">{m.conteudo_md}</p>}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-suave mt-3">Sem missões ainda. O Preceptor publica as do dia na primeira ronda.</p>
          )}
          {p.agenda_hoje.length > 0 && (
            <>
              <Link to="/agenda" className="text-[11px] uppercase tracking-wider text-apagado flex items-center gap-1.5 mt-5 hover:text-suave"><CalendarDays className="size-3.5" /> Agenda de hoje</Link>
              <ul className="mt-2 space-y-1.5">
                {p.agenda_hoje.map((a) => (
                  <li key={a.id} className="flex gap-2.5 items-start">
                    <button onClick={() => marcar.mutate({ id: a.id, status: a.status === 'feito' ? 'planejado' : 'feito' })} title="Marcar como feito">
                      {a.status === 'feito' ? <CheckCircle2 className="size-4 text-certo mt-0.5" /> : <Circle className="size-4 text-suave mt-0.5" />}
                    </button>
                    <p className={a.status === 'feito' ? 'text-sm line-through text-apagado' : 'text-sm'}>{a.titulo}
                      {a.minutos ? <span className="text-[11px] text-apagado num"> · {a.minutos} min</span> : null}</p>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <Link to="/flashcards" className="cartao col-span-3 p-6 hover:border-eosina/60 transition group">
          <p className="text-[11px] uppercase tracking-wider text-apagado flex items-center gap-1.5"><Brain className="size-3.5" /> Flashcards</p>
          <p className="num text-4xl mt-3 text-eosina">{p.flashcards_vencidos}</p>
          <p className="text-sm text-suave">para revisar agora</p>
          <p className="text-xs text-hema mt-4 group-hover:underline">Revisar →</p>
        </Link>
        <div className="cartao col-span-3 p-6 flex flex-col">
          <Link to="/preceptor" className="text-[11px] uppercase tracking-wider text-apagado flex items-center gap-1.5 hover:text-suave"><Stethoscope className="size-3.5" /> Preceptor</Link>
          <p className="text-sm text-suave mt-3 flex-1">
            {p.ultima_analise ? <>Última ronda: {new Date(p.ultima_analise.criado_em).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}.<br /></> : 'Nenhuma ronda ainda. '}
            {p.tentativas_desde_analise} respostas novas desde então. Ele roda sozinho em segundo plano.
          </p>
          <button className={p.coach_sugerido ? 'btn btn-primario mt-3' : 'btn mt-3'} disabled={ronda.isPending} onClick={() => ronda.mutate()}>
            Ronda agora
          </button>
        </div>
      </section>

      {/* Mapa de domínio */}
      <section className="cartao p-6">
        <div className="flex items-baseline justify-between mb-4">
          <h2 className="titulo text-xl">Mapa de domínio</h2>
          <div className="flex items-center gap-4 text-[11px] text-suave">
            <span className="flex items-center gap-1.5"><span className="size-3 rounded border border-dashed border-borda-forte" /> não iniciado</span>
            <span className="flex items-center gap-1.5"><span className="size-3 rounded bg-hema/50" /> em progresso</span>
            <span className="flex items-center gap-1.5"><span className="size-3 rounded bg-eosina/70" /> dominado (≥80%)</span>
            <span className="flex items-center gap-1.5"><span className="size-3 rounded ring-2 ring-parcial/70" /> revisar</span>
          </div>
        </div>
        <MapaDominio mapa={p.mapa} />
      </section>

      {/* Áreas + ritmo */}
      <section className="grid grid-cols-12 gap-6">
        <div className="cartao col-span-7 p-6">
          <h2 className="titulo text-lg mb-4">Áreas</h2>
          <div className="grid grid-cols-5 gap-2">
            {p.areas.map((a) => (
              <div key={a.area} className="flex flex-col items-center text-center">
                <Anel valor={a.aproveitamento_firme} tamanho={76} cor={a.status === 'dominado' ? 'var(--color-eosina)' : 'var(--color-hema)'}>
                  <span className="num text-sm">{pct(a.aproveitamento_firme)}</span>
                </Anel>
                <p className="text-xs mt-2">{AREA_CURTA[a.area]}</p>
                <p className="num text-[11px] text-apagado">{a.respondidas}/{a.total}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="cartao col-span-5 p-6">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="titulo text-lg">Ritmo · 21 dias</h2>
            <span className="text-[11px] text-apagado">barra cheia = acertos</span>
          </div>
          <Serie serie={p.serie} />
        </div>
      </section>

      {/* Insights + blocos abertos */}
      {(p.insights.length > 0 || p.blocos_abertos.length > 0 || p.revisar.length > 0) && (
        <section className="grid grid-cols-12 gap-6">
          <div className="col-span-7 space-y-3">
            {p.insights.map((i) => (
              <div key={i.id} className="cartao p-5 flex gap-3">
                {i.tipo === 'alerta' ? <TriangleAlert className="size-5 text-parcial shrink-0" /> : <Lightbulb className="size-5 text-hema shrink-0" />}
                <div>
                  <p className="font-medium text-sm">{i.titulo}</p>
                  <Markdown className="text-sm text-suave !leading-relaxed">{i.conteudo_md}</Markdown>
                </div>
              </div>
            ))}
            {p.revisar.length > 0 && (
              <div className="cartao p-5">
                <p className="text-sm font-medium mb-2">Dominados há mais de 14 dias — vale revisar</p>
                {p.revisar.map((t) => <Link key={t.id} to={`/temas/${t.id}`} className="block text-sm text-parcial hover:underline">{t.nome}</Link>)}
              </div>
            )}
          </div>
          <div className="col-span-5 space-y-3">
            {p.blocos_abertos.map((b) => (
              <Link key={b.id} to={`/blocos/${b.id}`} className="cartao p-4 flex items-center gap-3 hover:border-hema transition">
                <CheckCircle2 className="size-4 text-hema" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm truncate">{b.nome}</p>
                  <Barra valor={b.respondidas / Math.max(1, b.total)} className="mt-1.5" />
                </div>
                <span className="num text-xs text-apagado">{b.respondidas}/{b.total}</span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
