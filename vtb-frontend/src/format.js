/** Plain-language labels for backend codes, so nobody has to read internal ids. */

const SOLAR_SOURCES = {
  'ml+open-meteo+panel': 'live weather + panel reading',
  'ml+open-meteo': 'live weather',
  'open-meteo': 'weather forecast only',
  'clear-sky-persistence': 'clear-sky estimate (offline)',
  heuristic: 'typical profile (offline)',
}
const LOAD_SOURCES = {
  'ml+sldc-live': 'live Delhi SLDC load',
  'ml-calendar-weather': 'calendar + weather',
  heuristic: 'typical profile (offline)',
}

export const solarSourceLabel = (s) => SOLAR_SOURCES[s] || s || '—'
export const loadSourceLabel = (s) => LOAD_SOURCES[s] || s || '—'

export function tankName(id) {
  const m = /^tank-(\d+)$/.exec(id || '')
  return m ? `Building ${Number(m[1])}` : id
}

export function fmt(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtDuration(minutes) {
  if (minutes == null) return '—'
  if (minutes >= 24 * 60) return 'a full day'
  const h = Math.floor(minutes / 60), m = Math.round(minutes % 60)
  return h ? `${h} h ${m ? `${m} min` : ''}`.trim() : `${m} min`
}

export function clockLabel(ms) {
  return new Date(ms).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

/** Backend scheduler reasons -> plain language. */
export function explainReason(reason) {
  if (!reason) return ''
  const solar = /solar surplus \((\d+)W\)/.exec(reason)
  if (solar) return `Running on spare solar power (${solar[1]} W available).`
  if (reason.includes('predicted dip')) return 'Solar is forecast to drop within the hour — filling up while it lasts.'
  const supply = /municipal supply at (\d{2}:\d{2})/.exec(reason)
  if (supply) return `Municipal water arrives at ${supply[1]} — moving sump water up so none is turned away.`
  if (reason.includes('municipal supply on now')) return 'Municipal water is flowing and the sump is nearly full — moving water up so none is wasted.'
  if (reason.includes('below safe minimum')) return 'Below the safe level — refilling now, whatever the grid is doing.'
  if (reason.includes('no surplus and no dip')) return 'No spare solar right now — waiting for the next green window.'
  if (reason.includes('held for staggered start')) return 'Starts are staggered so the feeder voltage stays stable.'
  if (reason.includes('dry-run')) return 'Sump is nearly empty — pump stopped so it cannot run dry.'
  if (reason.includes('overflow')) return 'Tank is full — pump stopped to prevent overflow.'
  if (reason.includes('DISCOM pause')) return 'Paused by the grid operator for demand response.'
  return reason[0].toUpperCase() + reason.slice(1)
}

/** Pump state shown to people: what it's doing and why, in one short phrase.
 * The latest scheduler command is the intent; telemetry can lag it by a tick. */
export function pumpStatus(tank, command, paused) {
  if (paused) return { tone: 'critical', label: 'Paused by DISCOM', reason: 'Emergency demand response is active. Local safety rules still protect the water supply.' }
  const reason = command?.reason || ''
  if (command?.action === 'ON' || (!command && tank?.pump_on)) {
    return { tone: 'good', label: 'Pumping', reason: explainReason(reason) || 'Filling the tank.' }
  }
  if (reason.includes('held for staggered start')) return { tone: 'warning', label: 'Starting soon', reason: explainReason(reason) }
  if (reason.includes('dry-run')) return { tone: 'critical', label: 'Protected', reason: explainReason(reason) }
  if (reason.includes('overflow')) return { tone: 'good', label: 'Full', reason: explainReason(reason) }
  return { tone: 'neutral', label: 'Idle', reason: explainReason(reason) || 'Waiting for the next green window.' }
}
