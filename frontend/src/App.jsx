import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import Settings from './pages/Settings'
import Movies from './pages/Movies'

export default function App() {
    return (
        <div className="app-shell">
            <Sidebar />
            <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/movies" element={<Movies mediaType="movie" />} />
                <Route path="/series" element={<Movies mediaType="series" />} />
                <Route path="/jobs" element={<Jobs />} />
                <Route path="/settings" element={<Settings />} />
            </Routes>
        </div>
    )
}
