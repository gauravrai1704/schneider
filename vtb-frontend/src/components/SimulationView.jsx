import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { getSimulation } from '../api'

export default function SimulationView() {
  const [nBuildings, setNBuildings] = useState(300)
  const [cloudyDay, setCloudyDay] = useState(false)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = async () => {
    setLoading(true)
    try {
      setResult(await getSimulation(nBuildings, cloudyDay))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { run() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col gap-4">
      <h1 className="font-head text-2xl text-text-primary tracking-wide">Neighbourhood scale</h1>

      <div className="panel p-4 flex flex-wrap items-center gap-6">
        <div className="flex-1 min-w-[220px]">
          <div className="panel-label text-xs mb-2">Buildings: {nBuildings}</div>
          <input
            type="range" min="20" max="500" step="10" value={nBuildings}
            onChange={(e) => setNBuildings(Number(e.target.value))}
            className="w-full accent-amber"
          />
        </div>
        <label className="flex items-center gap-2 font-mono text-sm text-text-primary">
          <input type="checkbox" checked={cloudyDay} onChange={(e) => setCloudyDay(e.target.checked)} className="accent-amber" />
          Cloudy day
        </label>
        <button
          onClick={run}
          className="panel-label text-sm px-4 py-2 border border-amber text-amber hover:bg-amber hover:text-bg-deep transition-colors"
        >
          {loading ? 'running…' : 'run simulation'}
        </button>
      </div>

      {result && (
        <>
          <div className="flex gap-3 flex-wrap">
            <div className="panel px-4 py-3 flex-1 min-w-[160px]">
              <div className="panel-label text-xs mb-1">Peak load reduction</div>
              <div className="font-mono text-xl text-text-primary">{result.peak_reduction_pct.toFixed(0)}%</div>
            </div>
            <div className="panel px-4 py-3 flex-1 min-w-[160px]">
              <div className="panel-label text-xs mb-1">kWh shifted (24h)</div>
              <div className="font-mono text-xl text-text-primary">{result.kwh_shifted.toFixed(1)} kWh</div>
            </div>
          </div>

          <div className="panel p-4">
            <div className="panel-label text-xs mb-2">Feeder load — uncoordinated vs VTB-scheduled</div>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={result.curve.filter((_, i) => i % 3 === 0)}>
                <CartesianGrid stroke="#263449" strokeDasharray="3 3" />
                <XAxis dataKey="t_min" tick={{ fill: '#7C8CA3', fontSize: 10 }}
                       tickFormatter={(m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:00`} />
                <YAxis tick={{ fill: '#7C8CA3', fontSize: 10 }} />
                <Tooltip contentStyle={{ background: '#141E2E', border: '1px solid #263449' }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="baseline_w" name="uncoordinated" stroke="#7C8CA3" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="optimized_w" name="VTB-scheduled" stroke="#E8A33D" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  )
}
