"""Download the four extra bands SMBWI needs (B8A, B9, B11, B12) for every clear camera scene already stored.

    python scripts/download_smbwi_bands.py            # every stored optical scene
    python scripts/download_smbwi_bands.py --limit 3  # a quick try

The files go to data/smbwi_bands/<lake>/<scene id>.tif (git-ignored, like data/backfill/). Each one is
checked to sit on exactly the same pixel grid as its stored picture (same size, same position), so the
two can be combined pixel by pixel. Files already there are skipped, so it is safe to stop and restart.
The database is opened read-only. Each file's SHA-256 is written to the log.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from sailab.pipeline import NOT_DOWNLOADED_PREFIX, sha256_of  # noqa: E402

DB_PATH = REPO / "sailab_glof.db"
OUT_DIR = REPO / "data" / "smbwi_bands"
ATTEMPTS = 3

log = logging.getLogger("smbwi_bands")


def smbwi_path(stored_file_path: str, lake_code: str) -> Path:
    """Where the extra-band file of a stored picture lives."""
    return OUT_DIR / lake_code / Path(stored_file_path).name


def same_grid(path_a: Path, path_b: Path) -> bool:
    """True when two GeoTIFFs have the same size, projection and pixel position."""
    import rasterio

    with rasterio.open(path_a) as a, rasterio.open(path_b) as b:
        return (a.width, a.height, a.crs, a.transform) == (b.width, b.height, b.crs, b.transform)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    out_log = REPO / "logs" / f"{datetime.now(timezone.utc):%Y-%m-%d}_download_smbwi_bands.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(out_log, encoding="utf-8"), logging.StreamHandler(sys.stdout)])
    logging.getLogger("rasterio._env").setLevel(logging.ERROR)

    from scheduler import ENV_FILE, key_problem, load_env_file
    load_env_file(ENV_FILE)
    if key_problem():
        log.error(key_problem())
        return 2
    from sailab import earth_engine_client as client
    log.info("signed in to Earth Engine as %s", client.initialize())

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    lakes = {row["id"]: row for row in conn.execute("SELECT * FROM lake")}
    scenes = conn.execute("SELECT lake_id, acquired_at, file_path FROM scene WHERE source = 'sentinel-2' "
                          "AND file_path NOT LIKE ? ORDER BY lake_id, acquired_at", (NOT_DOWNLOADED_PREFIX + "%",)).fetchall()
    log.info("%d stored optical scenes", len(scenes))
    tally: Counter = Counter()
    fetched = 0
    for row in scenes:
        lake = lakes[row["lake_id"]]
        stored = REPO / row["file_path"]
        target = smbwi_path(row["file_path"], lake["code"])
        if not target.is_file():
            if args.limit is not None and fetched >= args.limit:
                tally["skipped (limit)"] += 1
                continue
            scene = client.SceneInfo(scene_id=target.stem, lake_code=lake["code"], acquired_at=row["acquired_at"],
                                     tile_cloud_percent=None, lake_cloud_percent=None)
            error = None
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    client.download_smbwi_bands(scene, lake, target)
                    error = None
                    break
                except Exception as exc:
                    error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    log.warning("%s attempt %d failed: %s", target.name, attempt, error)
            if error:
                tally["FAILED"] += 1
                continue
            fetched += 1
            log.info("%s %s: downloaded sha256=%s", lake["code"], target.name, sha256_of(target))
        if not stored.is_file():
            tally["stored picture missing, grid not checked"] += 1
        elif same_grid(stored, target):
            tally["same grid as the stored picture"] += 1
        else:
            tally["DIFFERENT grid"] += 1
            log.error("%s: not on the same grid as %s", target, stored)
    log.info("finished. Totals:")
    for key in sorted(tally):
        log.info("  %-45s %d", key, tally[key])
    return 1 if tally["FAILED"] or tally["DIFFERENT grid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
