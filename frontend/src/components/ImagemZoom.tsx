import { ZoomIn } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Imagem } from '../api'

function Visualizador({ img, aoFechar }: { img: Imagem; aoFechar: () => void }) {
  const [escala, setEscala] = useState(1)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const arrasto = useRef<{ x: number; y: number } | null>(null)

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => e.key === 'Escape' && aoFechar()
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [aoFechar])

  return (
    <div className="fixed inset-0 z-[60] bg-black/90 flex flex-col" onClick={aoFechar}>
      <div className="flex items-center justify-between px-5 py-3 text-sm text-suave" onClick={(e) => e.stopPropagation()}>
        <span>{img.rotulo || 'Imagem'}{img.legenda && img.legenda !== img.rotulo ? ` — ${img.legenda}` : ''}</span>
        <span className="flex items-center gap-3">
          <span className="num">{Math.round(escala * 100)}%</span>
          <button className="btn !py-1" onClick={() => { setEscala(1); setPos({ x: 0, y: 0 }) }}>Ajustar</button>
          <button className="btn !py-1" onClick={aoFechar}>Fechar (Esc)</button>
        </span>
      </div>
      <div
        className="flex-1 overflow-hidden grid place-items-center cursor-grab active:cursor-grabbing"
        onClick={(e) => e.stopPropagation()}
        onWheel={(e) => setEscala((s) => Math.min(6, Math.max(0.5, s * (e.deltaY < 0 ? 1.15 : 0.87))))}
        onMouseDown={(e) => { arrasto.current = { x: e.clientX - pos.x, y: e.clientY - pos.y } }}
        onMouseMove={(e) => arrasto.current && setPos({ x: e.clientX - arrasto.current.x, y: e.clientY - arrasto.current.y })}
        onMouseUp={() => { arrasto.current = null }}
        onMouseLeave={() => { arrasto.current = null }}
        onDoubleClick={() => setEscala((s) => (s > 1 ? 1 : 2.5))}
      >
        <img
          src={img.url} alt={img.legenda ?? 'imagem da questão'} draggable={false}
          className="max-h-[85vh] max-w-[92vw] select-none"
          style={{ transform: `translate(${pos.x}px, ${pos.y}px) scale(${escala})`, transition: arrasto.current ? 'none' : 'transform 120ms' }}
        />
      </div>
      <p className="text-center text-xs text-apagado pb-3">Role para ampliar · arraste para mover · duplo clique alterna zoom</p>
    </div>
  )
}

export default function ImagensQuestao({ imagens }: { imagens: Imagem[] }) {
  const [aberta, setAberta] = useState<Imagem | null>(null)
  if (!imagens.length) return null
  return (
    <>
      <div className="flex flex-wrap gap-3 my-4">
        {imagens.map((img) => (
          <button key={img.url} onClick={() => setAberta(img)}
                  className="group relative rounded-xl overflow-hidden border border-borda-forte bg-black hover:border-hema transition">
            <img src={img.url} alt={img.legenda ?? ''} className="h-56 max-w-full object-contain" />
            <span className="absolute bottom-2 right-2 chip bg-tinta/80 opacity-0 group-hover:opacity-100 transition">
              <ZoomIn className="size-3" /> ampliar
            </span>
            {img.rotulo && <span className="absolute top-2 left-2 chip bg-tinta/80">{img.rotulo}</span>}
          </button>
        ))}
      </div>
      {aberta && <Visualizador img={aberta} aoFechar={() => setAberta(null)} />}
    </>
  )
}
