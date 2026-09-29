/** Arc gauge styled like a physical substation meter dial, not a generic
 * donut chart — thick tick marks, a single needle-like value label. */
export default function SocGauge({ socKwh = 0, socPct = 0 }) {
  const angle = -90 + (socPct / 100) * 180 // sweep from -90deg to +90deg
  const rad = (angle * Math.PI) / 180
  const cx = 90, cy = 90, r = 68
  const needleX = cx + r * Math.cos(rad)
  const needleY = cy + r * Math.sin(rad)

  const ticks = Array.from({ length: 11 }, (_, i) => {
    const a = -90 + (i / 10) * 180
    const rr = (a * Math.PI) / 180
    const inner = 58, outer = 68
    return {
      x1: cx + inner * Math.cos(rr), y1: cy + inner * Math.sin(rr),
      x2: cx + outer * Math.cos(rr), y2: cy + outer * Math.sin(rr),
    }
  })

  return (
    <div className="flex flex-col items-center">
      <svg width="180" height="110" viewBox="0 0 180 110">
        <path d={`M 22 90 A 68 68 0 0 1 158 90`} fill="none" stroke="#263449" strokeWidth="10" strokeLinecap="round" />
        <path
          d={`M 22 90 A 68 68 0 0 1 158 90`}
          fill="none" stroke="#E8A33D" strokeWidth="10" strokeLinecap="round"
          strokeDasharray={`${(socPct / 100) * 213.6} 213.6`}
        />
        {ticks.map((t, i) => (
          <line key={i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} stroke="#7C8CA3" strokeWidth="1.5" />
        ))}
        <line x1={cx} y1={cy} x2={needleX} y2={needleY} stroke="#E8EDF4" strokeWidth="2" />
        <circle cx={cx} cy={cy} r="4" fill="#E8EDF4" />
      </svg>
      <div className="text-center -mt-2">
        <div className="font-mono text-2xl text-text-primary leading-none">{socKwh.toFixed(1)}</div>
        <div className="panel-label text-xs text-text-dim">kWh deferrable now</div>
      </div>
    </div>
  )
}
