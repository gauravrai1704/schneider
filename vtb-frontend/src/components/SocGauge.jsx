import { useTheme } from '../theme'

/** Feeder State of Charge as a half-circle meter: blue fill on a lighter
 * blue track, with the kWh figure as the hero number underneath. */
export default function SocGauge({ socKwh = 0, socPct = 0 }) {
  const { chart } = useTheme()
  const pct = Math.max(0, Math.min(100, socPct || 0))
  const r = 80
  const len = Math.PI * r
  const arc = `M 20 100 A ${r} ${r} 0 0 1 180 100`

  return (
    <div className="flex flex-col items-center">
      <svg width="200" height="112" viewBox="0 0 200 112" role="img" aria-label={`State of charge ${pct.toFixed(0)} percent`}>
        <path d={arc} fill="none" stroke={chart.waterTrack} strokeWidth="14" strokeLinecap="round" />
        <path
          d={arc} fill="none" stroke={chart.waterFill} strokeWidth="14" strokeLinecap="round"
          strokeDasharray={`${(pct / 100) * len} ${len}`}
          style={{ transition: 'stroke-dasharray 600ms ease' }}
        />
        <text x="100" y="86" textAnchor="middle" fontSize="30" fontWeight="600" fill={chart.ink}>
          {socKwh.toFixed(1)}
        </text>
        <text x="100" y="104" textAnchor="middle" fontSize="12" fill={chart.tick}>kWh</text>
      </svg>
      <div className="mt-1 text-xs text-ink-muted">{pct.toFixed(0)}% of tank capacity empty and fillable</div>
    </div>
  )
}
