import { useEffect, useRef, useState } from 'react'

export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const WS_BASE = API_BASE.replace(/^http/, 'ws')

export async function getTanks() {
  const res = await fetch(`${API_BASE}/tanks`)
  return res.json()
}

export async function getFeederSoc() {
  const res = await fetch(`${API_BASE}/feeder/soc`)
  return res.json()
}

export async function getForecast(horizons = '0,15,30,60') {
  const res = await fetch(`${API_BASE}/forecast?horizons=${horizons}`)
  return res.json()
}

export async function getLoadCurve() {
  const res = await fetch(`${API_BASE}/loadcurve`)
  return res.json()
}

export async function postPause(active) {
  const res = await fetch(`${API_BASE}/pause`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active }),
  })
  return res.json()
}

export async function getSimulation(nBuildings, cloudyDay) {
  const res = await fetch(`${API_BASE}/simulate?n_buildings=${nBuildings}&cloudy_day=${cloudyDay}`)
  return res.json()
}

/** Live WebSocket feed: reconnects automatically, exposes the most recent
 * event of each type so components can react to whichever ones they care about. */
export function useLiveFeed() {
  const [connected, setConnected] = useState(false)
  const [tanksById, setTanksById] = useState({})
  const [solar, setSolar] = useState(null)
  const [paused, setPaused] = useState(false)
  const [lastCommands, setLastCommands] = useState([])
  const wsRef = useRef(null)

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
        } else if (msg.type === 'pause_state') {
          setPaused(msg.active)
        } else if (msg.type === 'pump_commands') {
          setLastCommands(msg.commands)
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

  return { connected, tanksById, solar, paused, lastCommands }
}
