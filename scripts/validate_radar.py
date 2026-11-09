"""Validate radar lake areas against optical ones measured within a few days (run after a radar backfill).

    .venv/bin/python scripts/validate_radar.py

For every usable ('ok') radar measurement, finds the nearest usable optical measurement of the same lake
within MAX_GAP_DAYS and compares the two areas. The radar method's settings (slope limit 10 degrees) were
fixed BEFORE this was run, so the numbers below are a test of the method, not a tuning of it.
Read-only: it changes nothing.
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

REPO = Path(__file__).resolve().parent.parent
MAX_GAP_DAYS = 3


def main() -> int:
    db = sqlite3.connect(REPO / "sailab_glof.db")
    rows = db.execute("""SELECT l.code, s.acquired_at, m.sensor, m.status, m.extent_ha
                         FROM measurement m JOIN scene s ON s.id = m.scene_id JOIN lake l ON l.id = m.lake_id
                         ORDER BY l.code, s.acquired_at""").fetchall()
    print(f"checked_at {datetime.now(timezone.utc).isoformat(timespec='seconds')}; pairing window +-{MAX_GAP_DAYS} days\n")

    by_lake: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for code, when, sensor, status, extent in rows:
        by_lake[code][sensor].append((datetime.fromisoformat(when), status, extent))

    all_pct = []
    for code, sensors in sorted(by_lake.items()):
        radar = sensors.get("radar", [])
        optical_ok = [(t, e) for t, st, e in sensors.get("optical", []) if st == "ok"]
        print(f"=== {code}")
        print(f"  radar measurements: {len(radar)} ({Counter(st for _, st, _ in radar)})")
        print("  radar 'ok' by month:", dict(sorted(Counter(t.strftime('%m') for t, st, _ in radar if st == 'ok').items())))
        print("  optical 'ok' by month:", dict(sorted(Counter(t.strftime('%m') for t, _ in optical_ok).items())))
        pairs = []
        for t, st, e in radar:
            if st != "ok" or not optical_ok:
                continue
            ot, oe = min(optical_ok, key=lambda o: abs((o[0] - t).total_seconds()))
            gap = abs((ot - t).total_seconds()) / 86400
            if gap <= MAX_GAP_DAYS:
                pairs.append((t, e, ot, oe, gap))
        if not pairs:
            print("  no radar/optical pairs within the window\n")
            continue
        diffs = [e - oe for _, e, _, oe, _ in pairs]
        pct = [100 * (e - oe) / oe for _, e, _, oe, _ in pairs]
        all_pct += pct
        print(f"  pairs within {MAX_GAP_DAYS} days: {len(pairs)}")
        print(f"  radar - optical: mean {mean(diffs):+.2f} ha ({mean(pct):+.1f}%), median {median(pct):+.1f}%, "
              f"mean absolute {mean(abs(p) for p in pct):.1f}%, worst {max(pct, key=abs):+.1f}%")
        for t, e, ot, oe, gap in pairs:
            print(f"    radar {t:%Y-%m-%d %H:%M} {e:8.2f} ha | optical {ot:%Y-%m-%d} {oe:8.2f} ha | gap {gap:.1f} d | "
                  f"{100 * (e - oe) / oe:+.1f}%")
        print()
    if all_pct:
        print(f"ALL LAKES: {len(all_pct)} pairs, mean {mean(all_pct):+.1f}%, mean absolute {mean(abs(p) for p in all_pct):.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
