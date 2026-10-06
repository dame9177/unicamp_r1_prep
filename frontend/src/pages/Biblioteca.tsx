import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { BookMarked, FileText, Library, Link2, Search, StickyNote } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type AchadoBiblioteca, type EstadoConversor, type ItemBiblioteca } from '../api'
import Cadernos from '../components/Cadernos'
import EnviarArquivos from '../components/EnviarArquivos'
import ListaTarefas, { NovaTarefa } from '../components/Tarefas'
import { Cabecalho, Carregando, ConfChip, ErroCaixa, Markdown } from '../components/ui'

interface Catalogo { itens: ItemBiblioteca[]; total: number; caracteres: number; conversor: EstadoConversor }

function tamanho(c: number) {
  return c > 1e6 ? `${(c / 1e6).toFixed(1)} M car.` : c > 1e3 ? `${Math.round(c / 1e3)} mil car.` : `${c} car.`
}

function Adicionar() {
  const qc = useQueryClient()
  const [f, setF] = useState({ url: '', titulo: '', orgao: '', ano: '', confiabilidade: 'oficial' })
  const capturar = useMutation({
    mutationFn: () => api.post<{ id?: string; armazenado?: boolean; ja_existia?: boolean; links_documentos?: { url: string; texto: string }[] }>(
      '/api/biblioteca/capturar', { ...f, ano: f.ano ? Number(f.ano) : null, titulo: f.titulo || null, orgao: f.orgao || null }),
    onSuccess: (r) => { if (r.id) { setF({ url: '', titulo: '', orgao: '', ano: '', confiabilidade: 'oficial' }); qc.invalidateQueries({ queryKey: ['biblioteca'] }) } },
  })
  const r = capturar.data
  return (
    <div className="space-y-2">
      <input className="campo text-sm" placeholder="URL do PDF ou da página (gov.br, CONITEC, sociedade…)" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
      <div className="grid grid-cols-[1fr_120px] gap-2">
        <input className="campo text-sm" placeholder="Título oficial" value={f.titulo} onChange={(e) => setF({ ...f, titulo: e.target.value })} />
        <input className="campo text-sm num" placeholder="Ano" value={f.ano} onChange={(e) => setF({ ...f, ano: e.target.value.replace(/\D/g, '') })} />
      </div>
      <div className="grid grid-cols-[1fr_140px] gap-2">
        <input className="campo text-sm" placeholder="Órgão (Ministério da Saúde, SBP…)" value={f.orgao} onChange={(e) => setF({ ...f, orgao: e.target.value })} />
        <select className="campo text-sm" value={f.confiabilidade} onChange={(e) => setF({ ...f, confiabilidade: e.target.value })}>
          <option value="oficial">Oficial</option><option value="sociedade">Sociedade</option><option value="literatura">Literatura</option>
        </select>
      </div>
      <button className="btn btn-primario w-full justify-center" disabled={f.url.length < 8 || capturar.isPending} onClick={() => capturar.mutate()}>
        <Link2 className="size-4" /> {capturar.isPending ? 'Baixando e indexando…' : 'Capturar documento integral'}
      </button>
      <ErroCaixa erro={capturar.error} />
      {r?.id && <p className="text-xs text-certo">{r.ja_existia ? 'Já estava na biblioteca: ' : 'Guardado: '}<Link className="underline" to={`/biblioteca/${r.id}`}>{r.id}</Link></p>}
      {r?.armazenado === false && (
        <div className="text-xs text-suave">
          <p>É uma página-índice. Documentos encontrados:</p>
          {r.links_documentos?.slice(0, 8).map((l) => (
            <button key={l.url} className="block text-left text-hema hover:underline truncate w-full" onClick={() => setF({ ...f, url: l.url, titulo: f.titulo || l.texto })}>{l.texto || l.url}</button>
          ))}
        </div>
      )}
    </div>
  )
}

function Resultados({ q }: { q: string }) {
  const { data, isFetching } = useQuery({
    queryKey: ['biblioteca', 'busca', q],
    queryFn: () => api.get<AchadoBiblioteca[]>(`/api/biblioteca/buscar?q=${encodeURIComponent(q)}`),
  })
  if (!data) return <Carregando texto="Buscando…" />
  if (!data.length) return <p className="text-sm text-suave py-6">Nada encontrado para “{q}”.{isFetching && ' …'}</p>
  return (
    <div className="space-y-2">
      {data.map((r, i) => (
        <Link key={i} to={`/biblioteca/${r.doc_id}${r.local.startsWith('p. ') ? `?pagina=${r.local.slice(3)}` : ''}`}
              className="cartao p-4 block hover:border-hema transition">
          <div className="flex items-center gap-2">
            <ConfChip c={r.confiabilidade} />
            <p className="text-sm font-medium truncate flex-1">{r.titulo}</p>
            <span className="text-[11px] text-apagado shrink-0">{r.orgao ?? ''}{r.ano ? ` · ${r.ano}` : ''} · {r.local}</span>
          </div>
          <Markdown className="text-xs text-suave mt-2 !leading-relaxed">{r.trecho}</Markdown>
        </Link>
      ))}
    </div>
  )
}

