import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Ajustes from './pages/Ajustes'
import Blocos from './pages/Blocos'
import Busca from './pages/Busca'
import Coach from './pages/Coach'
import Curadoria from './pages/Curadoria'
import Flashcards from './pages/Flashcards'
import Painel from './pages/Painel'
import QuestaoAvulsa from './pages/QuestaoAvulsa'
import Resolver from './pages/Resolver'
import Simulado from './pages/Simulado'
import TemaDetalhe from './pages/TemaDetalhe'
import Temas from './pages/Temas'
import TutorLivre from './pages/TutorLivre'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Painel />} />
        <Route path="temas" element={<Temas />} />
        <Route path="temas/:id" element={<TemaDetalhe />} />
        <Route path="blocos" element={<Blocos />} />
        <Route path="blocos/:id" element={<Resolver />} />
        <Route path="questao/:id" element={<QuestaoAvulsa />} />
        <Route path="flashcards" element={<Flashcards />} />
        <Route path="simulado" element={<Simulado />} />
        <Route path="coach" element={<Coach />} />
        <Route path="busca" element={<Busca />} />
        <Route path="tutor" element={<TutorLivre />} />
        <Route path="curadoria" element={<Curadoria />} />
        <Route path="ajustes" element={<Ajustes />} />
      </Route>
    </Routes>
  )
}
