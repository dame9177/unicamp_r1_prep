import clsx from 'clsx'
import { Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Confianca, StatusTema, Veredito } from '../api'

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={clsx('md', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ a: (p) => <a {...p} target="_blank" rel="noreferrer" /> }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}

const COR_VEREDITO: Record<Veredito, string> = {
  correto: 'text-certo border-certo/40 bg-certo/10',
  parcial: 'text-parcial border-parcial/40 bg-parcial/10',
  incorreto: 'text-errado border-errado/40 bg-errado/10',
  pendente: 'text-suave border-borda-forte',
  erro: 'text-errado border-errado/40',
}
const ROTULO_VEREDITO: Record<Veredito, string> = {
  correto: 'Correto',
  parcial: 'Parcial',
  incorreto: 'Incorreto',
  pendente: 'Corrigindo…',
  erro: 'Falha na correção',
}

export function VereditoBadge({ v, grande }: { v: Veredito; grande?: boolean }) {
  return (
    <span className={clsx('chip', COR_VEREDITO[v], grande && '!text-sm !px-3 !py-1')}>
      {v === 'pendente' && <Loader2 className="size-3 animate-spin" />}
      {ROTULO_VEREDITO[v]}
    </span>
  )
}

export const ROTULO_CONFIANCA: Record<Confianca, string> = { certeza: 'Certeza', duvida: 'Dúvida', chute: 'Chute' }

const COR_STATUS: Record<StatusTema, string> = {
  nao_iniciado: 'text-apagado border-borda',
  em_progresso: 'text-hema border-hema/40 bg-hema/10',
  dominado: 'text-eosina border-eosina/50 bg-eosina/10',
}
const ROTULO_STATUS: Record<StatusTema, string> = {
  nao_iniciado: 'Não iniciado',
  em_progresso: 'Em progresso',
  dominado: 'Dominado',
}

export function StatusChip({ s, revisar, manual }: { s: StatusTema; revisar?: boolean; manual?: boolean }) {
  return (
    <span className="inline-flex gap-1.5">
      <span className={clsx('chip', COR_STATUS[s])}>
        {ROTULO_STATUS[s]}
        {manual && <span title="marcado manualmente">·✋</span>}
      </span>
      {revisar && <span className="chip text-parcial border-parcial/40">Revisar</span>}
    </span>
  )
}

export function Anel({ valor, tamanho = 64, espessura = 6, cor = 'var(--color-hema)', children }: {
  valor: number | null
  tamanho?: number
  espessura?: number
  cor?: string
  children?: ReactNode
}) {
  const r = (tamanho - espessura) / 2
  const c = 2 * Math.PI * r
  const v = Math.max(0, Math.min(1, valor ?? 0))
  return (
    <div className="relative inline-grid place-items-center" style={{ width: tamanho, height: tamanho }}>
      <svg width={tamanho} height={tamanho} className="-rotate-90">
        <circle cx={tamanho / 2} cy={tamanho / 2} r={r} stroke="var(--color-borda)" strokeWidth={espessura} fill="none" />
        {valor !== null && (
          <circle
            cx={tamanho / 2} cy={tamanho / 2} r={r} stroke={cor} strokeWidth={espessura} fill="none"
            strokeDasharray={c} strokeDashoffset={c * (1 - v)} strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 600ms ease' }}
          />
        )}
      </svg>
      <div className="absolute inset-0 grid place-items-center">{children}</div>
    </div>
  )
}

export function Barra({ valor, cor = 'bg-hema', className }: { valor: number | null; cor?: string; className?: string }) {
  return (
    <div className={clsx('h-1.5 rounded-full bg-borda overflow-hidden', className)}>
      <div className={clsx('h-full rounded-full transition-all duration-500', cor)}
           style={{ width: `${Math.max(0, Math.min(1, valor ?? 0)) * 100}%` }} />
    </div>
  )
}

export function Carregando({ texto = 'Carregando…' }: { texto?: string }) {
  return (
    <div className="flex items-center gap-2 text-suave text-sm py-10 justify-center">
      <Loader2 className="size-4 animate-spin" /> {texto}
    </div>
  )
}

export function Vazio({ titulo, children }: { titulo: string; children?: ReactNode }) {
  return (
    <div className="cartao p-10 text-center">
      <p className="titulo text-lg">{titulo}</p>
      {children && <div className="text-suave text-sm mt-2">{children}</div>}
    </div>
  )
}

export function Cabecalho({ titulo, sub, acoes }: { titulo: ReactNode; sub?: ReactNode; acoes?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div>
        <h1 className="titulo text-3xl font-medium">{titulo}</h1>
        {sub && <p className="text-suave text-sm mt-1">{sub}</p>}
      </div>
      {acoes && <div className="flex flex-wrap gap-2">{acoes}</div>}
    </header>
  )
}

export function ErroCaixa({ erro }: { erro: unknown }) {
  if (!erro) return null
  return (
    <div className="rounded-xl border border-errado/40 bg-errado/10 text-errado text-sm px-4 py-3">
      {erro instanceof Error ? erro.message : String(erro)}
    </div>
  )
}

export function Modal({ aberto, aoFechar, titulo, children, largura = 'max-w-2xl' }: {
  aberto: boolean
  aoFechar: () => void
  titulo: ReactNode
  children: ReactNode
  largura?: string
}) {
  if (!aberto) return null
  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm grid place-items-center p-4" onClick={aoFechar}>
      <div className={clsx('cartao w-full max-h-[90vh] overflow-y-auto p-6 entrar', largura)}
           onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="flex items-start justify-between gap-4 mb-4">
          <h2 className="titulo text-xl">{titulo}</h2>
          <button className="btn btn-fantasma !px-2 !py-1" onClick={aoFechar} aria-label="Fechar">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}
