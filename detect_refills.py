#!/usr/bin/env python3
"""
Detecta reposiciones (y retiradas) de bicis en BiciMAD a partir de la base de
datos que genera collector.py, y resume a qué horas ocurren.

Idea: un usuario cambia el contador de 1 en 1. Un camión de rebalanceo mete o
saca muchas bicis de golpe. Se buscan saltos grandes entre dos consultas
consecutivas, fusionando los que caen en una ventana corta (una descarga puede
quedar partida entre dos consultas).

Uso:
  python detect_refills.py --db bicimad.sqlite
  python detect_refills.py --min-jump 6 --merge-window 600
  python detect_refills.py --station "Sol"        # filtra por nombre o id
Requiere: pandas, numpy, matplotlib
Salidas (en --out): events.csv, station_summary.csv, heatmap_reposiciones.png,
                    hist_horas.png
"""
import argparse
import os
import sqlite3

import numpy as np
import pandas as pd

TZ = "Europe/Madrid"
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def load(db):
    con = sqlite3.connect(db)
    r = pd.read_sql("SELECT * FROM readings ORDER BY station_id, ts", con)
    polls = pd.read_sql("SELECT ts FROM polls WHERE ok=1 ORDER BY ts", con)["ts"].to_numpy()
    st = pd.read_sql("SELECT station_id, name, capacity FROM stations", con)
    con.close()
    return r, polls, st


def step_changes(r, polls, max_gap):
    """Cambio entre cada lectura y la anterior de la misma estación, y cuánto
    tiempo pudo tardar (desde la consulta exitosa previa)."""
    r = r.copy()
    g = r.groupby("station_id")
    r["delta"] = r["bikes"] - g["bikes"].shift()
    r["prev_renting"] = g["is_renting"].shift()
    r = r.dropna(subset=["delta"])

    idx = np.searchsorted(polls, r["ts"].to_numpy(), side="left") - 1
    prev_poll = np.where(idx >= 0, polls[np.clip(idx, 0, None)], np.nan)
    r["window_s"] = r["ts"].to_numpy() - prev_poll
    # Descartar cambios tras huecos en la recogida (no sabemos cuándo pasaron)
    # y estaciones fuera de servicio (al reactivarlas el contador salta).
    ok = (r["window_s"] <= max_gap) & (r["is_renting"] != 0) & (r["prev_renting"] != 0)
    return r[ok]


def merge_events(ch, min_step, merge_window, min_jump):
    """Fusiona saltos consecutivos del mismo signo en la misma estación."""
    c = ch[ch["delta"].abs() >= min_step].sort_values(["station_id", "ts"]).copy()
    c["sign"] = np.sign(c["delta"])
    new = (
        (c["station_id"] != c["station_id"].shift())
        | (c["sign"] != c["sign"].shift())
        | (c["ts"] - c["ts"].shift() > merge_window)
    )
    c["event_id"] = new.cumsum()
    ev = c.groupby("event_id").agg(
        station_id=("station_id", "first"),
        ts_start=("ts", "first"),
        ts_end=("ts", "last"),
        delta=("delta", "sum"),
        bikes_after=("bikes", "last"),
        n_steps=("delta", "size"),
    )
    ev = ev[ev["delta"].abs() >= min_jump].reset_index(drop=True)
    ev["tipo"] = np.where(ev["delta"] > 0, "reposicion", "retirada")
    t = pd.to_datetime(ev["ts_start"], unit="s", utc=True).dt.tz_convert(TZ)
    ev["fecha_hora"] = t.dt.strftime("%Y-%m-%d %H:%M")
    ev["hora"] = t.dt.hour + t.dt.minute / 60
    ev["dia_semana"] = t.dt.dayofweek
    return ev


