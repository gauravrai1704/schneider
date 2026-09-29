function Counter({ label, value, unit }) {
  return (
    <div className="panel px-4 py-3 flex-1 min-w-[140px]">
      <div className="panel-label text-xs mb-1">{label}</div>
      <div className="font-mono text-xl text-text-primary">
        {value} <span className="text-sm text-text-dim">{unit}</span>
      </div>
    </div>
  )
}

export default function ImpactCounters({ kwhShifted, peakReductionPct, tanksReporting }) {
  return (
    <div className="flex gap-3 flex-wrap">
      <Counter label="kWh shifted today" value={kwhShifted.toFixed(2)} unit="kWh" />
      <Counter label="Peak load cut" value={peakReductionPct.toFixed(0)} unit="%" />
      <Counter label="Tanks reporting" value={tanksReporting} unit="live" />
    </div>
  )
}
