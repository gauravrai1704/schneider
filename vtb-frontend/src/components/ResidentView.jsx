import { useEffect, useState } from 'react'
import { getDemo, getResident, postDemoLeak, useLiveFeed, usePoll } from '../api'
import { fmt, pumpStatus, tankName } from '../format'
import TankGlass from './TankGlass'
import { Banner, Card, StatusChip } from './ui'

const SAFE_MIN = 15
const KEY = 'vtb-resident-building'

function readSaved() {
  try { return localStorage.getItem(KEY) } catch { return null }
}

function timeLabel(iso) {
  if (!iso) return null
  const d = new Date(iso)
  const sameDay = d.toDateString() === new Date().toDateString()
  const t = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
  return sameDay ? t : `tomorrow ${t}`
}

/** What a resident cares about: is there water, is the pump OK, when will it run next,
 * and what they're saving — in plain words, on a phone-sized layout. */
export default function ResidentView() {
  const { tanksById, commandsById, paused } = useLiveFeed()
  const ids = Object.keys(tanksById).sort()
  const [selected, setSelected] = useState(readSaved)
  const id = selected && tanksById[selected] ? selected : ids[0]
  const tank = id ? tanksById[id] : null
  const { data: info } = usePoll(() => (id ? getResident(id) : Promise.resolve(null)), 4000, [id])
  const [demoTick, setDemoTick] = useState(0)
  const { data: demo } = usePoll(getDemo, 15000, [demoTick])
  const leaking = demo?.leaks?.includes(id)

  useEffect(() => {
    if (!selected) return
    try { localStorage.setItem(KEY, selected) } catch { /* not critical */ }
  }, [selected])

  const toggleLeak = async () => {
    await postDemoLeak(id, !leaking)
    setDemoTick((n) => n + 1)
  }

  const st = tank ? pumpStatus(tank, commandsById[id], paused) : null
  const next = info?.next_pump
  const savings = info?.savings
  const alerts = info?.alerts ?? []

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
                  <div className="num text-sm text-ink-secondary">≈ {fmt(info?.litres ?? tank.level_pct * 10)} litres</div>
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
              {next && next.why !== 'Pumping now' && (
                <p className="text-sm text-ink">
                  <span className="text-ink-muted">Next run: </span>
                  {next.at && <span className="num font-medium">{timeLabel(next.at)} — </span>}
                  {next.why.toLowerCase()}
                </p>
              )}
              {info?.next_supply && (
                <p className="text-xs text-ink-muted">Municipal water next arrives at {timeLabel(info.next_supply)}.</p>
              )}
            </div>
          </Card>

          <div className="flex flex-col gap-2">
            {alerts.length === 0
              ? <Banner tone="good" title="Everything's normal">No alerts for your building.</Banner>
              : alerts.map((a) => <Banner key={a.code} tone={a.tone} title={a.title}>{a.text}</Banner>)}
          </div>

          <Card
            title="Your savings"
            subtitle={info?.tariff
              ? `Solar hours (${info.tariff.solar_hours}) are ${info.tariff.solar_discount_pct}% cheaper; ${info.tariff.peak_hours} costs ${info.tariff.peak_surcharge_pct}% more`
              : 'Time-of-day tariff'}
          >
            {savings?.monthly_saving_inr != null ? (
              <div className="flex flex-col gap-1">
                <div className="text-3xl font-semibold text-ink">
                  ₹{fmt(savings.monthly_saving_inr)}<span className="ml-1 text-sm font-normal text-ink-muted">/ month</span>
                </div>
                <p className="text-sm text-ink-secondary">
                  {fmt(savings.today_green_share_pct)}% of today's pumping ran in cheap solar hours. Estimated for a real
                  0.75 HP pump moving your building's water ({fmt(savings.real_pump_kwh_per_day, 2)} kWh/day), compared with
                  paying the normal rate.
                </p>
              </div>
            ) : (
              <p className="text-sm text-ink-secondary">Your pump hasn't run yet today — savings appear after the first green-hour fill.</p>
            )}
          </Card>

          {demo?.mock_running && (
            <button
              onClick={toggleLeak}
              className="self-start rounded-lg border border-line px-3 py-1.5 text-xs text-ink-secondary hover:bg-raised"
              title="Demo: make this tank drain like it has a leak"
            >
              {leaking ? 'Demo: fix the leak' : 'Demo: simulate a leak'}
            </button>
          )}
          {leaking && !alerts.some((a) => a.code === 'leak') && (
            <p className="text-xs text-ink-muted">
              Leak detection needs about a minute of data with the pump idle (tip: press Pause all pumps on the grid operator view).
            </p>
          )}
        </>
      )}
    </div>
  )
}