def summarize(ev, st):
    rep = ev[ev["tipo"] == "reposicion"].copy()

    def franja(h):
        # Hora "típica": mediana circular aproximada (evita romperse a medianoche)
        ang = h / 24 * 2 * np.pi
        m = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) % (2 * np.pi)
        return m / (2 * np.pi) * 24

    def fmt(h):
        return f"{int(h):02d}:{int(round((h % 1) * 60)) % 60:02d}"

    s = rep.groupby("station_id").agg(
        n_reposiciones=("delta", "size"),
        bicis_medias=("delta", "mean"),
        hora_media=("hora", lambda h: fmt(franja(h))),
        horas=("hora", lambda h: ", ".join(sorted({f"{int(x):02d}h" for x in h}))),
    )
    s = s.join(st.set_index("station_id")[["name", "capacity"]], how="left")
    return s.sort_values("n_reposiciones", ascending=False)


def plots(ev, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rep = ev[ev["tipo"] == "reposicion"]
    ret = ev[ev["tipo"] == "retirada"]

    fig, ax = plt.subplots(figsize=(9, 4))
    bins = np.arange(0, 24.5, 0.5)
    ax.hist(rep["hora"], bins=bins, alpha=0.7, label=f"Reposiciones (n={len(rep)})")
    ax.hist(ret["hora"], bins=bins, alpha=0.5, label=f"Retiradas (n={len(ret)})")
    ax.set_xlabel("Hora del día (Madrid)")
    ax.set_ylabel("Eventos")
    ax.set_xticks(range(0, 25, 2))
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out, "hist_horas.png"), dpi=150)

    m = np.zeros((7, 24))
    for d, h in zip(rep["dia_semana"], rep["hora"].astype(int)):
        m[d, h] += 1
    fig, ax = plt.subplots(figsize=(10, 3.5))
    im = ax.imshow(m, aspect="auto", cmap="viridis")
    ax.set_yticks(range(7), DIAS)
    ax.set_xticks(range(24))
    ax.set_xlabel("Hora (Madrid)")
    ax.set_title("Reposiciones por día y hora")
    fig.colorbar(im, ax=ax, label="Eventos")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "heatmap_reposiciones.png"), dpi=150)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="bicimad.sqlite")
    ap.add_argument("--out", default="resultados")
    ap.add_argument("--min-jump", type=int, default=5,
                    help="bicis netas mínimas para considerar reposición/retirada")
    ap.add_argument("--min-step", type=int, default=2,
                    help="salto mínimo entre consultas para entrar en la fusión")
    ap.add_argument("--merge-window", type=int, default=420,
                    help="s entre saltos para fusionarlos en un evento")
    ap.add_argument("--max-gap", type=int, default=180,
                    help="s máximos desde la consulta previa (descarta huecos)")
    ap.add_argument("--station", help="filtra por station_id o parte del nombre")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    r, polls, st = load(args.db)
    if args.station:
        mask = (st["station_id"] == args.station) | st["name"].str.contains(
            args.station, case=False, na=False)
        ids = set(st.loc[mask, "station_id"])
        r = r[r["station_id"].isin(ids)]
        print(f"Estaciones seleccionadas: {', '.join(st.loc[mask, 'name'])}")

    span_h = (polls[-1] - polls[0]) / 3600 if len(polls) > 1 else 0
    print(f"{len(polls)} consultas OK en {span_h:.1f} h; {len(r)} lecturas")

    ch = step_changes(r, polls, args.max_gap)
    ev = merge_events(ch, args.min_step, args.merge_window, args.min_jump)
    ev = ev.merge(st[["station_id", "name"]], on="station_id", how="left")
    ev.to_csv(os.path.join(args.out, "events.csv"), index=False)

    print(f"Eventos: {(ev.tipo == 'reposicion').sum()} reposiciones, "
          f"{(ev.tipo == 'retirada').sum()} retiradas")
    if ev.empty:
        print("Sin eventos todavía: deja el recolector más tiempo o baja --min-jump.")
        return

    s = summarize(ev, st)
    s.to_csv(os.path.join(args.out, "station_summary.csv"))
    print("\nEstaciones con más reposiciones:")
    print(s.head(15).to_string())

    plots(ev, args.out)
    print(f"\nResultados en {args.out}/")


if __name__ == "__main__":
    main()
