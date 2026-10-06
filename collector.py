#!/usr/bin/env python3
"""
Recolector del estado de las estaciones BiciMAD (feed oficial GBFS) -> SQLite.

Uso:
  python collector.py                      # bucle continuo, consulta cada 60 s
  python collector.py --interval 90        # otro intervalo
  python collector.py --once               # una sola consulta (para lanzarlo con cron)
  python collector.py --db /ruta/bicimad.sqlite

Solo usa la librería estándar de Python (>=3.9).

Tablas:
  stations(station_id, name, lat, lon, capacity, updated)
  polls(ts, ok, n_stations)          -> cada consulta, para saber si hubo huecos
  readings(ts, station_id, bikes, docks, is_renting, is_returning, last_reported)
      -> solo se guarda una fila cuando cambia el estado de la estación
         (ahorra ~95 % de espacio; los huecos se detectan con la tabla polls)
"""
import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime

DISCOVERY_URL = "https://madrid.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json"
USER_AGENT = "bicimad-refill-study/0.1 (uso personal)"
STATION_INFO_REFRESH_S = 6 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations(
    station_id TEXT PRIMARY KEY, name TEXT, lat REAL, lon REAL,
    capacity INTEGER, updated INTEGER);
CREATE TABLE IF NOT EXISTS polls(
    ts INTEGER PRIMARY KEY, ok INTEGER, n_stations INTEGER);
CREATE TABLE IF NOT EXISTS readings(
    ts INTEGER, station_id TEXT, bikes INTEGER, docks INTEGER,
    is_renting INTEGER, is_returning INTEGER, last_reported INTEGER,
    PRIMARY KEY (station_id, ts));
"""


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def discover_feeds(url=DISCOVERY_URL):
    data = get_json(url)["data"]
    feeds = data.get("feeds")
    if feeds is None:  # GBFS 2.x: data -> {idioma: {feeds: [...]}}
        lang = "es" if "es" in data else next(iter(data))
        feeds = data[lang]["feeds"]
    return {f["name"]: f["url"] for f in feeds}


def localized(v):
    """GBFS 3.0 usa [{'text':..., 'language':...}]; 2.x usa un string."""
    if isinstance(v, list):
        for item in v:
            if str(item.get("language", "")).startswith("es"):
                return item.get("text")
        return v[0].get("text") if v else None
    return v


def to_epoch(v):
    """last_reported: entero POSIX (2.x) o RFC3339 (3.0)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def as_int(v):
    return None if v is None else int(bool(v)) if isinstance(v, bool) else int(v)


def update_stations(con, url):
    stations = get_json(url)["data"]["stations"]
    now = int(time.time())
    con.executemany(
        "INSERT OR REPLACE INTO stations VALUES (?,?,?,?,?,?)",
        [(str(s["station_id"]), localized(s.get("name")), s.get("lat"), s.get("lon"),
          s.get("capacity"), now) for s in stations])
    con.commit()
    log(f"station_information actualizado: {len(stations)} estaciones")


def load_last_state(con):
    rows = con.execute("""
        SELECT r.station_id, r.bikes, r.docks, r.is_renting, r.is_returning
        FROM readings r
        JOIN (SELECT station_id, MAX(ts) AS ts FROM readings GROUP BY station_id) m
          ON r.station_id = m.station_id AND r.ts = m.ts""").fetchall()
    return {sid: tuple(rest) for sid, *rest in rows}


def poll_once(con, status_url, last_state):
    ts = int(time.time())
    try:
        stations = get_json(status_url)["data"]["stations"]
    except Exception as e:
        con.execute("INSERT OR REPLACE INTO polls VALUES (?,?,?)", (ts, 0, 0))
        con.commit()
        log(f"ERROR en la consulta: {e}")
        return False

    new_rows = []
    for s in stations:
        sid = str(s["station_id"])
        bikes = s.get("num_vehicles_available", s.get("num_bikes_available"))
        state = (as_int(bikes), as_int(s.get("num_docks_available")),
                 as_int(s.get("is_renting")), as_int(s.get("is_returning")))
        if last_state.get(sid) != state:
            new_rows.append((ts, sid, *state, to_epoch(s.get("last_reported"))))
            last_state[sid] = state

    con.executemany("INSERT OR REPLACE INTO readings VALUES (?,?,?,?,?,?,?)", new_rows)
    con.execute("INSERT OR REPLACE INTO polls VALUES (?,?,?)", (ts, 1, len(stations)))
    con.commit()
    log(f"{len(stations)} estaciones, {len(new_rows)} cambios guardados")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="bicimad.sqlite")
    ap.add_argument("--interval", type=int, default=60, help="segundos entre consultas")
    ap.add_argument("--once", action="store_true", help="una sola consulta y salir")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.executescript(SCHEMA)

    feeds = discover_feeds()
    for needed in ("station_status", "station_information"):
        if needed not in feeds:
            sys.exit(f"El feed no publica {needed}. Feeds disponibles: {list(feeds)}")

    update_stations(con, feeds["station_information"])
    last_info = time.time()
    last_state = load_last_state(con)

    if args.once:
        poll_once(con, feeds["station_status"], last_state)
        return

    log(f"Recolectando cada {args.interval} s en {args.db} (Ctrl+C para parar)")
    fails = 0
    while True:
        t0 = time.time()
        ok = poll_once(con, feeds["station_status"], last_state)
        fails = 0 if ok else fails + 1
        try:
            if fails >= 5:  # quizá cambió la URL: redescubrir
                feeds = discover_feeds()
                fails = 0
            if time.time() - last_info > STATION_INFO_REFRESH_S:
                update_stations(con, feeds["station_information"])
                last_info = time.time()
        except Exception as e:
            log(f"ERROR actualizando metadatos: {e}")
        time.sleep(max(1, args.interval - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Parado.")
