import { useState } from 'react'
import DiscomView from './components/DiscomView'
import ResidentView from './components/ResidentView'
import SimulationView from './components/SimulationView'

const TABS = [
  { id: 'discom', label: 'DISCOM', view: DiscomView },
  { id: 'resident', label: 'Resident', view: ResidentView },
  { id: 'simulation', label: 'Simulation', view: SimulationView },
]

export default function App() {
  const [active, setActive] = useState('discom')
  const ActiveView = TABS.find((t) => t.id === active).view

  return (
    <div className="min-h-screen bg-bg-deep text-text-primary">
      <div className="border-b border-line px-6 py-3 flex items-center justify-between">
        <div className="font-head text-lg tracking-wide text-text-primary">
          Virtual Tank Battery
        </div>
        <nav className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setActive(t.id)}
              className="relative px-4 py-2 font-head text-sm tracking-wide transition-colors"
              style={{
                color: active === t.id ? '#0D1420' : '#7C8CA3',
                background: active === t.id ? '#E8A33D' : 'transparent',
              }}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>
      <main className="p-6 max-w-6xl mx-auto">
        <ActiveView />
      </main>
    </div>
  )
}
