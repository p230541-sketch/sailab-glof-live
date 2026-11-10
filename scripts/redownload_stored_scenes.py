"""Download again every picture the database already knows, onto this machine.

Why: the backfill pictures (2023 to 2026) were downloaded on another machine and are git-ignored, so a
new machine has the measurements but not the pictures. Comparing an old method with a new one "on the
same data" needs the pictures themselves.

What it does, for every row in the `scene` table that was really downloaded (not the too-cloudy ones):
  1. If the file is already here, leave it. Otherwise download the same lake window from Earth Engine.
  2. Work out the file's SHA-256 (a fingerprint of the file) and compare it with the fingerprint the
     original run wrote in logs/runs/. Same fingerprint = the very same file, byte for byte.

It never writes to the database. Safe to stop and start again: files already here are skipped.

    python scripts/redownload_stored_scenes.py            # everything
    python scripts/redownload_stored_scenes.py --limit 4  # a quick try with 4 files
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from sailab.pipeline import NOT_DOWNLOADED_PREFIX, sha256_of  # noqa: E402

DB_PATH = REPO / "sailab_glof.db"
RUN_LOG_DIR = REPO / "logs" / "runs"
CHECKSUM_LINE = re.compile(r"downloaded (\S+) sha256=([0-9a-f]{64})")
ATTEMPTS = 3

log = logging.getLogger("redownload")


def expected_checksums(run_log_dir: Path) -> dict[str, str]:
    """{stored file path: sha256} from every run log. Logs are read oldest first, so when a file was
    downloaded twice (the backfill was run again with a sixth band) the newest fingerprint wins."""
    found: dict[str, str] = {}
    for log_file in sorted(run_log_dir.glob("*.log")):
        for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
            match = CHECKSUM_LINE.search(line)
            if match:
                found[match.group(1).replace("\\", "/")] = match.group(2)
    return found


def stored_scenes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every scene that has a real file path, oldest first. Too-cloudy scenes were never downloaded."""
    return conn.execute(
        "SELECT s.id, s.lake_id, s.source, s.acquired_at, s.file_path FROM scene s "
        "WHERE s.file_path NOT LIKE ? ORDER BY s.lake_id, s.source, s.acquired_at",
        (NOT_DOWNLOADED_PREFIX + "%",),
    ).fetchall()


def verdict_for(actual_sha: str, expected_sha: str | None) -> str:
    if expected_sha is None:
        return "no fingerprint on record"
    return "same file" if actual_sha == expected_sha else "DIFFERENT file"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="stop after this many missing files (for a quick try)")
    args = parser.parse_args(argv)

    from datetime import datetime, timezone
    out_log = REPO / "logs" / f"{datetime.now(timezone.utc):%Y-%m-%d}_redownload_stored_scenes.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(out_log, encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    logging.getLogger("rasterio._env").setLevel(logging.ERROR)

    from scheduler import ENV_FILE, key_problem, load_env_file
    load_env_file(ENV_FILE)
    problem = key_problem()
    if problem:
        log.error(problem)
        return 2
    from sailab import earth_engine_client as client
    log.info("signed in to Earth Engine as %s", client.initialize())

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)   # read-only: this script never changes the database
    conn.row_factory = sqlite3.Row
    lakes = {row["id"]: row for row in conn.execute("SELECT * FROM lake")}
    scenes = stored_scenes(conn)
    expected = expected_checksums(RUN_LOG_DIR)
    log.info("%d stored scenes, %d fingerprints on record", len(scenes), len(expected))

    tally: Counter = Counter()
    fetched = 0
    for row in scenes:
        lake = lakes[row["lake_id"]]
        target = REPO / row["file_path"]
        if target.is_file():
            how = "already here"
        else:
            if args.limit is not None and fetched >= args.limit:
                tally["skipped (limit)"] += 1
                continue
            scene = client.SceneInfo(scene_id=target.stem, lake_code=lake["code"], acquired_at=row["acquired_at"],
                                     tile_cloud_percent=None, lake_cloud_percent=None, source=row["source"])
            download = client.download_s1_window if row["source"] == "sentinel-1" else client.download_scene_window
            error = None
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    download(scene, lake, target)
                    error = None
                    break
                except Exception as exc:   # one bad scene must not stop the other 695
                    error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    log.warning("%s attempt %d failed: %s", row["file_path"], attempt, error)
            if error:
                tally["FAILED"] += 1
                log.error("%s: gave up after %d attempts", row["file_path"], ATTEMPTS)
                continue
            fetched += 1
            how = "downloaded"
        verdict = verdict_for(sha256_of(target), expected.get(row["file_path"]))
        tally[f"{how}, {verdict}"] += 1
        if verdict != "same file":
            log.warning("%s: %s, %s", row["file_path"], how, verdict)
        elif how == "downloaded" and fetched % 25 == 0:
            log.info("%d downloaded so far (latest: %s)", fetched, row["file_path"])

    log.info("finished. Totals:")
    for key in sorted(tally):
        log.info("  %-45s %d", key, tally[key])
    bad = sum(count for key, count in tally.items() if "FAILED" in key or "DIFFERENT" in key)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
