import { createContext, createElement, useContext, useEffect, useRef, useState } from 'react'

export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const WS_BASE = API_BASE.replace(/^http/, 'ws')

async function getJson(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json()
}

export const getTanks = () => getJson('/tanks')
export const getFeederSoc = () => getJson('/feeder/soc')
export const getForecast = (horizons = '0,15,30,60') => getJson(`/forecast?horizons=${horizons}`)
export const getLoadCurve = () => getJson('/loadcurve')
export const getSources = () => getJson('/sources')
export const getSimulation = (nBuildings, cloudyDay) =>
  getJson(`/simulate?n_buildings=${nBuildings}&cloudy_day=${cloudyDay}`)

export async function postPause(active) {
  const res = await fetch(`${API_BASE}/pause`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active }),
  })
  return res.json()
}

const SOLAR_HISTORY_POINTS = 90 // ~3 minutes at one reading every 2 s

/** Live WebSocket feed: reconnects automatically and keeps the latest state
 * per tank, the latest pump decision (with its reason) per tank, and a short
 * solar history. One connection shared by every view via LiveFeedProvider. */
function useLiveFeedState() {
  const [connected, setConnected] = useState(false)
  const [tanksById, setTanksById] = useState({})
  const [commandsById, setCommandsById] = useState({})
  const [solar, setSolar] = useState(null)
  const [solarHistory, setSolarHistory] = useState([])
  const [paused, setPaused] = useState(false)
  const wsRef = useRef(null)

  useEffect(() => {
    // Seed from REST so views have data immediately, before the first live message
    getTanks()
      .then((rows) => setTanksById((prev) => {
        const next = { ...prev }
        for (const r of rows) if (!next[r.building_id]) next[r.building_id] = r
        return next
      }))
      .catch(() => { /* backend not up yet — the WebSocket will fill in */ })
  }, [])

  useEffect(() => {
    let cancelled = false
    let retryTimer = null

    function connect() {
      const ws = new WebSocket(`${WS_BASE}/ws/live`)
      wsRef.current = ws

      ws.onopen = () => !cancelled && setConnected(true)
      ws.onclose = () => {
        if (cancelled) return
        setConnected(false)
        retryTimer = setTimeout(connect, 2000)
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (evt) => {
        const msg = JSON.parse(evt.data)
        if (msg.type === 'tank_telemetry') {
          setTanksById((prev) => ({ ...prev, [msg.building_id]: msg }))
        } else if (msg.type === 'solar_telemetry') {
          setSolar(msg)
          setSolarHistory((prev) => [...prev.slice(-(SOLAR_HISTORY_POINTS - 1)), { ts: Date.parse(msg.ts), w: msg.solar_w }])
        } else if (msg.type === 'pause_state') {
          setPaused(msg.active)
        } else if (msg.type === 'pump_commands') {
          setCommandsById((prev) => {
            const next = { ...prev }
            for (const c of msg.commands) next[c.building_id] = c
            return next
          })
        }
      }
    }
    connect()

    return () => {
      cancelled = true
      clearTimeout(retryTimer)
      wsRef.current?.close()
    }
  }, [])

  return { connected, tanksById, commandsById, solar, solarHistory, paused, setPaused }
}

const LiveFeedContext = createContext(null)

export function LiveFeedProvider({ children }) {
  return createElement(LiveFeedContext.Provider, { value: useLiveFeedState() }, children)
}

export function useLiveFeed() {
  return useContext(LiveFeedContext)
}

/** Polls a REST endpoint; keeps the last good value if the backend blips. */
export function usePoll(fetcher, intervalMs, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const d = await fetcher()
        if (alive) { setData(d); setError(null) }
      } catch (e) {
        if (alive) setError(e)
      }
    }
    tick()
    const t = setInterval(tick, intervalMs)
    return () => { alive = false; clearInterval(t) }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error }
}
