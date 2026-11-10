"""SAMPLE DATA. Build a separate database of made-up measurements for tests and demos.

    python scripts/make_sample_db.py

Writes sample_data/sample_glof.db (deleted and rebuilt on every run). It holds the three made-up lakes
from sailab/sample_data.py, their made-up areas, and the scores the real scoring code gives them.
It never touches sailab_glof.db, the real database, and refuses if asked to.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sailab import db, pipeline, sample_data  # noqa: E402

REAL_DB = REPO / "sailab_glof.db"
DEFAULT_OUT = REPO / "sample_data" / "sample_glof.db"
SAMPLE_PASS_TIME = "T06:00:00+00:00"   # a made-up time of day for every made-up scene


def build_sample_db(out_path: Path) -> dict[str, int]:
    """Create the sample database at out_path. Returns how many rows of each kind were written."""
    out_path = Path(out_path).resolve()
    if out_path == REAL_DB.resolve():
        raise ValueError("refusing to write sample data into the real database (sailab_glof.db)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)

    conn = db.connect(out_path)
    run_id = db.start_run_log(conn)
    result = pipeline.RunResult(run_id=run_id)
    counts = {"lakes": 0, "measurements": 0, "scores": 0}
    for lake in sample_data.SAMPLE_LAKES:
        # Coordinates 0, 0 on purpose: an obviously made-up place, never a real lake's position.
        lake_id = db.insert_lake(conn, lake.code, lake.name, 0.0, 0.0, 1000.0, 1000.0)
        lake_row = {"id": lake_id, "code": lake.code}
        counts["lakes"] += 1
        for m in sample_data.sample_series(lake):
            acquired_at = m.observed_on.isoformat() + SAMPLE_PASS_TIME
            scene_name = f"{m.observed_on.isoformat()}_sample"
            scene_id = db.insert_scene(conn, lake_id, "sentinel-2", acquired_at, 0.0,
                                       f"{sample_data.SAMPLE_PATH_PREFIX}{lake.code}/{scene_name}.tif")
            measurement_id = db.insert_measurement(conn, scene_id, lake_id, "optical", m.extent_ha, "ok")
            counts["measurements"] += 1
            # The real scoring code, unchanged: same z-score and same minimum-history rule as real lakes get.
            pipeline._score(conn, lake_row, SimpleNamespace(acquired_at=acquired_at, scene_id=scene_name),
                            measurement_id, m.extent_ha, "optical", result)
            pipeline.score_eif(conn, lake_row, acquired_at, scene_name, measurement_id, m.extent_ha, "optical")
            counts["scores"] += 1
    db.finish_run_log(conn, run_id, counts["lakes"], 0)
    conn.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the sample database")
    args = parser.parse_args(argv)
    counts = build_sample_db(args.out)
    print(f"SAMPLE DATA written to {args.out}")
    print(f"  {counts['lakes']} made-up lakes, {counts['measurements']} made-up measurements, {counts['scores']} scores")
    print("  Nothing in this file was measured from a satellite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
