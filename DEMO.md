# Demo rehearsal script

A run-through of the live demo, following the final demo flow in the project plan. It takes about 6 minutes. Rehearse it end to end at least twice, once with the hardware and once without.

---

## T−30 min: set up

**1. Run the preflight check** (from `vtb-backend`, with the venv active):

```powershell
python -m tools.preflight
```

Fix every `FAIL`. Read every `WARN`.

**2. Start the servers.** Pick the variant that matches the situation:

| Situation | Terminal 1 (backend, in `vtb-backend`) |
|---|---|
| Normal: mock buildings, daytime | `uvicorn app.main:app --port 8000` |
| **Demo slot after ~4 pm** (no real sun) | `$env:VTB_DEMO_TIME="11:30"; uvicorn app.main:app --port 8000` |
| No venue wifi | add `$env:VTB_OFFLINE="1";` before `uvicorn` |
| Physical model connected | see [With the hardware](#with-the-hardware) below |

Then start the dashboard (Terminal 2, in `vtb-frontend`): `npm run dev`.

**3. Open these tabs in one browser window:**
- http://localhost:5173/#discom
- http://localhost:5173/#resident
- http://localhost:5173/#simulation
- http://localhost:8000/docs, in case a judge asks about the API

**4. Reset leftover state from rehearsals:**
- If the red banner shows, press **Resume all pumps**.
- On the Resident tab, press **Demo: fix the leak** if it's showing.
- On the solar card, press **Clear the cloud** if it's showing.

**5. Pick the theme.** Projectors wash out dark themes, so use **light** (the sun icon, top right) unless the room is dark.

**6. Run preflight once more.** It warns if a pause is still active.

---

## The demo (≈6 min)

### 1. Hook (30 s)
> "India is adding solar fast, but output drops with clouds and every evening, and weak feeders black out first. Batteries are expensive. But almost every Indian building already has a sump, a pump and a rooftop tank. Pumping is flexible: it doesn't matter *when* water goes up, as long as the tank never runs dry."

### 2. Sunny: pumps fill the tanks (1 min) — *Grid operator tab*
- **SoC gauge:** "the virtual battery: kWh of pumping this feeder can still absorb right now".
- **Solar tile and building cards:** cards read *"Running on spare solar power"*. Pumps start one by one, not all at once ("staggered so feeder voltage stays stable").
- **Forecast chart:** "Six-hour forecast. The solar model is trained on a year of NASA satellite data, the load model on real Delhi SLDC demand for BSES Yamuna."
- If a card says *"Waiting (grid peak)"*: "It holds pumps back so moving load into solar hours never creates a new peak."

### 3. Cover the panel: the forecast flags a dip (1 min)
- **With hardware:** physically cover the solar panel.
- **Without hardware:** press **Simulate cloud** on the solar card.
- **Point at:** the live solar chart drops, the forecast updates, and new starts stop ("No spare solar right now").
- **Key line:** "Water supply stays safe. Any tank close to its safe level still refills, whatever the grid is doing."

### 4. DISCOM Pump Pause (45 s)
- Press **Pause all pumps**. The red banner appears and every pump stops within a second.
- "One tap gives the DISCOM instant demand response. The card shows how many watts were shed and how long every building can safely wait."
- Scroll to **Today on this feeder**: the pause is counted as a demand-response event.
- Leave the pause on for the next step.

### 5. Resident view (1 min) — *Resident tab*
- Pick **Building 3**. Show the level, litres, sump, and *"Next run: when the grid operator ends the pause"*.
- Press **Demo: simulate a leak**. About 60 seconds later a red **Possible leak** alert appears: *"draining at ~250 L/h with the pump off; normal use right now is ~30 L/h"*. Fill the wait with the next talking point.
- **Savings card:** "Solar hours are 20% cheaper under the 2023 time-of-day rules, so residents save money just by pumping at noon."
- Go back to Grid operator and press **Resume all pumps**.

### 6. Scale: 500 buildings (1 min) — *Simulation tab*
- Set the slider to **500** and press **Run**.

| Typical Oct day, 500 buildings | Today | VTB |
|---|---|---|
| Pumping on solar | 44% | **96%** |
| Evening-peak pumping | 19 kWh | **0** |
| Energy moved into solar hours | — | **93 kWh/day** (≈ 19 MWh/day per lakh buildings) |
| Feeder net peak | 508 kW | 500 kW (−1.5%) |
| Time below safe level | 0% | **0%** |

- Tick **Cloudy day** (the real cloudiest day that October) and run again: solar share goes **21% → 94%**, still with no evening pumping and no dry tanks.
- "The dotted green line is a linear program that knows the whole day in advance. Our live controller gets close to it."

### 7. Close (15 s)
> **"India already owns millions of batteries. They're on its rooftops, filled with water."**

---

## Numbers to have ready

| Claim | Number | Source |
|---|---|---|
| Solar forecast error, 1–6 h | **46 W/m²** vs 71 for the raw weather forecast | held-out weeks, `metadata.json` |
| Load forecast error | **5.8%** vs 7.1% for same-time-yesterday | held-out weeks |
| Training data | 1 year of Delhi data, Jul 2025 – Jun 2026 | NASA POWER, Open-Meteo, Delhi SLDC |
| Retrofit cost | ₹500–800 per building | project plan |

## Likely judge questions

- **"Why does the overall peak only drop 1–2%?"** Delhi's evening peak is mostly household demand; pumping is about 4% of a home's energy. The value is *controllable, flexible* load: nearly all pumping on solar, zero evening pumping, instant pause capacity, and no new peak. We didn't tune the assumptions to inflate this.
- **"What's real and what's simulated?"** Solar, weather and load data are real, and the live feeds are real. Water demand is synthetic, scaled to the CPHEEO 135 L/person/day norm. Tank telemetry comes from the physical model, or from the mock. Open "Data sources & model accuracy" at the bottom of the Grid operator tab to show it.
- **"What if the internet or the server goes down?"** The forecasts fall back to cached data and the trained models (`VTB_OFFLINE`). The firmware runs its own safety rules and falls back to them if no command arrives for about 3 minutes.
- **"Does a pause ever leave someone without water?"** No. A tank below its safe level keeps refilling even during a pause.
- **"Is the 'best possible' line a cheat?"** It's a benchmark that knows the whole day in advance; it isn't the live controller. It shows how close the live rules get.

## Fallbacks

| Problem | Do this |
|---|---|
| Hardware stops responding | Restart the backend without `VTB_MQTT_URL`; the mock buildings take over, and Simulate cloud replaces covering the panel |
| No wifi | Restart with `$env:VTB_OFFLINE="1"` |
| Evening slot, no sun | Restart with `$env:VTB_DEMO_TIME="11:30"`; a "Demo clock" badge shows in the header. Say so if asked |
| Dashboard shows "Reconnecting…" | The backend isn't running on port 8000; check Terminal 1 |
| Leak alert doesn't appear | Make sure pumps are paused; detection needs about a minute with the pump idle |
| Simulation is slow | It takes 2–4 s for 500 buildings. Click Run once before the demo to warm the cache |

## With the hardware

Three terminals in `vtb-backend`, venv active:

```powershell
python -m tools.local_broker                                   # 1. MQTT broker on port 1883 (no Mosquitto needed)
$env:VTB_MQTT_URL="mqtt://localhost:1883"; uvicorn app.main:app --host 0.0.0.0 --port 8000   # 2. backend
python -m tools.preflight                                      # 3. check
```

- **Point the ESP32s** at this laptop's IP, port 1883. Topics and payloads are in `vtb-backend/docs/api_contract.md`.
- **To rehearse without the physical model:** run `python -m tools.fake_esp32 --broker mqtt://localhost:1883` in place of the ESP32s.
- **Demo buttons:** in MQTT mode the dashboard's Simulate cloud and Simulate leak buttons are hidden, because they only drive the mock. Cover the real panel instead.
