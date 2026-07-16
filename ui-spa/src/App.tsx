import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import MissionBuilder from './pages/MissionBuilder'
import Logs from './pages/Logs'
import Config from './pages/Config'

const NAV = [
  { to: '/',        label: '대시보드' },
  { to: '/mission', label: '미션 빌더' },
  { to: '/logs',    label: 'MQTT 로그' },
  { to: '/config',  label: 'Config' },
]

export default function App() {
  return (
    <div className="flex flex-col h-screen text-[#f4f7fb]">
      {/* 상단 네비게이션 */}
      <nav className="flex items-center gap-1 px-4 py-3 border-b border-white/10 bg-[#10131a]/90 backdrop-blur-md shadow-[0_8px_30px_rgba(0,0,0,0.18)]">
        <span className="font-extrabold tracking-tight text-[#8f84ff] mr-4 text-base">Fleet Mission Hub</span>
        {NAV.map(n => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === '/'}
            className={({ isActive }) =>
              `px-3 py-1.5 rounded-lg text-sm transition-colors border ` +
              (isActive
                ? 'bg-[#7c6ff7] text-white font-semibold border-[#7c6ff7] shadow-[0_8px_20px_rgba(124,111,247,0.28)]'
                : 'text-[#b3b8c8] border-transparent hover:text-white hover:bg-white/5 hover:border-white/10')
            }
          >
            {n.label}
          </NavLink>
        ))}
      </nav>

      {/* 본문 */}
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/"        element={<Dashboard />} />
          <Route path="/mission" element={<MissionBuilder />} />
          <Route path="/logs"    element={<Logs />} />
          <Route path="/config"  element={<Config />} />
        </Routes>
      </main>
    </div>
  )
}
