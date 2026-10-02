import { useTheme } from '../theme'

/** Overhead tank as a sight-glass: water fill, dashed safe-minimum line,
 * and a small sump gauge underneath. Low water switches to the critical
 * colour — always paired with a text label by the caller. */
export default function TankGlass({ levelPct = 0, sumpPct = null, safeMinPct = 15, size = 'md' }) {
  const { chart } = useTheme()
  const level = Math.max(0, Math.min(100, levelPct))
  const isLow = level < safeMinPct
  const scale = size === 'lg' ? 1.8 : 1
  const w = 44 * scale, h = 84 * scale
  const inner = h - 8
  const fillH = (level / 100) * inner
  const minY = h - 4 - (safeMinPct / 100) * inner

  return (
    <div className="flex flex-col items-center gap-1.5">
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Tank ${level.toFixed(0)} percent full`}>
        <rect x="1" y="1" width={w - 2} height={h - 2} rx={6 * scale} fill={chart.waterTrack} opacity="0.55" stroke={chart.axis} />
        <rect
          x="4" y={h - 4 - fillH} width={w - 8} height={fillH} rx={4 * scale}
          fill={isLow ? chart.low : chart.waterFill}
          style={{ transition: 'y 500ms ease, height 500ms ease' }}
        />
        <line x1="2" x2={w - 2} y1={minY} y2={minY} stroke={chart.low} strokeWidth="1.5" strokeDasharray="3 3" />
      </svg>
      {sumpPct !== null && sumpPct !== undefined && (
        <div className="w-full" title={`Sump ${sumpPct.toFixed(0)}%`}>
          <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: chart.waterTrack }}>
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.max(0, Math.min(100, sumpPct))}%`, background: sumpPct < 10 ? chart.low : chart.baseline, transition: 'width 500ms ease' }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
