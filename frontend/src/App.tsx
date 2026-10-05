import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Agenda from './pages/Agenda'
import Ajustes from './pages/Ajustes'
import Biblioteca from './pages/Biblioteca'
import BibliotecaDoc from './pages/BibliotecaDoc'
import Blocos from './pages/Blocos'
import Busca from './pages/Busca'
import Curadoria from './pages/Curadoria'
import Flashcards from './pages/Flashcards'
import Painel from './pages/Painel'
import Preceptor from './pages/Preceptor'
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
        <Route path="agenda" element={<Agenda />} />
        <Route path="preceptor" element={<Preceptor />} />
        <Route path="coach" element={<Navigate to="/preceptor" replace />} />
        <Route path="biblioteca" element={<Biblioteca />} />
        <Route path="biblioteca/:id" element={<BibliotecaDoc />} />
        <Route path="busca" element={<Busca />} />
        <Route path="tutor" element={<TutorLivre />} />
        <Route path="curadoria" element={<Curadoria />} />
        <Route path="ajustes" element={<Ajustes />} />
      </Route>
    </Routes>
  )
}
