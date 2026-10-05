import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ChevronLeft, ChevronRight, ExternalLink, FileDown, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, type ItemBiblioteca, type TextoBiblioteca } from '../api'
import { Carregando, ConfChip, ErroCaixa, Markdown } from '../components/ui'

const JANELA = 3

/** Em notas de fonte única, “[p. 7; p. 36-37]” vira links para as páginas do documento. */
function linkarPaginas(texto: string, id: string) {
  return texto.replace(/\[((?:\s*p\.\s*\d+(?:-\d+)?\s*[;,]?)+)\]/g, (_m, dentro: string) =>
    dentro.replace(/p\.\s*(\d+)(-\d+)?/g, (_x, n: string, r?: string) => `[p. ${n}${r ?? ''}](/biblioteca/${id}?pagina=${n})`))
}

function TextoPdf({ texto }: { texto: string }) {
  const partes = texto.split(/\[\[página (\d+)\]\]/)
  const blocos: { n: string; t: string }[] = []
  for (let i = 1; i < partes.length; i += 2) blocos.push({ n: partes[i], t: partes[i + 1] })
  if (!blocos.length) return <pre className="whitespace-pre-wrap text-sm leading-relaxed font-sans">{texto}</pre>
  return (
    <div className="space-y-6">
      {blocos.map((b) => (
        <div key={b.n} id={`p${b.n}`}>
          <p className="text-[11px] uppercase tracking-wider text-apagado border-b border-borda pb-1 mb-2">Página {b.n}</p>
          <pre className="whitespace-pre-wrap text-sm leading-relaxed font-sans text-texto/90">{b.t.trim()}</pre>
        </div>
      ))}
    </div>
  )
}

export default function BibliotecaDoc() {
  const { id = '' } = useParams()
  return <Documento key={id} id={id} />
}

