import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { getForecast, getFeederSoc, postPause, useLiveFeed } from '../api'
import SocGauge from './SocGauge'
import TankGlass from './TankGlass'
import PumpPauseButton from './PumpPauseButton'
import ImpactCounters from './ImpactCounters'

export default function DiscomView() {
  const { connected, tanksById, solar, paused, lastCommands } = useLiveFeed()
  const [forecast, setForecast] = useState([])
  const [soc, setSoc] = useState({ soc_kwh: 0, soc_pct_of_max: 0, tanks_reporting: 0 })
  const [solarHistory, setSolarHistory] = useState([])
  const [kwhShifted, setKwhShifted] = useState(0)

  useEffect(() => {
    const poll = async () => {
      try {
        setForecast(await getForecast())
        setSoc(await getFeederSoc())
      } catch (e) { /* backend not up yet — panels just show last-known values */ }
    }
    poll()
    const t = setInterval(poll, 5000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (!solar) return
    setSolarHistory((prev) => [...prev.slice(-40), { t: new Date(solar.ts).toLocaleTimeString(), w: solar.solar_w }])
  }, [solar])

  useEffect(() => {
    const onCount = lastCommands.filter((c) => c.action === 'ON').length
    if (onCount > 0) setKwhShifted((prev) => prev + (onCount * 40 * 2) / 3600 / 1000 * 1000) // rough live accrual, matches sim's 40W pump assumption
  }, [lastCommands])

  const tanks = Object.values(tanksById)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="font-head text-2xl text-text-primary tracking-wide">Feeder-1 grid console</h1>
        <span className={`font-mono text-xs px-2 py-1 rounded ${connected ? 'text-cyan' : 'text-alert'}`}>
          {connected ? '● live' : '○ reconnecting'}
        </span>
      </div>

      <div className="flex flex-wrap gap-4">
        <div className="panel px-6 py-4 flex items-center justify-center">
          <SocGauge socKwh={soc.soc_kwh} socPct={soc.soc_pct_of_max} />
        </div>
        <div className="flex-1 min-w-[280px]">
          <ImpactCounters
            kwhShifted={soc.soc_kwh > 0 ? kwhShifted : 0}
            peakReductionPct={0}
            tanksReporting={soc.tanks_reporting}
          />
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="panel p-4">
          <div className="panel-label text-xs mb-2">Solar — live vs 60min forecast</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={solarHistory}>
              <CartesianGrid stroke="#263449" strokeDasharray="3 3" />
              <XAxis dataKey="t" tick={{ fill: '#7C8CA3', fontSize: 10 }} />
              <YAxis tick={{ fill: '#7C8CA3', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#141E2E', border: '1px solid #263449' }} />
              <Line type="monotone" dataKey="w" stroke="#E8A33D" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="panel p-4">
          <div className="panel-label text-xs mb-2">Forecast — next 60 minutes</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={forecast.map((f) => ({ ...f, label: `+${f.horizon_min}m` }))}>
              <CartesianGrid stroke="#263449" strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fill: '#7C8CA3', fontSize: 10 }} />
              <YAxis tick={{ fill: '#7C8CA3', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#141E2E', border: '1px solid #263449' }} />
              <Line type="monotone" dataKey="solar_w" name="solar (W)" stroke="#E8A33D" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="feeder_load_w" name="load (W)" stroke="#4FB8C4" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="panel p-4 flex flex-wrap items-center gap-6">
        <div className="flex-1 min-w-[240px]">
          <div className="panel-label text-xs mb-3">Live tank grid</div>
          <div className="flex flex-wrap gap-3">
            {tanks.length === 0 && <span className="text-text-dim text-sm">waiting for telemetry…</span>}
            {tanks.map((t) => (
              <TankGlass key={t.building_id} id={t.building_id} levelPct={t.level_pct} pumpOn={t.pump_on} />
            ))}
          </div>
        </div>
        <PumpPauseButton paused={paused} onToggle={postPause} />
      </div>
    </div>
  )
}
