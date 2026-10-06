#!/usr/bin/env python3
"""
Exporta un resumen compacto de bicimad.sqlite a data.json para el dashboard.

Uso:
  python export_dashboard.py --db bicimad.sqlite --out docs/data.json
"""
import argparse
import json
import sqlite3
import time

import numpy as np
import pandas as pd

from detect_refills import TZ, load, merge_events, step_changes


def circular_mean_hour(hours):
    if len(hours) == 0:
        return None
    ang = np.asarray(hours) / 24 * 2 * np.pi
    m = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) % (2 * np.pi)
    return round(float(m / (2 * np.pi) * 24), 2)


def latest_state(db):
    con = sqlite3.connect(db)
    df = pd.read_sql("""
        SELECT r.station_id, r.bikes, r.docks, r.is_renting
        FROM readings r
        JOIN (SELECT station_id, MAX(ts) AS ts FROM readings GROUP BY station_id) m
          ON r.station_id = m.station_id AND r.ts = m.ts""", con)
    con.close()
    return df.set_index("station_id")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="bicimad.sqlite")
    ap.add_argument("--out", default="docs/data.json")
    ap.add_argument("--min-jump", type=int, default=5)
    ap.add_argument("--min-step", type=int, default=2)
    ap.add_argument("--merge-window", type=int, default=420)
    ap.add_argument("--max-gap", type=int, default=180)
    ap.add_argument("--recent", type=int, default=150, help="nº de eventos recientes")
    args = ap.parse_args()

    r, polls, st = load(args.db)
    ch = step_changes(r, polls, args.max_gap)
    ev = merge_events(ch, args.min_step, args.merge_window, args.min_jump)
    state = latest_state(args.db)

    rep = ev[ev["tipo"] == "reposicion"]
    ret = ev[ev["tipo"] == "retirada"]

    stations = []
    for s in st.itertuples():
        sr = rep[rep["station_id"] == s.station_id]
        hours = np.bincount(sr["hora"].astype(int), minlength=24).tolist()
        cur = state.loc[s.station_id] if s.station_id in state.index else None
        stations.append({
            "id": s.station_id,
            "name": s.name,
            "lat": s.lat,
            "lon": s.lon,
            "cap": None if pd.isna(s.capacity) else int(s.capacity),
            "bikes": None if cur is None else int(cur["bikes"]),
            "open": None if cur is None else bool(cur["is_renting"]),
            "nRep": int(len(sr)),
            "nRet": int((ret["station_id"] == s.station_id).sum()),
            "meanHour": circular_mean_hour(sr["hora"]),
            "avgBikes": round(float(sr["delta"].mean()), 1) if len(sr) else None,
            "hours": hours,
        })

    heat = np.zeros((7, 24), dtype=int)
    for d, h in zip(rep["dia_semana"], rep["hora"].astype(int)):
        heat[d, h] += 1

    bins = np.arange(0, 24.5, 0.5)
    recent = ev.sort_values("ts_start", ascending=False).head(args.recent)

    data = {
        "generated": int(time.time()),
        "firstPoll": int(polls[0]) if len(polls) else None,
        "lastPoll": int(polls[-1]) if len(polls) else None,
        "nPolls": int(len(polls)),
        "timezone": TZ,
        "params": {k: getattr(args, k) for k in ("min_jump", "merge_window", "max_gap")},
        "stations": stations,
        "histRep": np.histogram(rep["hora"], bins=bins)[0].tolist(),
        "histRet": np.histogram(ret["hora"], bins=bins)[0].tolist(),
        "heat": heat.tolist(),
        "recent": [{"id": e.station_id, "t": e.fecha_hora, "d": int(e.delta)}
                   for e in recent.itertuples()],
    }
    with open(args.out, "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{args.out}: {len(stations)} estaciones, {len(rep)} reposiciones, "
          f"{len(ret)} retiradas")


if __name__ == "__main__":
    main()
