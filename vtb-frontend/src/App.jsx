import { useEffect, useState } from 'react'
import { useLiveFeed } from './api'
import { useTheme } from './theme'
import DiscomView from './components/DiscomView'
import ResidentView from './components/ResidentView'
import SimulationView from './components/SimulationView'
import { IconDrop, IconMonitor, IconMoon, IconSun } from './components/icons'
import { Segmented } from './components/ui'

const TABS = [
  { id: 'discom', label: 'Grid operator', view: DiscomView },
  { id: 'resident', label: 'Resident', view: ResidentView },
  { id: 'simulation', label: 'Simulation', view: SimulationView },
]

function ConnectionPill() {
  const { connected } = useLiveFeed()
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
        connected ? 'bg-good-soft text-good-text' : 'bg-warning-soft text-warning-text'
      }`}
      role="status"
    >
      <span className={`h-2 w-2 rounded-full ${connected ? 'bg-good animate-pulse' : 'bg-warning'}`} />
      {connected ? 'Live' : 'Reconnecting…'}
    </span>
  )
}

export default function App() {
  const fromHash = () => (TABS.some((t) => t.id === location.hash.slice(1)) ? location.hash.slice(1) : 'discom')
  const [active, setActiveState] = useState(fromHash)
  const setActive = (id) => { history.replaceState(null, '', `#${id}`); setActiveState(id) }
  useEffect(() => {
    const onHash = () => setActiveState(fromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const { choice, setChoice } = useTheme()
  const ActiveView = TABS.find((t) => t.id === active).view

  return (
    <div className="min-h-screen bg-page text-ink">
      <header className="sticky top-0 z-10 border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-white">
              <IconDrop width={18} height={18} />
            </span>
            <div className="leading-tight">
              <div className="text-sm font-semibold text-ink">Virtual Tank Battery</div>
              <div className="hidden text-xs text-ink-muted sm:block">Rooftop tanks as grid storage</div>
            </div>
          </div>

          <nav className="order-3 flex w-full gap-1 overflow-x-auto sm:order-none sm:ml-6 sm:w-auto" aria-label="Views">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setActive(t.id)}
                aria-current={active === t.id ? 'page' : undefined}
                className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition-colors ${
                  active === t.id ? 'bg-accent-soft font-semibold text-accent' : 'text-ink-muted hover:bg-raised hover:text-ink'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <div className="ml-auto flex shrink-0 items-center gap-2">
            <ConnectionPill />
            <Segmented
              label="Colour theme"
              value={choice}
              onChange={setChoice}
              options={[
                { value: 'system', icon: <IconMonitor width={14} height={14} />, title: 'Match system' },
                { value: 'light', icon: <IconSun width={14} height={14} />, title: 'Light' },
                { value: 'dark', icon: <IconMoon width={14} height={14} />, title: 'Dark' },
              ]}
            />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        <ActiveView />
      </main>
    </div>
  )
}
