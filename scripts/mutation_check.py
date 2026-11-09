"""Mutation check for the modules written in this build: break one line, run the whole test suite, put it back.

Run:   .venv/bin/python scripts/mutation_check.py [--only ID ...]

Same method as the original 6-module check (one deliberate, hand-chosen change at a time; a mutation is
"caught" if at least one test fails), but scripted so anyone can re-run it. Each mutation is an exact text
replacement that must match exactly once; the original file is restored afterwards (also on Ctrl-C).
Prints one line per mutation and a total. Exit code 1 if any mutation survived.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTEST = [str(REPO / ".venv" / "bin" / "python"), "-m", "pytest", "tests", "-x", "-q", "-p", "no:cacheprovider"]

# (id, file, original text, mutated text, what the mutation breaks)
MUTATIONS = [
    # radar.py
    ("R1", "sailab/radar.py", "steep = slope > slope_limit_deg", "steep = slope < slope_limit_deg", "slope mask inverted (keeps steep, drops flat)"),
    ("R2", "sailab/radar.py", "        usable &= ~steep\n", "        pass\n", "slope mask computed but never applied"),
    ("R3", "sailab/radar.py", "candidate = usable & (vv < threshold)", "candidate = usable & (vv > threshold)", "water = brighter than Otsu instead of darker"),
    ("R4", "sailab/radar.py", "/ ((right - left) * pixel_size_m)", "/ pixel_size_m", "x-gradient forgets the 2-cell spacing (slope overstated)"),
    ("R5", "sailab/radar.py", "degrees(atan(hypot(dzdx, dzdy)))", "degrees(atan(abs(dzdx)))", "slope ignores the north-south gradient"),
    ("R6", "sailab/radar.py", "    if touching:\n", "    if False:\n", "cut-off-by-no-data check removed"),
    ("R7", "sailab/radar.py", "    if not candidate[seed.row, seed.col]:\n", "    if False:\n", "centre-must-be-water check removed"),
    ("R8", "sailab/radar.py", "extent_area_m2(region, pixel_size_m) / 10_000", "extent_area_m2(region, pixel_size_m) / 1_000", "m² to ha conversion wrong"),
    # pipeline.py
    ("P1", "sailab/pipeline.py", "if record.observed_on < acquired_on]", "if record.observed_on <= acquired_on]", "same-day values leak into the baseline"),
    ("P2", "sailab/pipeline.py", "if len(same_month) < MIN_SAME_MONTH_VALUES or len(same_month_years)",
     "if len(same_month) < MIN_SAME_MONTH_VALUES and len(same_month_years)", "check F: 'or' weakened to 'and'"),
    ("P3", "sailab/pipeline.py", "if snow_share > SNOW_COVER_LIMIT:", "if snow_share > 2 * SNOW_COVER_LIMIT:", "check C: snow-cover limit doubled"),
    ("P4", "sailab/pipeline.py", "        if cloud_touching:\n", "        if False:\n", "check D (cloud touching the lake) removed"),
    ("P5", "sailab/pipeline.py", "\nSCORE_RADAR = False", "\nSCORE_RADAR = True", "radar risk scoring switched back on"),
    ("P6", "sailab/pipeline.py", "return date.fromisoformat(row[0][:10]) - timedelta(days=1)",
     "return date.fromisoformat(row[0][:10]) + timedelta(days=1)", "next search starts a day late (scenes missed)"),
    ("P7", "sailab/pipeline.py", "scene.scene_id}\"\n    if _already_recorded(conn, lake[\"id\"], scene.scene_id):\n",
     "scene.scene_id}\"\n    if False:\n", "duplicate optical scene not skipped"),
    ("P7b", "sailab/pipeline.py", "import measure_radar_scene\n\n    if _already_recorded(conn, lake[\"id\"], scene.scene_id):\n",
     "import measure_radar_scene\n\n    if False:\n", "duplicate radar scene not skipped"),
    ("P8", "sailab/pipeline.py", "sensor=sensor)\n               if record.observed_on", "sensor=None)\n               if record.observed_on",
     "baseline mixes optical and radar history"),
    ("P9", "sailab/pipeline.py", "if src.count < SCL_BAND_INDEX:", "if src.count < 0:", "missing-SCL-band guard removed"),
    # db.py
    ("D1", "sailab/db.py", "    if status == \"ok\" and extent_ha is None:\n", "    if False:\n", "'ok' allowed without an area"),
    ("D2", "sailab/db.py", "    if status == \"insufficient_observation\" and extent_ha is not None:\n", "    if False:\n",
     "refused measurement allowed to carry a number"),
    ("D3", "sailab/db.py", "WHERE m.lake_id = ? AND m.status = 'ok' AND", "WHERE m.lake_id = ? AND", "history includes refused measurements"),
    ("D4", "sailab/db.py", "(? IS NULL OR m.sensor = ?)", "(? IS NULL OR m.sensor = ? OR 1)", "sensor filter ignored in history"),
    ("D5", "sailab/db.py", "if row[\"id\"] != exclude_measurement_id", "if row[\"id\"] == exclude_measurement_id", "exclusion inverted"),
    ("D6", "sailab/db.py", "ORDER BY s.acquired_at, m.id", "ORDER BY s.acquired_at DESC, m.id", "history returned newest first"),
    ("D7", "sailab/db.py", "-90.0 <= centre_lat <= 90.0", "-180.0 <= centre_lat <= 180.0", "latitude range check widened"),
    ("D8", "sailab/db.py", "if existing[key] != value}", "if existing[key] != value and False}", "seed guard never refuses changed lake values"),
    # earth_engine_client.py
    ("E1", "sailab/earth_engine_client.py", "zone = int(floor((lon + 180.0) / 6.0)) + 1", "zone = int(floor((lon + 180.0) / 6.0))", "UTM zone off by one"),
    ("E2", "sailab/earth_engine_client.py", "(32600 if lat >= 0 else 32700)", "(32700 if lat >= 0 else 32600)", "UTM hemisphere swapped"),
    ("E3", "sailab/earth_engine_client.py", "valid = inside & (scl != SCL_NO_DATA)", "valid = inside", "no-data pixels counted as clear"),
    ("E4", "sailab/earth_engine_client.py", "return 100.0 * cloudy_count / valid_count", "return cloudy_count / valid_count", "cloud as a fraction, not a percent"),
    ("E5", "sailab/earth_engine_client.py", "return (since_date + timedelta(days=1)).isoformat(), (until_date + timedelta(days=1)).isoformat()",
     "return since_date.isoformat(), until_date.isoformat()", "date range shifted (re-lists old day, misses last day)"),
    ("E6", "sailab/earth_engine_client.py", "    if start >= end:\n        return []          # the whole period is already covered: genuinely",
     "    if start > end:\n        return []          # the whole period is already covered: genuinely", "empty optical date range sent to Earth Engine"),
    ("E7", "sailab/earth_engine_client.py", "CLOUD_SCL_CLASSES = (SCL_CLOUD_SHADOW, ", "CLOUD_SCL_CLASSES = (", "cloud shadow not counted as cloud"),
    ("E8", "sailab/earth_engine_client.py", "DOWNLOAD_BANDS = MANUAL_EXPORT_BANDS + (\"SCL\",)", "DOWNLOAD_BANDS = MANUAL_EXPORT_BANDS",
     "SCL band no longer downloaded"),
    ("E9", "sailab/earth_engine_client.py", "if src.crs is None or src.crs.to_epsg() != expected_epsg:", "if src.crs is None:",
     "downloaded file's projection not checked"),
]


def run(mutation) -> tuple[bool, str, float]:
    ident, rel, old, new, _ = mutation
    path = REPO / rel
    original = path.read_text()
    if original.count(old) != 1:
        raise SystemExit(f"{ident}: original text found {original.count(old)} times in {rel}; fix the mutation list")
    start = time.monotonic()
    try:
        path.write_text(original.replace(old, new))
        proc = subprocess.run(PYTEST, cwd=REPO, capture_output=True, text=True)
    finally:
        path.write_text(original)
    first_fail = next((l for l in proc.stdout.splitlines() if l.startswith(("FAILED", "ERROR"))), proc.stdout.strip().splitlines()[-1])
    return proc.returncode != 0, first_fail, time.monotonic() - start


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    chosen = [m for m in MUTATIONS if not args.only or m[0] in args.only]
    for ident, rel, old, _, _ in chosen:          # check every mutation applies exactly once BEFORE running any
        found = (REPO / rel).read_text().count(old)
        if found != 1:
            print(f"{ident}: original text found {found} times in {rel}; fix the mutation list")
            return 2
    baseline = subprocess.run(PYTEST, cwd=REPO, capture_output=True, text=True)
    print(f"baseline (no mutation): {baseline.stdout.strip().splitlines()[-1]}")
    if baseline.returncode != 0:
        print("the unmutated suite does not pass; stopping")
        return 2
    survived = []
    for m in chosen:
        caught, detail, secs = run(m)
        print(f"{m[0]:3} {'CAUGHT  ' if caught else 'SURVIVED'} {m[1]:32} {m[4]}  ({secs:.0f}s)\n      {detail}")
        if not caught:
            survived.append(m[0])
    print(f"\n{len(chosen) - len(survived)} of {len(chosen)} mutations caught." + (f" Survived: {', '.join(survived)}" if survived else ""))
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
