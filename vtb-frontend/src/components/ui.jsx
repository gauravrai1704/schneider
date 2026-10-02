import { IconAlert, IconCheck, IconInfo, IconStop } from './icons'
import { useTheme } from '../theme'

const TONES = {
  good: { cls: 'bg-good-soft text-good-text', Icon: IconCheck },
  warning: { cls: 'bg-warning-soft text-warning-text', Icon: IconAlert },
  critical: { cls: 'bg-critical-soft text-critical-text', Icon: IconStop },
  neutral: { cls: 'bg-raised text-ink-secondary', Icon: IconInfo },
}

/** Status is never colour alone: every chip carries an icon and a word. */
export function StatusChip({ tone = 'neutral', children }) {
  const { cls, Icon } = TONES[tone] || TONES.neutral
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      <Icon width={12} height={12} />
      {children}
    </span>
  )
}

export function Banner({ tone = 'neutral', title, children, action }) {
  const { cls, Icon } = TONES[tone] || TONES.neutral
  return (
    <div className={`flex items-start gap-3 rounded-card px-4 py-3 ${cls}`} role={tone === 'critical' ? 'alert' : 'status'}>
      <Icon width={18} height={18} className="mt-0.5 shrink-0" />
      <div className="flex-1 text-sm">
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className="opacity-90">{children}</div>}
      </div>
      {action}
    </div>
  )
}

export function Card({ title, subtitle, right, className = '', children }) {
  return (
    <section className={`card min-w-0 p-4 ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-subtitle mt-0.5">{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  )
}

export function StatTile({ label, value, unit, hint, icon, accent }) {
  return (
    <div className="card flex min-w-0 flex-col gap-1 p-4">
      <div className="flex items-center gap-1.5 text-xs text-ink-muted">
        {icon && <span className={accent}>{icon}</span>}
        {label}
      </div>
      <div className="text-2xl font-semibold text-ink">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-ink-muted">{unit}</span>}
      </div>
      {hint && <div className="text-xs text-ink-muted">{hint}</div>}
    </div>
  )
}

/** Small legend key: coloured line beside text-coloured label (text never wears the series colour). */
export function LegendKey({ color, label, dashed }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-secondary">
      <svg width="16" height="8" aria-hidden>
        <line x1="1" y1="4" x2="15" y2="4" stroke={color} strokeWidth="2" strokeLinecap="round" strokeDasharray={dashed ? '3 3' : undefined} />
      </svg>
      {label}
    </span>
  )
}

/** Themed Recharts tooltip. */
export function ChartTooltip({ active, payload, label, labelFormatter, unit = 'W' }) {
  const { chart } = useTheme()
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-ink">{labelFormatter ? labelFormatter(label) : label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2 text-ink-secondary">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color || chart.ink }} />
          <span>{p.name}</span>
          <span className="num ml-auto pl-3 font-medium text-ink">
            {Math.round(p.value).toLocaleString('en-IN')} {unit}
          </span>
        </div>
      ))}
    </div>
  )
}

export function Segmented({ options, value, onChange, label }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg border border-line bg-raised p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          title={o.title}
          aria-pressed={value === o.value}
          className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
            value === o.value ? 'bg-surface font-medium text-ink shadow-sm' : 'text-ink-muted hover:text-ink'
          }`}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  )
}
