import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { CheckCircle2, CircleAlert, FileUp, Loader2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { enviarArquivos, type ResultadoEnvio } from '../api'
import { ErroCaixa } from './ui'

export const ACEITOS = '.pdf,.png,.jpg,.jpeg,.webp,.txt,.md,.html,.htm'

function Resultado({ r }: { r: ResultadoEnvio }) {
  if (r.erro) return <li className="text-xs text-errado flex gap-1.5"><CircleAlert className="size-3.5 shrink-0 mt-0.5" /> {r.arquivo}: {r.erro}</li>
  const etapa = r.ja_existia ? 'já estava na biblioteca'
    : !r.tarefa_id ? (r.conversao_local ? 'pesquisável já; Markdown/OCR na GPU em seguida' : 'pesquisável')
    : r.conversao_local ? (r.precisa_transcricao ? 'OCR na GPU em seguida, depois catalogação' : 'conversão para Markdown na GPU, depois catalogação')
    : r.precisa_transcricao ? 'sem texto: o bibliotecário vai transcrever' : 'texto extraído; bibliotecário catalogando'
  return (
    <li className="text-xs flex gap-1.5">
      <CheckCircle2 className="size-3.5 shrink-0 mt-0.5 text-certo" />
      <span><Link to={`/biblioteca/${r.id}`} className="text-hema hover:underline">{r.titulo}</Link>
        <span className="text-apagado"> · {r.paginas ? `${r.paginas} p. · ` : ''}{etapa}</span></span>
    </li>
  )
}

export default function EnviarArquivos() {
  const qc = useQueryClient()
  const entrada = useRef<HTMLInputElement>(null)
  const [arrastando, setArrastando] = useState(false)
  const [observacao, setObservacao] = useState('')
  const [confiabilidade, setConfiabilidade] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [progresso, setProgresso] = useState('')
  const [resultados, setResultados] = useState<ResultadoEnvio[]>([])
  const [erro, setErro] = useState<unknown>(null)

  async function enviar(lista: FileList | File[]) {
    const arquivos = [...lista]
    if (!arquivos.length) return
    setEnviando(true); setErro(null); setResultados([])
    try {
      // Lotes de 10 por requisição; nenhum arquivo é deixado de fora.
      for (let i = 0; i < arquivos.length; i += 10) {
        setProgresso(`${Math.min(i + 10, arquivos.length)} de ${arquivos.length}`)
        // Envios em massa (mais de 3 arquivos) só são extraídos e convertidos, sem catalogação paga pelo Claude.
        const catalogar = arquivos.length <= 3 ? 'true' : 'false'
        const r = await enviarArquivos(arquivos.slice(i, i + 10), { observacao, confiabilidade, origem: 'biblioteca', catalogar })
        setResultados((ant) => [...ant, ...r])
      }
      setObservacao('')
      for (const k of ['biblioteca', 'tarefas', 'preceptor', 'avisos']) qc.invalidateQueries({ queryKey: [k] })
    } catch (e) { setErro(e) } finally { setEnviando(false); setProgresso('') }
  }

  return (
    <div className="space-y-2">
      <button type="button" onClick={() => entrada.current?.click()} disabled={enviando}
              onDragOver={(e) => { e.preventDefault(); setArrastando(true) }} onDragLeave={() => setArrastando(false)}
              onDrop={(e) => { e.preventDefault(); setArrastando(false); enviar(e.dataTransfer.files) }}
              className={clsx('w-full rounded-xl border-2 border-dashed px-4 py-6 text-center transition',
                arrastando ? 'border-hema bg-hema/10' : 'border-borda-forte hover:border-hema/70')}>
        {enviando ? <Loader2 className="size-6 mx-auto animate-spin text-hema" /> : <FileUp className="size-6 mx-auto text-hema" />}
        <p className="text-sm mt-2">{enviando ? `Enviando e extraindo… ${progresso}` : 'Arraste PDFs ou fotos de páginas, ou clique para escolher'}</p>
        <p className="text-[11px] text-apagado mt-1">PDF, imagem, texto ou HTML · até 250 MB cada · até 3 arquivos ganham catalogação e nota do bibliotecário; mais que isso, só texto e Markdown (sem tokens)</p>
      </button>
      <input ref={entrada} type="file" multiple accept={ACEITOS} className="hidden" onChange={(e) => { if (e.target.files) enviar(e.target.files); e.target.value = '' }} />
      <textarea className="campo text-sm" rows={2} placeholder="Opcional: o que é e o que extrair (ex.: “Diretriz SBC 2025 de HAS; quero nota dos alvos pressóricos”)"
                value={observacao} onChange={(e) => setObservacao(e.target.value)} />
      <select className="campo text-sm" value={confiabilidade} onChange={(e) => setConfiabilidade(e.target.value)}>
        <option value="">Confiabilidade: o bibliotecário decide</option>
        <option value="oficial">Oficial (MS, CONITEC, governo)</option>
        <option value="sociedade">Sociedade médica</option>
        <option value="literatura">Literatura</option>
      </select>
      <ErroCaixa erro={erro} />
      {resultados.length > 0 && <ul className="space-y-1.5 pt-1">{resultados.map((r, i) => <Resultado key={i} r={r} />)}</ul>}
    </div>
  )
}