export default function Biblioteca() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const [busca, setBusca] = useState(q)
  const [tipo, setTipo] = useState<'' | 'documento' | 'nota'>('')
  const [conf, setConf] = useState('')
  const { data, error } = useQuery({
    queryKey: ['biblioteca', 'catalogo'],
    queryFn: () => api.get<Catalogo>('/api/biblioteca'),
    refetchInterval: (q) => (q.state.data?.conversor.na_fila || q.state.data?.conversor.convertendo ? 8000 : false),
  })
  if (error) return <div className="p-8"><ErroCaixa erro={error} /></div>
  if (!data) return <Carregando />
  const itens = data.itens.filter((i) => (!tipo || i.tipo === tipo) && (!conf || i.confiabilidade === conf))
  const docs = data.itens.filter((i) => i.tipo === 'documento').length

  return (
    <div className="max-w-7xl mx-auto px-8 py-8 entrar">
      <Cabecalho
        titulo={<span className="flex items-center gap-3"><Library className="size-7 text-certo" /> Biblioteca</span>}
        sub="Documentos oficiais com texto integral e notas verificadas, guardados pelos agentes e por você. Todo agente consulta aqui antes de ir à web."
      />
      <div className="grid grid-cols-12 gap-6">
        <section className="col-span-8 space-y-4">
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setParams(busca ? { q: busca } : {}) }}>
            <div className="relative flex-1">
              <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-apagado" />
              <input className="campo !pl-9" placeholder="Buscar no texto completo (ex.: sífilis gestante tratamento)" value={busca} onChange={(e) => setBusca(e.target.value)} />
            </div>
            <button className="btn btn-primario">Buscar</button>
            {q && <button type="button" className="btn btn-fantasma" onClick={() => { setBusca(''); setParams({}) }}>Limpar</button>}
          </form>

          {q ? <Resultados q={q} /> : (
            <div className="cartao p-0 overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-3 border-b border-borda text-sm">
                <span className="text-suave flex-1">{docs} documentos · {data.total - docs} notas · {tamanho(data.caracteres)}</span>
                <select className="campo !w-36 !py-1 text-xs" value={tipo} onChange={(e) => setTipo(e.target.value as typeof tipo)}>
                  <option value="">Tudo</option><option value="documento">Documentos</option><option value="nota">Notas</option>
                </select>
                <select className="campo !w-36 !py-1 text-xs" value={conf} onChange={(e) => setConf(e.target.value)}>
                  <option value="">Qualquer fonte</option><option value="oficial">Oficial</option><option value="sociedade">Sociedade</option>
                  <option value="literatura">Literatura</option><option value="nota">Notas</option>
                </select>
              </div>
              {itens.length === 0 ? (
                <div className="p-10 text-center">
                  <BookMarked className="size-8 mx-auto text-apagado" />
                  <p className="titulo text-lg mt-3">A biblioteca começa aqui</p>
                  <p className="text-sm text-suave mt-1 max-w-md mx-auto">O tutor e o juiz guardam os documentos oficiais que consultam; o bibliotecário trabalha em segundo plano nas lacunas que o Preceptor apontar. Você também pode adicionar por URL.</p>
                </div>
              ) : (
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-borda">
                    {itens.map((i) => (
                      <tr key={i.id} className={clsx('hover:bg-lamina-2/60', i.status !== 'vigente' && 'opacity-55')}>
                        <td className="px-4 py-2.5">
                          <Link to={`/biblioteca/${i.id}`} className="flex items-center gap-2 hover:text-hema">
                            {i.tipo === 'nota' ? <StickyNote className="size-3.5 text-eosina shrink-0" /> : <FileText className="size-3.5 text-certo shrink-0" />}
                            <span className="truncate max-w-md">{i.titulo}</span>
                          </Link>
                          <p className="text-[11px] text-apagado mt-0.5 pl-5.5">{i.orgao ?? '—'}{i.ano ? ` · ${i.ano}` : ''}{i.categoria ? ` · ${i.categoria}` : ''} · por {i.criado_por}</p>
                        </td>
                        <td className="px-2"><ConfChip c={i.confiabilidade} /></td>
                        <td className="px-2 text-[11px] text-apagado">{i.status === 'vigente' ? '' : i.status === 'substituido' ? 'substituído' : 'em revisão'}
                          {(i.conversao === 'pendente' || i.conversao === 'executando') && <span className="text-hema"> · convertendo</span>}</td>
                        <td className="px-4 text-right text-[11px] text-apagado num whitespace-nowrap">{i.paginas ? `${i.paginas} p.` : tamanho(i.caracteres)} · {i.acessos} usos</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          <details className="cartao p-5">
            <summary className="cursor-pointer titulo text-lg">Cadernos dos agentes</summary>
            <div className="mt-4"><Cadernos /></div>
          </details>
        </section>

        <aside className="col-span-4 space-y-6">
          <div className="cartao p-5">
            <h2 className="titulo text-lg mb-3">Enviar arquivos</h2>
            <EnviarArquivos />
            <p className="text-[11px] text-apagado mt-3">
              {data.conversor.disponivel
                ? <>Conversor local (GPU) ativo: Markdown com tabelas e OCR sem gastar tokens.{data.conversor.convertendo ? <> Convertendo <b>{data.conversor.convertendo}</b>.</> : ''}{data.conversor.na_fila ? ` ${data.conversor.na_fila} na fila.` : ''}</>
                : 'Conversor local não instalado: o texto é extraído de forma simples, e o bibliotecário transcreve PDFs escaneados.'}
            </p>
          </div>
          <div className="cartao p-5">
            <h2 className="titulo text-lg mb-3">Adicionar por URL</h2>
            <Adicionar />
          </div>
          <div className="cartao p-5">
            <h2 className="titulo text-lg mb-3">Pedir ao bibliotecário</h2>
            <NovaTarefa />
            <div className="mt-4"><ListaTarefas limite={6} /></div>
          </div>
        </aside>
      </div>
    </div>
  )
}