function Documento({ id }: { id: string }) {
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const pagina = Number(params.get('pagina') || 1)
  const [inicio, setInicio] = useState(0)
  const [acumulado, setAcumulado] = useState('')
  const { data: doc, error } = useQuery({ queryKey: ['biblioteca', 'doc', id], queryFn: () => api.get<ItemBiblioteca>(`/api/biblioteca/${id}`) })
  const ehPdf = doc?.formato === 'pdf'
  const { data: trecho, error: erroTexto } = useQuery({
    queryKey: ['biblioteca', 'texto', id, ehPdf ? pagina : inicio],
    enabled: !!doc,
    queryFn: () => api.get<TextoBiblioteca>(ehPdf
      ? `/api/biblioteca/${id}/texto?pagina=${pagina}&ate_pagina=${Math.min(pagina + JANELA - 1, doc!.paginas ?? pagina)}&max_caracteres=40000`
      : `/api/biblioteca/${id}/texto?inicio=${inicio}&max_caracteres=40000`),
  })
  useEffect(() => { if (trecho && !ehPdf) setAcumulado((a) => (inicio === 0 ? trecho.texto : a + trecho.texto)) }, [trecho, ehPdf, inicio])
  useEffect(() => { window.scrollTo({ top: 0 }) }, [pagina])
  const editar = useMutation({
    mutationFn: (status: string) => api.patch(`/api/biblioteca/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['biblioteca'] }),
  })
  const apagar = useMutation({
    mutationFn: () => api.del(`/api/biblioteca/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['biblioteca'] }); nav('/biblioteca') },
  })
  if (error) return <div className="p-8"><ErroCaixa erro={error} /></div>
  if (!doc) return <Carregando />
  // Notas com uma única fonte citam só [p. N]: viram links para a página do documento.
  const fonteUnica = doc.tipo === 'nota' && doc.fontes?.length === 1 && !doc.fontes[0].startsWith('http') ? doc.fontes[0] : null
  const irPara = (p: number) => setParams({ pagina: String(Math.max(1, Math.min(p, doc.paginas ?? 1))) })

  return (
    <div className="max-w-4xl mx-auto px-8 py-8 entrar">
      <Link to="/biblioteca" className="text-sm text-suave hover:text-texto inline-flex items-center gap-1"><ArrowLeft className="size-4" /> Biblioteca</Link>
      <header className="mt-4 mb-6">
        <div className="flex items-center gap-2"><ConfChip c={doc.confiabilidade} />
          {doc.status !== 'vigente' && <span className="chip text-parcial border-parcial/40">{doc.status === 'substituido' ? 'Substituído' : 'Em revisão'}</span>}
        </div>
        <h1 className="titulo text-3xl mt-2 leading-tight">{doc.titulo}</h1>
        <p className="text-sm text-suave mt-1">{doc.orgao ?? '—'}{doc.ano ? ` · ${doc.ano}` : ''}{doc.categoria ? ` · ${doc.categoria}` : ''} · guardado por {doc.criado_por} em {new Date(doc.criado_em).toLocaleDateString('pt-BR')} · {doc.acessos} consultas</p>
        {doc.resumo && <p className="text-sm mt-3">{doc.resumo}</p>}
        {doc.status_motivo && <p className="text-xs text-apagado mt-1">{doc.status_motivo}</p>}
        {doc.fontes && doc.fontes.length > 0 && (
          <p className="text-xs text-suave mt-2">Fontes: {doc.fontes.map((f, i) => (
            <span key={f}>{i > 0 && ', '}{f.startsWith('http') ? <a className="text-hema hover:underline" href={f} target="_blank" rel="noreferrer">{f}</a> : <Link className="text-hema hover:underline" to={`/biblioteca/${f}`}>{f}</Link>}</span>
          ))}</p>
        )}
        <div className="flex flex-wrap gap-2 mt-4">
          {doc.url && <a className="btn btn-fantasma text-xs" href={doc.url} target="_blank" rel="noreferrer"><ExternalLink className="size-3.5" /> Fonte original</a>}
          {doc.tipo === 'documento' && <a className="btn btn-fantasma text-xs" href={`/api/biblioteca/${id}/original`} target="_blank" rel="noreferrer"><FileDown className="size-3.5" /> Arquivo baixado</a>}
          <select className="campo !w-40 !py-1 text-xs" value={doc.status} onChange={(e) => editar.mutate(e.target.value)}>
            <option value="vigente">Vigente</option><option value="substituido">Substituído</option><option value="em_revisao">Em revisão</option>
          </select>
          <button className="btn btn-fantasma text-xs text-errado" onClick={() => { if (confirm('Remover da biblioteca? Os agentes deixarão de consultá-lo.')) apagar.mutate() }}>
            <Trash2 className="size-3.5" /> Remover
          </button>
        </div>
      </header>

      <ErroCaixa erro={erroTexto} />
      {ehPdf && doc.paginas && (
        <div className="sticky top-0 z-10 bg-tinta/90 backdrop-blur py-2 mb-4 flex items-center gap-2 border-b border-borda">
          <button className="btn btn-fantasma !p-1.5" disabled={pagina <= 1} onClick={() => irPara(pagina - JANELA)}><ChevronLeft className="size-4" /></button>
          <span className="text-sm text-suave">Páginas</span>
          <input type="number" className="campo !w-20 !py-1 num text-sm" value={pagina} min={1} max={doc.paginas} onChange={(e) => irPara(Number(e.target.value))} />
          <span className="text-sm text-suave">a {Math.min(pagina + JANELA - 1, doc.paginas)} de {doc.paginas}</span>
          <button className="btn btn-fantasma !p-1.5" disabled={pagina + JANELA > doc.paginas} onClick={() => irPara(pagina + JANELA)}><ChevronRight className="size-4" /></button>
        </div>
      )}
      <article className="cartao p-6">
        {!trecho ? <Carregando /> : ehPdf ? <TextoPdf texto={trecho.texto} />
          : <Markdown>{fonteUnica ? linkarPaginas(acumulado || trecho.texto, fonteUnica) : (acumulado || trecho.texto)}</Markdown>}
        {trecho && !ehPdf && trecho.continua && (
          <button className="btn mt-4" onClick={() => setInicio(trecho.fim)}>Carregar mais ({Math.round((trecho.fim / trecho.total_caracteres) * 100)}% lido)</button>
        )}
      </article>
    </div>
  )
}
