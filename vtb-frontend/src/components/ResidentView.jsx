import { useLiveFeed } from '../api'
import TankGlass from './TankGlass'

/** Residents don't need the grid-operator complexity — just their own tank,
 * plain-language alerts, and what they're getting out of it. */
export default function ResidentView() {
  const { tanksById, connected } = useLiveFeed()
  const tanks = Object.values(tanksById)
  const myTank = tanks[0] // in a real deployment this comes from the logged-in resident's building id

  const alerts = []
  if (myTank && myTank.level_pct < 15) alerts.push({ tone: 'alert', text: 'Tank running low — pump will prioritize a refill soon.' })
  if (myTank && myTank.level_pct > 92) alerts.push({ tone: 'ok', text: 'Tank is nearly full — pump has paused to prevent overflow.' })
  if (myTank && myTank.pump_on) alerts.push({ tone: 'amber', text: 'Pump is running now, timed to solar surplus.' })

  return (
    <div className="flex flex-col gap-4 max-w-md">
      <h1 className="font-head text-2xl text-text-primary tracking-wide">Your tank</h1>
      <span className={`font-mono text-xs ${connected ? 'text-cyan' : 'text-alert'}`}>
        {connected ? '● connected' : '○ reconnecting'}
      </span>

      <div className="panel p-6 flex items-center gap-6">
        {myTank ? (
          <TankGlass id={myTank.building_id} levelPct={myTank.level_pct} pumpOn={myTank.pump_on} />
        ) : (
          <span className="text-text-dim text-sm">waiting for your tank's data…</span>
        )}
        <div>
          <div className="panel-label text-xs">Current level</div>
          <div className="font-mono text-3xl text-text-primary">
            {myTank ? `${myTank.level_pct.toFixed(0)}%` : '—'}
          </div>
        </div>
      </div>

      <div className="panel p-4">
        <div className="panel-label text-xs mb-2">Alerts</div>
        {alerts.length === 0 && <div className="text-text-dim text-sm">Everything's normal — no alerts.</div>}
        {alerts.map((a, i) => (
          <div key={i} className="text-sm py-1" style={{ color: a.tone === 'alert' ? '#E15252' : a.tone === 'amber' ? '#E8A33D' : '#4FB8C4' }}>
            {a.text}
          </div>
        ))}
      </div>

      <div className="panel p-4">
        <div className="panel-label text-xs mb-1">Green-hour savings</div>
        <div className="text-sm text-text-dim">
          Your pump runs during solar surplus whenever it's safe to, cutting the grid power your building draws for water.
        </div>
      </div>
    </div>
  )
}
