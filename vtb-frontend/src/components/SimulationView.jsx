import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getSimulation } from '../api'
import { fmt } from '../format'
import { useTheme } from '../theme'
import { Banner, Card, ChartTooltip, LegendKey, StatTile } from './ui'

const hhmm = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`

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

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold text-ink">Neighbourhood scale</h1>
        <p className="text-sm text-ink-muted">What happens to the feeder when hundreds of buildings join the virtual battery.</p>
      </div>

      <Banner tone="warning" title="Preview">
        The simulator is being recalibrated — use these numbers to explore, not to quote.
      </Banner>

      <Card>
        <div className="flex flex-wrap items-center gap-6">
          <label className="min-w-[220px] flex-1">
            <div className="mb-2 flex justify-between text-sm">
              <span className="text-ink-secondary">Buildings</span>
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
            {loading ? 'Running…' : 'Run simulation'}
          </button>
        </div>
      </Card>

      {error && <Banner tone="critical" title="Simulation failed">Is the backend running on port 8000?</Banner>}

      {result && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <StatTile label="Peak load reduction" value={fmt(result.peak_reduction_pct)} unit="%" />
            <StatTile label="Pumping energy shifted (24 h)" value={fmt(result.kwh_shifted, 1)} unit="kWh" />
          </div>

          <Card
            title="Pump load over a day"
            subtitle={`${result.n_buildings} buildings${cloudyDay ? ' · cloudy day' : ''}`}
            right={<div className="flex gap-3"><LegendKey color={chart.baseline} label="Uncoordinated" dashed /><LegendKey color={chart.load} label="VTB-scheduled" /></div>}
          >
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={result.curve} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <CartesianGrid stroke={chart.grid} vertical={false} />
                <XAxis dataKey="t_min" type="number" domain={[0, 1440]} ticks={[0, 240, 480, 720, 960, 1200, 1440]}
                       tickFormatter={hhmm} tick={{ fill: chart.tick, fontSize: 11 }} stroke={chart.axis} tickLine={false} />
                <YAxis tick={{ fill: chart.tick, fontSize: 11 }} stroke={chart.axis} tickLine={false} axisLine={false}
                       tickFormatter={(v) => fmt(v)} width={56} />
                <Tooltip content={<ChartTooltip labelFormatter={hhmm} />} cursor={{ stroke: chart.axis }} />
                <Line type="monotone" dataKey="baseline_w" name="Uncoordinated" stroke={chart.baseline} strokeWidth={2}
                      strokeDasharray="5 4" dot={false} activeDot={{ r: 4, stroke: chart.surface, strokeWidth: 2 }} />
                <Line type="monotone" dataKey="optimized_w" name="VTB-scheduled" stroke={chart.load} strokeWidth={2}
                      dot={false} activeDot={{ r: 4, stroke: chart.surface, strokeWidth: 2 }} />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </>
      )}
    </div>
  )
}
