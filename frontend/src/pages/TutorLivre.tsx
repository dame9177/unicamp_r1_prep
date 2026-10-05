import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { MessageSquarePlus } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { api, type Chat } from '../api'
import Tutor from '../components/Tutor'

interface ChatResumo { id: number; titulo: string | null; atualizado_em: string }

export default function TutorLivre() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const atual = params.get('c') ? Number(params.get('c')) : null
  const { data: chats } = useQuery({ queryKey: ['chats-gerais'], queryFn: () => api.get<ChatResumo[]>('/api/chats') })
  const novo = useMutation({
    mutationFn: () => api.post<Chat>('/api/chats'),
    onSuccess: (c) => { qc.invalidateQueries({ queryKey: ['chats-gerais'] }); setParams({ c: String(c.chat.id) }) },
  })
  return (
    <div className="flex h-full">
      <aside className="w-64 shrink-0 border-r border-borda p-3 overflow-y-auto">
        <button className="btn btn-primario w-full justify-center mb-3" onClick={() => novo.mutate()} disabled={novo.isPending}>
          <MessageSquarePlus className="size-4" /> Nova conversa
        </button>
        {chats?.filter((c) => c.titulo || c.id === atual).map((c) => (
          <button key={c.id} onClick={() => setParams({ c: String(c.id) })}
                  className={clsx('block w-full text-left rounded-xl px-3 py-2 text-sm mb-1 transition',
                    c.id === atual ? 'bg-hema-escuro/70 text-white' : 'text-suave hover:bg-lamina-2 hover:text-texto')}>
            <p className="truncate">{c.titulo || 'Nova conversa'}</p>
            <p className="text-[10px] text-apagado">{new Date(c.atualizado_em).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</p>
          </button>
        ))}
      </aside>
      {atual ? <Tutor key={atual} chatId={atual} inteiro /> : (
        <div className="flex-1 grid place-items-center text-center px-8">
          <div>
            <p className="titulo text-2xl">Tutor livre</p>
            <p className="text-suave text-sm mt-2 max-w-md">Dúvidas que não estão presas a uma questão: um tema inteiro, uma diretriz nova, uma tabela de doses. Usa busca na web em fontes brasileiras atuais.</p>
            <button className="btn btn-primario mt-5" onClick={() => novo.mutate()}><MessageSquarePlus className="size-4" /> Começar</button>
          </div>
        </div>
      )}
    </div>
  )
}
