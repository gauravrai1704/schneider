/** A tank rendered like a physical sight-glass gauge: a vertical vessel with
 * a fill level, a safe-minimum tick, and a small amber dot when the pump is
 * actively running. This stands in for a generic progress bar because the
 * subject matter (a literal water tank) has its own real-world gauge form. */
export default function TankGlass({ id, levelPct = 0, pumpOn = false, safeMinPct = 15 }) {
  const clamped = Math.max(0, Math.min(100, levelPct))
  const fillHeight = (clamped / 100) * 84
  const isLow = clamped < safeMinPct

  return (
    <div className="flex flex-col items-center gap-1 w-16">
      <svg width="40" height="100" viewBox="0 0 40 100">
        {/* vessel outline */}
        <rect x="4" y="8" width="32" height="88" rx="3" fill="none" stroke="#263449" strokeWidth="2" />
        {/* safe-minimum tick */}
        <line x1="2" y1={96 - (safeMinPct / 100) * 84} x2="8" y2={96 - (safeMinPct / 100) * 84}
              stroke="#E15252" strokeWidth="1.5" />
        {/* fill */}
        <rect
          x="6" y={94 - fillHeight} width="28" height={fillHeight} rx="1.5"
          fill={isLow ? '#E15252' : '#4FB8C4'}
          opacity="0.85"
        />
        {/* pump indicator */}
        <circle cx="20" cy="4" r="3.5" fill={pumpOn ? '#E8A33D' : '#263449'} />
      </svg>
      <span className="text-[10px] text-text-dim font-mono leading-none">{id.replace('tank-', 'T')}</span>
      <span className="text-[10px] font-mono leading-none" style={{ color: isLow ? '#E15252' : '#E8EDF4' }}>
        {clamped.toFixed(0)}%
      </span>
    </div>
  )
}
