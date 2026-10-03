import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getSimulation } from '../api'
import { fmt } from '../format'
import { useTheme } from '../theme'
import { IconBolt, IconDrop, IconSun } from './icons'
import { Banner, Card, ChartTooltip, LegendKey, StatTile, StatusChip } from './ui'

const hhmm = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
const TICKS = [0, 240, 480, 720, 960, 1200, 1440]
const kw = (w) => (w == null ? null : w / 1000)

function DayChart({ data, lines, height = 260 }) {
  const { chart } = useTheme()
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: -4, bottom: 0 }}>
        <CartesianGrid stroke={chart.grid} vertical={false} />
        <XAxis dataKey="t_min" type="number" domain={[0, 1440]} ticks={TICKS} tickFormatter={hhmm}
               tick={{ fill: chart.tick, fontSize: 11 }} stroke={chart.axis} tickLine={false} />
        <YAxis tick={{ fill: chart.tick, fontSize: 11 }} stroke={chart.axis} tickLine={false} axisLine={false}
               tickFormatter={(v) => fmt(v)} width={48} />
        <Tooltip content={<ChartTooltip labelFormatter={hhmm} unit="kW" />} cursor={{ stroke: chart.axis }} />
        {lines.map((l) => (
          <Line key={l.key} type="monotone" dataKey={l.key} name={l.name} stroke={l.color} strokeWidth={2}
                strokeDasharray={l.dash} dot={false} isAnimationActive={false}
                activeDot={{ r: 4, stroke: chart.surface, strokeWidth: 2 }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

const ROWS = [
  ['Pumping powered by solar', 'green_share_pct', '%', 0],
  ['Pumping in evening peak (6–11 pm)', 'evening_peak_pump_kwh', 'kWh', 1],
  ['Pumping outside solar hours', 'pump_kwh_outside_green', 'kWh', 1],
  ['Peak pump load', 'pump_peak_kw', 'kW', 0],
  ['Feeder net peak', 'net_peak_kw', 'kW', 0],
  ['Time any tank below safe level', 'pct_time_below_safe_min', '%', 2],
  ['Tanks full at end of day', 'tank_fill_end_pct', '%', 0],
]

export default function SimulationView() {
  const { chart } = useTheme()
  const [nBuildings, setNBuildings] = useState(300)
  const [cloudyDay, setCloudyDay] = useState(false)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const run = async () => {
    setLoading(true)
    setError(null)
    try {
      setResult(await getSimulation(nBuildings, cloudyDay))
    } catch (e) {
      setError(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { run() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const m = result?.metrics
  const base = m?.baseline, rules = m?.rules, opt = m?.optimal
  const data = (result?.curve || []).map((p) => ({
    t_min: p.t_min,
    baseline: kw(p.baseline_w), vtb: kw(p.optimized_w), optimal: kw(p.optimal_w),
    netBaseline: kw(p.net_baseline_w), netVtb: kw(p.net_optimized_w),
  }))
  const lakhScale = result ? (result.kwh_shifted / result.n_buildings) * 100000 / 1000 : 0
  const safe = rules && rules.pct_time_below_safe_min === 0 && rules.unmet_water_litres === 0

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold text-ink">Neighbourhood scale</h1>
        <p className="text-sm text-ink-muted">
          The same buildings and the same water, scheduled three ways: how pumps run today, the VTB controller,
          and the best possible plan.
        </p>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-6">
          <label className="min-w-[220px] flex-1">
            <div className="mb-2 flex justify-between text-sm">
              <span className="text-ink-secondary">Buildings on the feeder</span>
              <span className="num font-semibold text-ink">{nBuildings}</span>
            </div>
            <input
              type="range" min="20" max="500" step="10" value={nBuildings}
              onChange={(e) => setNBuildings(Number(e.target.value))}
              className="w-full accent-[var(--accent)]"
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input type="checkbox" checked={cloudyDay} onChange={(e) => setCloudyDay(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
            Cloudy day
          </label>
          <button
            onClick={run}
            disabled={loading}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-sm hover:brightness-110 disabled:opacity-60"
          >
            {loading ? `Simulating ${nBuildings} buildings…` : 'Run simulation'}
          </button>
        </div>
      </Card>

      {error && <Banner tone="critical" title="Simulation failed">Is the backend running on port 8000?</Banner>}

      {result && base && rules && (
        <>
          <div className={`grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 ${loading ? 'opacity-60' : ''}`}>
            <StatTile
              label="Pumping powered by solar" icon={<IconSun width={14} height={14} />} accent="text-solar"
              value={`${fmt(base.green_share_pct)}% → ${fmt(rules.green_share_pct)}`} unit="%"
              hint="Today → with VTB"
            />
            <StatTile
              label="Evening-peak pumping" icon={<IconBolt width={14} height={14} />} accent="text-accent"
              value={`−${fmt(result.evening_pumping_cut_pct)}`} unit="%"
              hint={`${fmt(base.evening_peak_pump_kwh, 1)} → ${fmt(rules.evening_peak_pump_kwh, 1)} kWh between 6 and 11 pm`}
            />
            <StatTile
              label="Energy moved into solar hours" icon={<IconSun width={14} height={14} />} accent="text-solar"
              value={fmt(result.kwh_shifted)} unit="kWh/day"
              hint={`≈ ${fmt(lakhScale, 1)} MWh/day for 1 lakh buildings`}
            />
            <StatTile
              label="Feeder net peak" icon={<IconBolt width={14} height={14} />} accent="text-accent"
              value={`${result.peak_reduction_pct > 0 ? '−' : ''}${fmt(Math.abs(result.peak_reduction_pct), 1)}`} unit="%"
              hint={`${fmt(base.net_peak_kw)} → ${fmt(rules.net_peak_kw)} kW · no new peak created`}
            />
          </div>

          <div className="flex flex-wrap items-center gap-2 text-sm text-ink-secondary">
            <IconDrop width={14} height={14} className="text-accent" />
            {safe
              ? <StatusChip tone="good">No tank went below its safe level, no water shortfall</StatusChip>
              : <StatusChip tone="warning">Some tanks dipped below the safe level — see the table</StatusChip>}
          </div>

          <Card
            title="Pump load over the day"
            subtitle={`${result.n_buildings} buildings · 0.75 HP pumps · kW`}
            right={
              <div className="flex flex-wrap gap-3">
                <LegendKey color={chart.baseline} label="Today" dashed />
                <LegendKey color={chart.load} label="VTB controller" />
                {opt && <LegendKey color={chart.optimal} label="Best possible (LP)" dashed />}
              </div>
            }
          >
            <DayChart data={data} lines={[
              { key: 'baseline', name: 'Today', color: chart.baseline, dash: '5 4' },
              { key: 'vtb', name: 'VTB controller', color: chart.load },
              ...(opt ? [{ key: 'optimal', name: 'Best possible (LP)', color: chart.optimal, dash: '2 3' }] : []),
            ]} />
          </Card>

          <Card
            title="Feeder net load — household demand + pumps − local solar"
            subtitle="What the DISCOM sees on the feeder · kW"
            right={
              <div className="flex flex-wrap gap-3">
                <LegendKey color={chart.baseline} label="Today" dashed />
                <LegendKey color={chart.load} label="VTB controller" />
              </div>
            }
          >
            <DayChart data={data} lines={[
              { key: 'netBaseline', name: 'Today', color: chart.baseline, dash: '5 4' },
              { key: 'netVtb', name: 'VTB controller', color: chart.load },
            ]} />
          </Card>

          <Card title="Side by side" subtitle="Same buildings, same water demand, same day">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs text-ink-muted">
                    <th className="py-2 pr-4 font-medium">Metric</th>
                    <th className="py-2 pr-4 text-right font-medium">Today</th>
                    <th className="py-2 pr-4 text-right font-medium">VTB controller</th>
                    <th className="py-2 text-right font-medium">Best possible (LP)</th>
                  </tr>
                </thead>
                <tbody className="num">
                  {ROWS.map(([label, key, unit, digits]) => (
                    <tr key={key} className="border-b border-line last:border-0">
                      <td className="py-2 pr-4 text-ink-secondary">{label}</td>
                      {[base, rules, opt].map((col, i) => (
                        <td key={i} className="py-2 pr-4 text-right text-ink last:pr-0">
                          {col && col[key] != null ? `${fmt(col[key], digits)} ${unit}` : '—'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <details className="card group p-4">
            <summary className="cursor-pointer list-none text-sm font-semibold text-ink">Data & assumptions</summary>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-secondary">
              <li>Solar: {result.inputs.solar}</li>
              <li>Household demand: {result.inputs.load}, peaking at {result.inputs.household_peak_kw} kW per building</li>
              <li>Local solar: {result.inputs.solar_kwp_per_building} kWp per building · pumps: {result.inputs.pump_kw} kW (0.75 HP)</li>
              <li>Water: {result.inputs.water} · municipal supply {result.inputs.supply_windows.join(' and ')}</li>
              <li>Today's behaviour: each pump switches on when its tank falls below 25–45% and runs until full.</li>
              <li>"Best possible" is a day-ahead linear program that knows the whole day in advance — a benchmark, not a live controller.</li>
            </ul>
          </details>
        </>
      )}
    </div>
  )
}
