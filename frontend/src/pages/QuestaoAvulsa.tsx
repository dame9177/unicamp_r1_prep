import { ArrowLeft } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import QuestaoView from '../components/QuestaoView'
import Tutor from '../components/Tutor'

export default function QuestaoAvulsa() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const [tutor, setTutor] = useState(false)
  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-8 py-8">
          <button className="text-sm text-suave hover:text-texto inline-flex items-center gap-1.5 mb-5" onClick={() => nav(-1)}>
            <ArrowLeft className="size-4" /> Voltar
          </button>
          <QuestaoView key={id} questaoId={id} tutorAberto={tutor} alternarTutor={() => setTutor((t) => !t)} />
        </div>
      </div>
      {tutor && <Tutor questaoId={id} aoFechar={() => setTutor(false)} />}
    </div>
  )
}
