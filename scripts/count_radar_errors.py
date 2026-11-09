"""Count the usable radar values that are clearly wrong, with a stated, reproducible rule.

Run:   .venv/bin/python scripts/count_radar_errors.py

Rule: a usable (status 'ok') radar area is counted as clearly wrong when it is more than 15% away from
that lake's median usable OPTICAL area. Why 15%: in the summer comparison with near-same-day optical
(logs/2026-11-09_radar_validation.log) the largest radar-optical difference was +13.0%, so 15% is just
beyond anything radar showed on days it could be checked. This is a judgement, not a calibrated limit;
the counts at 10%, 20% and 25% are printed too, so the effect of the choice is visible.
Read-only: opens the database without writing.
"""
from __future__ import annotations

import sqlite3
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RULE = 0.15


def main() -> int:
    db = sqlite3.connect(f"file:{REPO / 'sailab_glof.db'}?mode=ro", uri=True)
    print(f"checked {datetime.now(timezone.utc).isoformat(timespec='seconds')}; rule: radar 'ok' area more than "
          f"{RULE:.0%} from the lake's median optical 'ok' area\n")
    total_radar = total_wrong = 0
    sensitivity = Counter()
    for lake_id, code in db.execute("SELECT id, code FROM lake ORDER BY id"):
        def ok(sensor: str) -> list[tuple[str, float]]:
            return db.execute("""SELECT s.acquired_at, m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id
                                 WHERE m.lake_id = ? AND m.sensor = ? AND m.status = 'ok' ORDER BY s.acquired_at""",
                              (lake_id, sensor)).fetchall()
        optical, radar = ok("optical"), ok("radar")
        median = statistics.median(v for _, v in optical)
        wrong = [(d, v) for d, v in radar if abs(v - median) > RULE * median]
        for f in (0.10, 0.20, 0.25):
            sensitivity[f] += sum(abs(v - median) > f * median for _, v in radar)
        total_radar += len(radar)
        total_wrong += len(wrong)
        months = Counter(datetime.fromisoformat(d).strftime("%b") for d, _ in wrong)
        print(f"{code}: optical median {median:.2f} ha (from {len(optical)} values); allowed "
              f"{median * (1 - RULE):.2f}-{median * (1 + RULE):.2f} ha")
        print(f"  {len(wrong)} of {len(radar)} usable radar values outside; by month: "
              + ", ".join(f"{m} {n}" for m, n in sorted(months.items(), key=lambda kv: datetime.strptime(kv[0], "%b").month)))
        for d, v in wrong:
            print(f"    {d[:10]}  {v:8.2f} ha  ({(v - median) / median:+.1%})")
    print(f"\nTOTAL: {total_wrong} of {total_radar} usable radar values ({total_wrong / total_radar:.1%}) are outside the rule.")
    print("Sensitivity to the limit: " + ", ".join(f"{f:.0%}: {sensitivity[f]}" for f in (0.10, 0.20, 0.25)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
