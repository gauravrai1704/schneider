import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useState } from 'react'
import { getDemo, getFeederSoc, getForecast, getImpact, getSources, postDemoCloud, postPause, useLiveFeed, usePoll } from '../api'
import { clockLabel, fmt, fmtDuration, loadSourceLabel, pumpStatus, solarSourceLabel, tankName } from '../format'
import { useTheme } from '../theme'
import { IconBolt, IconDrop, IconSun } from './icons'
import DataSources from './DataSources'
import PumpPauseButton from './PumpPauseButton'
import SocGauge from './SocGauge'
import TankGlass from './TankGlass'
import { Banner, Card, ChartTooltip, LegendKey, StatTile, StatusChip } from './ui'

const FORECAST_HORIZONS = '0,30,60,90,120,150,180,210,240,270,300,330,360'
const SAFE_MIN = 15

export default function DiscomView() {
  const { chart } = useTheme()
  const { tanksById, commandsById, solar, solarHistory, paused, setPaused } = useLiveFeed()
  const { data: soc } = usePoll(getFeederSoc, 5000)
  const { data: forecast } = usePoll(() => getForecast(FORECAST_HORIZONS), 30000)
  const { data: sources } = usePoll(getSources, 30000)
  const { data: impact } = usePoll(getImpact, 10000)
  const [demoTick, setDemoTick] = useState(0)
  const { data: demo } = usePoll(getDemo, 15000, [demoTick])
  const toggleCloud = async () => {
    await postDemoCloud(!demo?.cloud)
    setDemoTick((n) => n + 1)
  }

  const tanks = Object.values(tanksById).sort((a, b) => a.building_id.localeCompare(b.building_id))
  const pumping = tanks.filter((t) => pumpStatus(t, commandsById[t.building_id], paused).label === 'Pumping').length
  const low = tanks.filter((t) => t.level_pct < SAFE_MIN).length
  const now = forecast?.[0]
  const clearness = sources?.panel_clearness
  // Follow the server's clock (it may be running a demo clock) for forecast times
  const skew = sources?.server_time ? Date.parse(sources.server_time) - Date.now() : 0
  const t0 = Date.now() + skew
  const forecastData = (forecast || []).map((f) => ({ ...f, ts: t0 + f.horizon_min * 60000 }))

  const togglePause = async (active) => {
    await postPause(active)
    setPaused(active)
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-ink">Feeder 1 · Delhi</h1>
          <p className="text-sm text-ink-muted">Pumping load the grid can shift right now, and what's coming in the next 6 hours.</p>
        </div>
      </div>

      {paused && (
        <Banner tone="critical" title="Demand response active — all pumps paused">
          Water supply stays protected by each building's local safety rules. Resume when the grid recovers.
        </Banner>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Virtual battery — State of Charge" subtitle="Pumping energy that can be shifted on this feeder">
          <div className="flex flex-col items-center gap-4">
            <SocGauge socKwh={soc?.soc_kwh ?? 0} socPct={soc?.soc_pct_of_max ?? 0} />
            <PumpPauseButton paused={paused} onToggle={togglePause} />
            <p className="text-center text-xs text-ink-muted">
              {soc?.pumps_running
                ? `Instantly sheds ${fmt(soc.sheddable_w)} W of pump load. `
                : 'No pumps running right now. '}
              {soc?.pause_minutes_available != null && (soc.pause_minutes_available > 0
                ? `Every building keeps safe water for at least ${fmtDuration(soc.pause_minutes_available)}.`
                : 'A building below its safe level keeps refilling even during a pause.')}
            </p>
          </div>
        </Card>

        <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 lg:col-span-2">
          <StatTile
            label="Solar output now" icon={<IconSun width={14} height={14} />} accent="text-solar"
            value={fmt(solar?.solar_w)} unit={solar ? 'W' : undefined}
            hint={clearness == null ? (solar?.solar_w > 0 ? 'Low sun — dawn or dusk' : 'Sun is down or no panel reading') : clearness >= 0.95 ? 'Clear sky — full output' : `${fmt(clearness * 100)}% of clear-sky output (clouds)`}
          />
          <StatTile
            label="Feeder load now" icon={<IconBolt width={14} height={14} />} accent="text-accent"
            value={fmt(now?.feeder_load_w)} unit="W"
            hint={now?.discom_load_mw != null ? `Real BYPL demand: ${fmt(now.discom_load_mw)} MW` : 'Waiting for forecast…'}
          />
          <StatTile
            label="Pumps running" icon={<IconDrop width={14} height={14} />} accent="text-accent"
            value={`${pumping} / ${tanks.length}`}
            hint="Starts are staggered to protect feeder voltage"
          />
          <div className="card flex min-w-0 flex-col gap-1 p-4">
            <div className="text-xs text-ink-muted">Water safety</div>
            <div className="text-2xl font-semibold text-ink">{tanks.length === 0 ? '—' : low === 0 ? 'All safe' : `${low} low`}</div>
            <div>
              {tanks.length === 0 ? <StatusChip tone="neutral">Waiting for tanks</StatusChip> : low === 0
                ? <StatusChip tone="good">Every tank above {SAFE_MIN}%</StatusChip>
                : <StatusChip tone="critical">{low} tank{low > 1 ? 's' : ''} below {SAFE_MIN}%</StatusChip>}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Next 6 hours — solar supply vs feeder load"
          subtitle={now ? `ML forecast · solar from ${solarSourceLabel(now.solar_source)} · load from ${loadSourceLabel(now.load_source)}` : 'Loading forecast…'}
          right={<div className="flex gap-3"><LegendKey color={chart.solar} label="Solar" /><LegendKey color={chart.load} label="Load" /></div>}
        >
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={forecastData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
              <CartesianGrid stroke={chart.grid} vertical={false} />
              <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} scale="time"
                     tickFormatter={clockLabel} tick={{ fill: chart.tick, fontSize: 11 }} stroke={chart.axis} tickLine={false} />
              <YAxis tick={{ fill: chart.tick, fontSize: 11 }} stroke={chart.axis} tickLine={false} axisLine={false}
                     tickFormatter={(v) => fmt(v)} width={52} />
              <Tooltip content={<ChartTooltip labelFormatter={clockLabel} />} cursor={{ stroke: chart.axis }} />
              <Area type="monotone" dataKey="solar_w" name="Solar" stroke={chart.solar} strokeWidth={2}
                    fill={chart.solar} fillOpacity={0.1} dot={false} activeDot={{ r: 4, stroke: chart.surface, strokeWidth: 2 }} />
              <Line type="monotone" dataKey="feeder_load_w" name="Load" stroke={chart.load} strokeWidth={2}
                    dot={false} activeDot={{ r: 4, stroke: chart.surface, strokeWidth: 2 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Solar panel — live"
          subtitle="Last few minutes, one reading every 2 s"
          right={demo?.mock_running && (
            <button
              onClick={toggleCloud}
              className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
                demo.cloud ? 'border-solar bg-solar-soft text-ink' : 'border-line text-ink-secondary hover:bg-raised'
              }`}
              title="Demo: simulate covering the panel"
            >
              {demo.cloud ? 'Clear the cloud' : 'Simulate cloud'}
            </button>
          )}
        >
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={solarHistory} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
              <CartesianGrid stroke={chart.grid} vertical={false} />
              <XAxis dataKey="ts" type="number" domain={['dataMin', 'dataMax']} scale="time"
                     tickFormatter={(ms) => new Date(ms).toLocaleTimeString('en-IN', { hour12: false })}
                     tick={{ fill: chart.tick, fontSize: 11 }} stroke={chart.axis} tickLine={false} minTickGap={40} />
              <YAxis tick={{ fill: chart.tick, fontSize: 11 }} stroke={chart.axis} tickLine={false} axisLine={false} width={44} />
              <Tooltip content={<ChartTooltip labelFormatter={(ms) => new Date(ms).toLocaleTimeString('en-IN')} />} cursor={{ stroke: chart.axis }} />
              <Area type="monotone" dataKey="w" name="Solar" stroke={chart.solar} strokeWidth={2} fill={chart.solar}
                    fillOpacity={0.1} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card
        title="Buildings on this feeder"
        subtitle="Overhead tank level (dashed line = safe minimum) · bar underneath = ground sump"
      >
        {tanks.length === 0 ? (
          <p className="py-6 text-center text-sm text-ink-muted">Waiting for tank telemetry…</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {tanks.map((t) => {
              const st = pumpStatus(t, commandsById[t.building_id], paused)
              return (
                <div key={t.building_id} className="flex gap-3 rounded-xl border border-line bg-raised p-3">
                  <div className="w-11 shrink-0">
                    <TankGlass levelPct={t.level_pct} sumpPct={t.sump_level_pct} safeMinPct={SAFE_MIN} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium text-ink">{tankName(t.building_id)}</span>
                      <span className="num text-sm font-semibold text-ink">{fmt(t.level_pct)}%</span>
                    </div>
                    <div className="num text-xs text-ink-muted">
                      Sump {t.sump_level_pct != null ? `${fmt(t.sump_level_pct)}%` : '—'}
                    </div>
                    <div className="mt-2"><StatusChip tone={st.tone}>{st.label}</StatusChip></div>
                    <p className="mt-1 line-clamp-2 text-xs text-ink-secondary" title={st.reason}>{st.reason}</p>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Card>

      <Card title="Today on this feeder" subtitle="Since midnight · model scale, rupees for a real 0.75 HP pump">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <TodayStat label="Pumping on solar" value={impact?.green_share_pct != null ? `${fmt(impact.green_share_pct)}%` : '—'}
                     hint={impact ? `${fmt(impact.wh_pumped, 1)} Wh pumped` : ''} />
          <TodayStat label="Pumping in evening peak" value={impact ? `${fmt(impact.wh_evening_peak, 1)} Wh` : '—'}
                     hint={impact?.tariff ? `${impact.tariff.peak_hours} costs +${impact.tariff.peak_surcharge_pct}%` : ''} />
          <TodayStat label="Saved by time-of-day rates" value={impact ? `₹${fmt(impact.tod_saving_inr, 2)}` : '—'}
                     hint={impact?.tariff ? `Solar hours ${impact.tariff.solar_hours} are ${impact.tariff.solar_discount_pct}% cheaper` : ''} />
          <TodayStat label="Pump Pause events" value={impact ? fmt(impact.pause_events) : '—'}
                     hint={impact?.pause_events ? `Up to ${fmt(impact.max_shed_w)} W shed · ${fmt(impact.pause_minutes, 1)} min paused` : 'None today'} />
        </div>
      </Card>

      <DataSources sources={sources} />
    </div>
  )
}

function TodayStat({ label, value, hint }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-ink-muted">{label}</div>
      <div className="num text-lg font-semibold text-ink">{value}</div>
      {hint && <div className="truncate text-xs text-ink-muted" title={hint}>{hint}</div>}
    </div>
  )
}
