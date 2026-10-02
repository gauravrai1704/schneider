import { useEffect, useState } from 'react'
import { useLiveFeed } from '../api'
import { fmt, pumpStatus, tankName } from '../format'
import TankGlass from './TankGlass'
import { Banner, Card, StatusChip } from './ui'

const TANK_LITRES = 1000
const SAFE_MIN = 15
const KEY = 'vtb-resident-building'

function readSaved() {
  try { return localStorage.getItem(KEY) } catch { return null }
}

/** What a resident cares about: is there water, is the pump OK, and why is it
 * (not) running — in plain words, on a phone-sized layout. */
export default function ResidentView() {
  const { tanksById, commandsById, paused } = useLiveFeed()
  const ids = Object.keys(tanksById).sort()
  const [selected, setSelected] = useState(readSaved)
  const id = selected && tanksById[selected] ? selected : ids[0]
  const tank = id ? tanksById[id] : null

  useEffect(() => {
    if (!selected) return
    try { localStorage.setItem(KEY, selected) } catch { /* not critical */ }
  }, [selected])

  const alerts = []
  if (tank) {
    if (tank.level_pct < SAFE_MIN) alerts.push({ tone: 'critical', title: 'Water running low', text: 'Your tank is below the safe level. A refill gets top priority, whatever the grid is doing.' })
    if (tank.sump_level_pct != null && tank.sump_level_pct < 10) alerts.push({ tone: 'warning', title: 'Sump nearly empty', text: 'The pump is stopped to protect the motor until municipal supply refills the sump.' })
    if (tank.level_pct > 92) alerts.push({ tone: 'good', title: 'Tank full', text: 'The pump stopped automatically to prevent overflow.' })
    if (paused) alerts.push({ tone: 'warning', title: 'Grid support in progress', text: 'Pumping is briefly paused to help the local grid. Your water stays above the safe level.' })
  }
  const st = tank ? pumpStatus(tank, commandsById[id], paused) : null

  return (
    <div className="mx-auto flex max-w-lg flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">My building's water</h1>
          <p className="text-sm text-ink-muted">Live from your tank controller.</p>
        </div>
        {ids.length > 0 && (
          <label className="flex items-center gap-2 text-sm text-ink-secondary">
            Building
            <select
              value={id || ''}
              onChange={(e) => setSelected(e.target.value)}
              className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink"
            >
              {ids.map((b) => <option key={b} value={b}>{tankName(b)}</option>)}
            </select>
          </label>
        )}
      </div>

      {!tank ? (
        <Card><p className="py-8 text-center text-sm text-ink-muted">Waiting for your tank's data…</p></Card>
      ) : (
        <>
          <Card>
            <div className="flex items-center gap-6">
              <TankGlass levelPct={tank.level_pct} safeMinPct={SAFE_MIN} size="lg" />
              <div className="flex flex-col gap-2">
                <div>
                  <div className="text-xs text-ink-muted">Overhead tank</div>
                  <div className="text-4xl font-semibold text-ink">{fmt(tank.level_pct)}%</div>
                  <div className="num text-sm text-ink-secondary">≈ {fmt((tank.level_pct / 100) * TANK_LITRES)} litres</div>
                </div>
                <div>
                  <div className="text-xs text-ink-muted">Ground sump</div>
                  <div className="num text-sm text-ink">{tank.sump_level_pct != null ? `${fmt(tank.sump_level_pct)}%` : 'No sensor'}</div>
                </div>
              </div>
            </div>
          </Card>

          <Card title="Pump">
            <div className="flex flex-col items-start gap-2">
              <StatusChip tone={st.tone}>{st.label}</StatusChip>
              <p className="text-sm text-ink-secondary">{st.reason}</p>
            </div>
          </Card>

          <div className="flex flex-col gap-2">
            {alerts.length === 0
              ? <Banner tone="good" title="Everything's normal">No alerts for your building.</Banner>
              : alerts.map((a) => <Banner key={a.title} tone={a.tone} title={a.title}>{a.text}</Banner>)}
          </div>

          <Card title="Green-hour pumping" subtitle="Coming soon: your monthly savings in ₹">
            <p className="text-sm text-ink-secondary">
              Your pump runs when solar power is plentiful and pauses during grid stress — the water is the same,
              the electricity is cleaner and cheaper.
            </p>
          </Card>
        </>
      )}
    </div>
  )
}
