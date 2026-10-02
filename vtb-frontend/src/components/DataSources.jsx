import { fmt } from '../format'
import { IconChevron } from './icons'
import { StatusChip } from './ui'

function feedChip(feed) {
  if (!feed) return <StatusChip tone="neutral">Unknown</StatusChip>
  if (feed.source === 'live') return <StatusChip tone="good">Live</StatusChip>
  if (feed.source === 'disk-cache') return <StatusChip tone="warning">Cached</StatusChip>
  return <StatusChip tone="critical">Unavailable</StatusChip>
}

function age(sec) {
  if (sec == null) return ''
  if (sec < 90) return `updated ${sec}s ago`
  if (sec < 5400) return `updated ${Math.round(sec / 60)} min ago`
  return `updated ${Math.round(sec / 3600)} h ago`
}

function Row({ name, detail, right }) {
  return (
    <div className="flex items-start justify-between gap-3 border-t border-line py-2 first:border-t-0">
      <div>
        <div className="text-sm text-ink">{name}</div>
        <div className="text-xs text-ink-muted">{detail}</div>
      </div>
      <div className="shrink-0">{right}</div>
    </div>
  )
}

/** "Where do these numbers come from?" — live feed health and the trained
 * models' held-out accuracy against simple baselines. */
export default function DataSources({ sources }) {
  const feeds = sources?.feeds
  const models = sources?.models
  const s = models?.solar_metrics
  const l = models?.load_metrics

  return (
    <details className="card group p-4">
      <summary className="flex cursor-pointer list-none items-center justify-between">
        <div>
          <h2 className="card-title">Data sources & model accuracy</h2>
          <p className="card-subtitle mt-0.5">All public data, no API keys. Real vs synthetic is labelled below.</p>
        </div>
        <IconChevron className="text-ink-muted transition-transform group-open:rotate-180" />
      </summary>

      <div className="mt-4 grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">Live feeds</h3>
          <Row name="Weather forecast" detail={`Open-Meteo · ${age(feeds?.weather?.age_sec)}`} right={feedChip(feeds?.weather)} />
          <Row name="Delhi grid load" detail={`Delhi SLDC (BYPL) · ${age(feeds?.grid?.age_sec)}`} right={feedChip(feeds?.grid)} />
          <Row name="Tank & panel telemetry" detail="Simulated buildings until the hardware is connected" right={<StatusChip tone="warning">Mock</StatusChip>} />
          <Row name="Water demand" detail="Synthetic, scaled to CPHEEO 135 L/person/day" right={<StatusChip tone="neutral">Synthetic</StatusChip>} />
        </div>
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Forecast accuracy {models?.train_window ? `(trained ${models.train_window[0]} → ${models.train_window[1]})` : ''}
          </h3>
          <Row
            name="Solar, 1–6 h ahead"
            detail={s ? `Weather-forecast-only baseline: ${fmt(s.baseline_raw_open_meteo)} W/m² error` : 'NASA POWER irradiance'}
            right={<span className="num text-sm font-semibold text-ink">{s ? `${fmt(s.ml_with_live_panel)} W/m²` : '—'}</span>}
          />
          <Row
            name="Feeder load, 15 min–6 h ahead"
            detail={l ? `"Same time yesterday" baseline: ${fmt(l.baseline_same_time_yesterday?.mape_pct, 1)}% error` : 'Delhi SLDC load'}
            right={<span className="num text-sm font-semibold text-ink">{l ? `${fmt(l.ml_with_live_sldc?.mape_pct, 1)}%` : '—'}</span>}
          />
          <p className="mt-2 text-xs text-ink-muted">Lower is better. Measured on held-out weeks across every season.</p>
        </div>
      </div>
    </details>
  )
}
