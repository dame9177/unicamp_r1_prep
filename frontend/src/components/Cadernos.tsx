import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { FileText, NotebookPen } from 'lucide-react'
import { useState } from 'react'
import { api, type Agente } from '../api'
import { Markdown } from './ui'

interface Arquivo { caminho: string; bytes: number; modificado: number }

export default function Cadernos({ inicial = 'tutor', fixo }: { inicial?: string; fixo?: boolean }) {
  const [agente, setAgente] = useState(inicial)
  const [arquivo, setArquivo] = useState('MEMORIA.md')
  const { data: agentes } = useQuery({ queryKey: ['agentes'], queryFn: () => api.get<Agente[]>('/api/agentes') })
  const { data: arquivos } = useQuery({ queryKey: ['agentes', agente, 'arquivos'], queryFn: () => api.get<Arquivo[]>(`/api/agentes/${agente}/arquivos`) })
  const { data: conteudo } = useQuery({
    queryKey: ['agentes', agente, 'arquivo', arquivo],
    queryFn: () => api.get<{ conteudo: string }>(`/api/agentes/${agente}/arquivo?caminho=${encodeURIComponent(arquivo)}`),
    retry: false,
  })
  return (
    <div className="space-y-3">
      {!fixo && (
        <div className="flex flex-wrap gap-1.5">
          {agentes?.map((a) => (
            <button key={a.id} onClick={() => { setAgente(a.id); setArquivo('MEMORIA.md') }} title={a.descricao}
                    className={clsx('chip !py-1 !px-2.5 cursor-pointer', a.id === agente ? 'text-white bg-hema-escuro border-hema' : 'text-suave border-borda hover:border-hema')}>
              <NotebookPen className="size-3" /> {a.nome} <span className="num text-apagado">{a.arquivos}</span>
            </button>
          ))}
        </div>
      )}
      <div className="grid grid-cols-[220px_1fr] gap-4">
        <ul className="space-y-0.5 max-h-[60vh] overflow-y-auto">
          {arquivos?.map((f) => (
            <li key={f.caminho}>
              <button onClick={() => setArquivo(f.caminho)} className={clsx('w-full text-left text-xs rounded-lg px-2 py-1.5 flex items-center gap-1.5 transition',
                f.caminho === arquivo ? 'bg-lamina-2 text-texto' : 'text-suave hover:text-texto')}>
                <FileText className="size-3 shrink-0" /><span className="truncate">{f.caminho}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="rounded-xl border border-borda p-4 max-h-[60vh] overflow-y-auto min-w-0">
          {conteudo ? (arquivo.endsWith('.md') ? <Markdown className="text-sm">{conteudo.conteudo}</Markdown>
            : <pre className="text-xs whitespace-pre-wrap">{conteudo.conteudo}</pre>) : <p className="text-sm text-suave">Selecione um arquivo.</p>}
        </div>
      </div>
      <p className="text-[11px] text-apagado">Os cadernos são dos agentes: eles escrevem, você lê. Ficam em app_data/agentes/ (fora do git).</p>
    </div>
  )
}
