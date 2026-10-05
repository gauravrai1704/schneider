"""
Demo-day preflight: checks everything the live demo needs, in one go.

    python -m tools.preflight              # full check (pings live data sources)
    python -m tools.preflight --offline    # skip internet checks (venue wifi down)

Exit code 0 = ready (warnings allowed), 1 = something must be fixed first.
"""
from __future__ import annotations
import argparse
import importlib
import json
import os
import socket
import sys
import time
import urllib.request
from urllib.parse import urlparse

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(os.path.dirname(BACKEND), "vtb-frontend")
results: list[tuple[str, str, str]] = []   # (status, check, detail)


def ok(check, detail=""):
    results.append(("OK  ", check, detail))


def warn(check, detail):
    results.append(("WARN", check, detail))


def fail(check, detail):
    results.append(("FAIL", check, detail))


def _get(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"User-Agent": "VirtualTankBattery-preflight"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def check_python():
    v = sys.version_info
    (ok if v >= (3, 11) else fail)("Python version", f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 11) else " - need 3.11+"))


def check_packages():
    required = ["fastapi", "uvicorn", "sqlalchemy", "pandas", "numpy", "lightgbm", "joblib", "paho.mqtt.client",
                "pulp", "requests", "bs4", "holidays"]
    missing = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        fail("Python packages", f"missing {', '.join(missing)} - run: pip install -r requirements.txt")
    else:
        ok("Python packages", "all required packages import")
    try:
        import pulp
        solvers = pulp.listSolvers(onlyAvailable=True)
        (ok if solvers else fail)("LP solver", ", ".join(solvers) if solvers else "none - pip install highspy")
    except ImportError:
        pass
    try:
        importlib.import_module("amqtt")
        ok("Local MQTT broker", "amqtt available (python -m tools.local_broker)")
    except ImportError:
        warn("Local MQTT broker", "amqtt not installed - only needed for the hardware path without Mosquitto")


def check_models_and_data():
    store = os.path.join(BACKEND, "app", "models_store")
    needed = ["solar_obs_model.joblib", "solar_nwp_model.joblib", "load_model.joblib", "metadata.json"]
    missing = [f for f in needed if not os.path.exists(os.path.join(store, f))]
    if missing:
        fail("Trained models", f"missing {missing} - run: python -m app.train_forecast")
    else:
        meta = json.load(open(os.path.join(store, "metadata.json")))
        ok("Trained models", f"trained on {meta.get('train_window')}")
    data = os.path.join(BACKEND, "data", "processed")
    csvs = ["solar_nasa_power.csv", "weather_openmeteo.csv", "load_delhi_sldc.csv"]
    missing = [f for f in csvs if not os.path.exists(os.path.join(data, f))]
    (fail if missing else ok)("Training data", f"missing {missing}" if missing else "NASA POWER, Open-Meteo, Delhi SLDC CSVs present")


def check_internet():
    from datetime import date, timedelta
    sources = {
        "Open-Meteo forecast": "https://api.open-meteo.com/v1/forecast?latitude=28.61&longitude=77.21&hourly=temperature_2m&forecast_days=1",
        "Delhi SLDC load": f"https://www.delhisldc.org/Loaddata.aspx?mode={(date.today() - timedelta(days=1)):%d/%m/%Y}",
    }
    for name, url in sources.items():
        try:
            t = time.time()
            status, _ = _get(url)
            (ok if status == 200 else warn)(name, f"HTTP {status} in {time.time() - t:.1f}s")
        except Exception as e:
            cache = os.path.join(BACKEND, "data", "cache")
            has_cache = os.path.isdir(cache) and os.listdir(cache)
            warn(name, f"unreachable ({e.__class__.__name__}) - " +
                 ("will use cached data" if has_cache else "no cache yet; forecasts fall back to models only"))


def _port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def check_servers(api: str):
    try:
        status, body = _get(f"{api}/health", 3)
        if status == 200 and b"ok" in body:
            ok("Backend", f"running at {api}")
            return True
    except Exception:
        pass
    port = urlparse(api).port or 8000
    if _port_open("127.0.0.1", port):
        fail("Backend", f"port {port} is in use by something that isn't the VTB backend")
    else:
        warn("Backend", f"not running - start it: uvicorn app.main:app --port {port}")
    return False


def check_mqtt():
    url = os.environ.get("VTB_MQTT_URL")
    if not url:
        ok("MQTT", "not configured - backend will use the built-in mock buildings")
        return
    p = urlparse(url)
    host, port = p.hostname or "localhost", p.port or 1883
    (ok if _port_open(host, port) else fail)("MQTT broker", f"{host}:{port} " + ("reachable" if _port_open(host, port) else
                                             "NOT reachable - start it: python -m tools.local_broker"))


def check_frontend():
    if not os.path.isdir(FRONTEND):
        warn("Dashboard", "vtb-frontend folder not found")
        return
    if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        fail("Dashboard", "dependencies missing - run: cd vtb-frontend && npm install")
    else:
        ok("Dashboard", "dependencies installed (start: npm run dev)")


def check_api_flow(api: str):
    try:
        _, body = _get(f"{api}/sources", 10)
        src = json.loads(body)
        feeds = src["feeds"]
        label = lambda f: "fresh" if f.get("fresh") else f"{f['source']} (stale)"  # noqa: E731
        stale = [n for n in ("weather", "grid") if not feeds[n].get("fresh")]
        (warn if stale else ok)("Live feeds (backend view)",
                                f"weather {label(feeds['weather'])}, grid {label(feeds['grid'])}, "
                                f"mock {'on' if src.get('mock_running') else 'off'}")
        _, body = _get(f"{api}/tanks", 5)
        n = len(json.loads(body))
        (ok if n else warn)("Telemetry", f"{n} tanks reporting" if n else "no tanks reporting yet")
        t = time.time()
        _, body = _get(f"{api}/simulate?n_buildings=50", 60)
        sim = json.loads(body)
        ok("Simulator", f"{sim['optimizer_status']} in {time.time() - t:.1f}s")
        _, body = _get(f"{api}/pause", 5)
        if json.loads(body).get("active"):
            warn("Pump Pause", "a pause is still ACTIVE from earlier - press Resume before the demo")
        else:
            ok("Pump Pause", "not active")
    except Exception as e:
        fail("API flow", f"{e.__class__.__name__}: {e}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="skip internet checks")
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    sys.path.insert(0, BACKEND)

    check_python()
    check_packages()
    check_models_and_data()
    if not args.offline:
        check_internet()
    check_mqtt()
    check_frontend()
    if check_servers(args.api):
        check_api_flow(args.api)

    width = max(len(c) for _, c, _ in results)
    for status, check, detail in results:
        print(f"[{status}] {check:<{width}}  {detail}")
    failed = sum(1 for s, _, _ in results if s == "FAIL")
    warned = sum(1 for s, _, _ in results if s == "WARN")
    print(f"\n{'NOT READY' if failed else 'READY'}: {failed} failed, {warned} warnings")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
