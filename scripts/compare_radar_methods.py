"""Radar water measurement: plain Otsu (old) against Edge Otsu (Markert et al. 2020), on every stored radar pass.

    python scripts/compare_radar_methods.py

Both use the same slope mask (pipeline.RADAR_SLOPE_LIMIT_DEG) and the same lake growing and refusals; only
the cutoff differs. The Edge Otsu result of each pass is saved in the alt_measurement table (method
'edge_otsu'); the original radar rows are never changed. Writes logs/<date>_radar_methods_comparison.md.

Two measures of "better", both read from the database:
  - clearly wrong values: more than 15% away from the lake's median usable optical area (the same rule
    as scripts/count_radar_errors.py);
  - camera against radar: radar minus optical (NDWI, cutoff 0.2) for passes within 3 days of a usable
    optical scene (the same pairing as scripts/validate_radar.py).
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sailab import db, pipeline, radar_edge_otsu as eo  # noqa: E402
from sailab.radar import load_slope  # noqa: E402

DB_PATH = REPO / "sailab_glof.db"
WRONG_SHARE = 0.15
PAIR_DAYS = 3


def main() -> int:
    conn = db.connect(DB_PATH)
    lakes = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM lake")}
    slopes = {lake_id: load_slope(REPO / "data" / "dem" / f"{lake['code']}_dem.tif") for lake_id, lake in lakes.items()}
    rows = conn.execute("SELECT m.id, m.lake_id, s.file_path FROM measurement m JOIN scene s ON s.id = m.scene_id "
                        "WHERE m.sensor = 'radar' ORDER BY s.acquired_at").fetchall()
    coverage = defaultdict(list)
    missing = 0
    for row in rows:
        path = REPO / row["file_path"]
        if not path.is_file():
            missing += 1
            continue
        outcome, covered = eo.measure_radar_edge_otsu(path, lakes[row["lake_id"]], slopes[row["lake_id"]],
                                                      pipeline.RADAR_SLOPE_LIMIT_DEG)
        db.insert_alt_measurement(conn, row["id"], eo.METHOD, outcome.status, outcome.extent_ha, outcome.threshold_db)
        if covered:
            coverage[row["lake_id"]].append(covered)

    lines = [
        "# Radar water measurement: plain Otsu (old) against Edge Otsu (new)",
        "",
        f"Written by `scripts/compare_radar_methods.py` on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. "
        "Every number is read from the database.",
        "",
        f"Edge Otsu (Markert et al. 2020, section 2.3.2) with the paper's numbers: initial cutoff "
        f"{eo.INITIAL_THRESHOLD_DB} dB, edges over {eo.MIN_EDGE_LENGTH_M:.0f} m, {eo.BUFFER_M:.0f} m buffer on each side. "
        f"Both methods use the same {pipeline.RADAR_SLOPE_LIMIT_DEG:.0f} degree slope mask and the same refusals. "
        f"Passes with no stored picture on this machine: {missing}.",
        "",
    ]
    for lake_id, lake in sorted(lakes.items()):
        optical = [(date.fromisoformat(r[0][:10]), r[1]) for r in conn.execute(
            "SELECT s.acquired_at, m.extent_ha FROM measurement m JOIN scene s ON s.id = m.scene_id "
            "WHERE m.lake_id = ? AND m.sensor = 'optical' AND m.status = 'ok'", (lake_id,))]
        optical_median = median(a for _, a in optical)
        lines += [f"### {lake['code']} (median usable optical area {optical_median:.2f} ha)", "",
                  "| Method | Passes | Usable (ok) | Refused | Clearly wrong (over 15% from optical median) | "
                  "Radar minus optical within 3 days: median, pairs |", "|---|---|---|---|---|---|"]
        for label, query in (
                ("Plain Otsu (old)", "SELECT s.acquired_at, m.status, m.extent_ha FROM measurement m JOIN scene s "
                                     "ON s.id = m.scene_id WHERE m.lake_id = ? AND m.sensor = 'radar'"),
                ("Edge Otsu (new)", "SELECT s.acquired_at, a.status, a.extent_ha FROM alt_measurement a JOIN measurement m "
                                    "ON m.id = a.measurement_id JOIN scene s ON s.id = m.scene_id WHERE m.lake_id = ? "
                                    "AND m.sensor = 'radar' AND a.method = 'edge_otsu'")):
            results = [(date.fromisoformat(r[0][:10]), r[1], r[2]) for r in conn.execute(query, (lake_id,))]
            ok = [(d, a) for d, status, a in results if status == "ok"]
            wrong = sum(abs(a - optical_median) > WRONG_SHARE * optical_median for _, a in ok)
            diffs = [a - o for d, a in ok for od, o in optical if abs((d - od).days) <= PAIR_DAYS]
            lines.append(f"| {label} | {len(results)} | {len(ok)} | {len(results) - len(ok)} | "
                         f"{wrong} of {len(ok)} ({wrong / max(len(ok), 1):.1%}) | "
                         + (f"{median(diffs):+.2f} ha, {len(diffs)} |" if diffs else "no pairs |"))
        if coverage[lake_id]:
            lines += ["", f"Share of the usable window the Edge Otsu buffer covered: median "
                      f"{median(coverage[lake_id]):.0%} (1.0 would be the same as plain Otsu)."]
        lines.append("")
    conn.close()
    out = REPO / "logs" / f"{datetime.now(timezone.utc):%Y-%m-%d}_radar_methods_comparison.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
