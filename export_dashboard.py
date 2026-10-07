#!/usr/bin/env python3
"""
Exporta la ocupación de las estaciones (bicis disponibles a lo largo del tiempo)
de bicimad.sqlite a data.json para el dashboard.

La base de datos solo guarda cambios; aquí se reconstruye el estado de cada
estación en una rejilla regular (por defecto cada 15 min). Los instantes sin
una consulta correcta reciente (hueco en la recogida) quedan como null, igual
que los de estaciones fuera de servicio.

Uso:
  python export_dashboard.py --db bicimad.sqlite --out docs/data.json
  python export_dashboard.py --step 600 --days 14
"""
import argparse
import json
import time
import warnings

import numpy as np
import pandas as pd

from detect_refills import TZ, load


def state_grid(r, polls, station_ids, grid, max_gap):
    """Matriz (estaciones × instantes) con las bicis de cada estación en cada
    instante de la rejilla; NaN si no hay dato fiable."""
    i = np.searchsorted(polls, grid, side="right") - 1
    valid = (i >= 0) & (grid - polls[np.clip(i, 0, None)] <= max_gap)

    B = np.full((len(station_ids), len(grid)), np.nan)
    row = {sid: k for k, sid in enumerate(station_ids)}
    for sid, g in r.groupby("station_id"):
        if sid not in row:
            continue
        ts = g["ts"].to_numpy()
        j = np.searchsorted(ts, grid, side="right") - 1
        has = j >= 0
        jj = np.clip(j, 0, None)
        ok = has & valid & (g["is_renting"].to_numpy()[jj] != 0)
        B[row[sid]] = np.where(ok, g["bikes"].to_numpy()[jj], np.nan)
    return B


def rounded(a, nd=1):
    """Lista JSON: redondea y cambia NaN por None."""
    a = np.round(np.asarray(a, dtype=float), nd)
    return [None if np.isnan(v) else (int(v) if nd == 0 else float(v)) for v in a]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="bicimad.sqlite")
    ap.add_argument("--out", default="docs/data.json")
    ap.add_argument("--step", type=int, default=900, help="segundos entre puntos (divisor de 86400)")
    ap.add_argument("--days", type=float, default=7, help="días de serie temporal publicados")
    ap.add_argument("--max-gap", type=int, default=180,
                    help="sin consulta correcta en estos segundos = hueco")
    args = ap.parse_args()
    if 86400 % args.step:
        ap.error("--step debe dividir 86400")

    r, polls, st = load(args.db)
    if len(polls) == 0:
        raise SystemExit("La base de datos no tiene consultas correctas todavía.")
    st = st.sort_values("station_id").reset_index(drop=True)
    cap = st["capacity"].to_numpy(dtype=float)
    cap[cap <= 0] = np.nan

    # Rejilla sobre todo el periodo (para perfiles y % vacía/llena) ...
    grid = np.arange(-(-polls[0] // args.step) * args.step, polls[-1] + 1, args.step)
    B = state_grid(r, polls, st["station_id"].tolist(), grid, args.max_gap)
    # ... y solo los últimos --days días se publican como serie
    recent = grid > polls[-1] - args.days * 86400

    local = pd.to_datetime(grid, unit="s", utc=True).tz_convert(TZ)
    slot = np.asarray((local.hour * 3600 + local.minute * 60) // args.step)
    weekend = np.asarray(local.dayofweek >= 5)
    n_slots = 86400 // args.step

    def profile(M, mask):
        out = np.full((M.shape[0], n_slots), np.nan)
        for s in range(n_slots):
            cols = mask & (slot == s)
            if cols.any():
                out[:, s] = np.nanmean(M[:, cols], axis=1)
        return out

    seen = ~np.isnan(B)
    with warnings.catch_warnings():  # filas o columnas sin datos -> NaN, es lo esperado
        warnings.simplefilter("ignore", RuntimeWarning)
        prof_wd, prof_we = profile(B, ~weekend), profile(B, weekend)
        n_seen = seen.sum(axis=1)
        p_empty = np.where(n_seen, (B == 0).sum(axis=1) / n_seen, np.nan)
        p_full = np.where(n_seen, (B >= cap[:, None]).sum(axis=1) / n_seen, np.nan)
        # Red: bicis totales / capacidad de las estaciones con dato en ese instante
        net_bikes = np.where(seen.any(axis=0), np.nansum(B, axis=0), np.nan)
        net_occ = net_bikes / np.nansum(np.where(seen, cap[:, None], np.nan), axis=0)
        net_wd = profile(net_occ[None, :], ~weekend)[0]
        net_we = profile(net_occ[None, :], weekend)[0]

    renting_now = r.groupby("station_id")["is_renting"].last()  # r va ordenado por ts
    stations = []
    for k, s in enumerate(st.itertuples()):
        series = B[k, recent]
        last = series[~np.isnan(series)]
        stations.append({
            "id": s.station_id,
            "name": s.name,
            "lat": s.lat,
            "lon": s.lon,
            "cap": None if np.isnan(cap[k]) else int(cap[k]),
            "bikes": int(last[-1]) if len(last) else None,
            "open": bool(renting_now.get(s.station_id, 1)),
            "pEmpty": rounded([p_empty[k]], 3)[0],
            "pFull": rounded([p_full[k]], 3)[0],
            "s": rounded(series, 0),
            "wd": rounded(prof_wd[k]),
            "we": rounded(prof_we[k]),
        })

    data = {
        "generated": int(time.time()),
        "firstPoll": int(polls[0]),
        "lastPoll": int(polls[-1]),
        "nPolls": int(len(polls)),
        "timezone": TZ,
        "step": args.step,
        "maxGap": args.max_gap,
        "t0": int(grid[recent][0]) if recent.any() else None,
        "net": {"bikes": rounded(net_bikes[recent], 0), "occ": rounded(net_occ[recent], 3),
                "wd": rounded(net_wd, 3), "we": rounded(net_we, 3)},
        "stations": stations,
    }
    with open(args.out, "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{args.out}: {len(stations)} estaciones, {int(recent.sum())} instantes "
          f"cada {args.step // 60} min ({(polls[-1] - polls[0]) / 86400:.1f} días de datos)")


if __name__ == "__main__":
    main()
