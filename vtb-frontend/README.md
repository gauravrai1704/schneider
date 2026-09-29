# Virtual Tank Battery — Dashboard

DISCOM console, resident view, and neighbourhood simulation for the Virtual
Tank Battery project. Built as a grid-operator console (tank sight-glasses,
a substation-style SoC dial, an emergency-stop-style Pump Pause) rather than
a generic analytics template — see the visual language notes at the bottom.

## Run it

```bash
npm install
npm run dev
```

Opens on `http://localhost:5173`. It expects the backend running at
`http://localhost:8000` (see `../vtb-backend`) — set `VITE_API_BASE` in a
`.env` file if it's running elsewhere.

## Structure

```
src/
  api.js                    REST calls + a useLiveFeed() WebSocket hook
  App.jsx                   tab shell (DISCOM / Resident / Simulation)
  components/
    DiscomView.jsx           SoC gauge, forecast charts, tank grid, pump pause
    ResidentView.jsx         single-tank view, plain-language alerts
    SimulationView.jsx       building-count slider, before/after load curve
    SocGauge.jsx              custom arc-dial SVG
    TankGlass.jsx             custom sight-glass tank SVG
    PumpPauseButton.jsx       emergency-stop-styled control
    ImpactCounters.jsx        small stat strip
```

## Design language

Palette and type were chosen to read as real substation/utility console
software rather than a SaaS dashboard: a deep navy background (`#0D1420`)
with amber (`#E8A33D`, "stored energy") and cyan (`#4FB8C4`, "water/flow")
accents, Barlow Condensed for headers (equipment-nameplate feel) and IBM
Plex Mono for all data (telemetry-readout feel). Panels use amber corner
brackets instead of rounded-card shadows, tanks are literal sight-glasses,
and Pump Pause is styled like a physical E-stop — each visual choice ties
back to what the thing actually is, not a generic component kit.

## Known gaps to fill before the demo

- `ResidentView` currently shows the first tank in the live feed
  (`tanksById`) as a stand-in for "my building" — wire up per-resident
  identity once there's auth or a building selector.
- `DiscomView`'s kWh-shifted counter accrues from live pump commands as a
  rough running estimate; for the pitch, prefer the simulator's more
  rigorous per-run number for headline claims.
