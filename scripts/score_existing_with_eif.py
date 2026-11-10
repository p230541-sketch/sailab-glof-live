"""Give every usable camera measurement already in the database the new score (Extended Isolation
Forest), next to the z-score it already has, and write a table comparing the two.

    python scripts/score_existing_with_eif.py            # the real database, sailab_glof.db
    python scripts/score_existing_with_eif.py --db sample_data/sample_glof.db

Safe to run again: a measurement that already has the new score is skipped. No z-score row is changed.
Each reading is scored from the readings before its own date only, exactly as a live run would have.
The comparison is written to logs/<date>_eif_vs_zscore.md (real database only).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sailab import db, pipeline, risk_eif  # noqa: E402

REAL_DB = REPO / "sailab_glof.db"
SENSOR = "optical"      # radar is not scored by either method (pipeline.SCORE_RADAR is off)


def score_missing(conn: sqlite3.Connection) -> dict[str, int]:
    """Add the new score to every usable optical measurement that does not have it yet, oldest first."""
    lakes = {row["id"]: row for row in db.get_lakes(conn)}
    todo = conn.execute(
        "SELECT m.id, m.lake_id, m.extent_ha, s.acquired_at, s.file_path FROM measurement m "
        "JOIN scene s ON s.id = m.scene_id WHERE m.status = 'ok' AND m.sensor = ? AND NOT EXISTS "
        "(SELECT 1 FROM risk_score r WHERE r.measurement_id = m.id AND r.method = ?) ORDER BY s.acquired_at, m.id",
        (SENSOR, db.RISK_METHOD_EIF)).fetchall()
    counts = {"ok": 0, "insufficient_history": 0}
    for row in todo:
        status = pipeline.score_eif(conn, lakes[row["lake_id"]], row["acquired_at"], Path(row["file_path"]).stem,
                                    row["id"], row["extent_ha"], SENSOR)
        counts[status] += 1
    return counts


def comparison_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """One row per usable optical measurement with both scores side by side."""
    return conn.execute(
        "SELECT l.code, substr(s.acquired_at, 1, 10) AS day, m.extent_ha, "
        "z.status AS z_status, z.baseline_ha AS z_baseline, z.deviation_score AS z_score, "
        "e.status AS e_status, e.baseline_ha AS e_usual, e.score_0_100 AS e_score, e.reason AS e_reason "
        "FROM measurement m JOIN scene s ON s.id = m.scene_id JOIN lake l ON l.id = m.lake_id "
        "LEFT JOIN risk_score z ON z.measurement_id = m.id AND z.method = ? "
        "LEFT JOIN risk_score e ON e.measurement_id = m.id AND e.method = ? "
        "WHERE m.status = 'ok' AND m.sensor = ? ORDER BY l.code, s.acquired_at",
        (db.RISK_METHOD_SEASONAL_ZSCORE, db.RISK_METHOD_EIF, SENSOR)).fetchall()


def comparison_markdown(rows: list[sqlite3.Row], db_name: str) -> str:
    def number(value, digits):
        return "-" if value is None else f"{value:.{digits}f}"

    both = [r for r in rows if r["z_status"] == "ok" and r["e_status"] == "ok"]
    flagged = [r for r in both if r["e_score"] >= risk_eif.FLAG_SCORE]
    lines = [
        f"# Old score (z-score) against new score (Extended Isolation Forest): {db_name}",
        "",
        f"Written by `scripts/score_existing_with_eif.py` on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.",
        "Every number below is read from the database; nothing is typed in by hand.",
        "",
        f"- Usable optical measurements: **{len(rows)}**",
        f"- With a z-score: **{sum(r['z_status'] == 'ok' for r in rows)}**",
        f"- With the new score: **{sum(r['e_status'] == 'ok' for r in rows)}**",
        f"- With both: **{len(both)}**",
        f"- New score at or above the flag line ({risk_eif.FLAG_SCORE:.0f}): **{len(flagged)}**",
        "",
        "The z-score counts spreads (how many normal swings away from the same-month mean). The new score is",
        "0 to 100 (0 = an ordinary reading, 100 = as alone as a reading can be). They are different scales, so",
        "compare which readings each one picks out, not the numbers themselves.",
        "",
        "| Lake | Date | Area (ha) | z-score | New score | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        z = number(r["z_score"], 2) if r["z_status"] == "ok" else "too little history"
        e = number(r["e_score"], 1) if r["e_status"] == "ok" else "too little history"
        lines.append(f"| {r['code']} | {r['day']} | {r['extent_ha']:.2f} | {z} | {e} | {r['e_reason'] or '-'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=REAL_DB, help="database to score (default: the real one)")
    args = parser.parse_args(argv)
    db_path = args.db.resolve()
    conn = db.connect(db_path)
    counts = score_missing(conn)
    rows = comparison_rows(conn)
    conn.close()
    print(f"{db_path.name}: new scores written: {counts['ok']} ok, {counts['insufficient_history']} with too little history")
    text = comparison_markdown(rows, db_path.name)
    if db_path == REAL_DB.resolve():
        out = REPO / "logs" / f"{datetime.now(timezone.utc):%Y-%m-%d}_eif_vs_zscore.md"
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"comparison written to {out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
