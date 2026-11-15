"""Download every stored radar pass again in linear power, clean it (sailab/s1_clean.py, after Mullissa et al.
2021) and save the cleaned window.

    python scripts/clean_radar.py            # every stored radar pass
    python scripts/clean_radar.py --limit 3  # a quick try

  data/s1_float/<lake>/<scene>.tif   linear power VV, VH and the incidence angle (from COPERNICUS/S1_GRD_FLOAT)
  data/s1_clean/<lake>/<scene>.tif   after border noise removal, Refined Lee and terrain correction: VV, VH in dB
Both folders are git-ignored (re-downloadable). Each download is checked to sit on the same grid as the stored
radar window and its height map. Files already there are skipped. The database is opened read-only.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from sailab import s1_clean  # noqa: E402
from sailab.pipeline import sha256_of  # noqa: E402

DB_PATH = REPO / "sailab_glof.db"
FLOAT_DIR = REPO / "data" / "s1_float"
CLEAN_DIR = REPO / "data" / "s1_clean"
ATTEMPTS = 3

log = logging.getLogger("clean_radar")


def write_clean(float_path: Path, dem_path: Path, out_path: Path) -> tuple[float, float]:
    """Clean one downloaded window and write VV, VH (dB). Returns (heading used, share of pixels kept)."""
    import rasterio

    with rasterio.open(float_path) as src:
        vv, vh, angle = (src.read(i).astype(float) for i in (1, 2, 3))
        heading = float(src.tags()["HEADING_DEG"])     # worked out over the whole scene at download
        profile = src.profile
        pixel_size_m = float(src.res[0])
    with rasterio.open(dem_path) as d:
        dem = d.read(1).astype(float)
    if dem.shape != vv.shape:
        raise ValueError(f"height map {dem.shape} is not on the radar grid {vv.shape}")
    for band in (vv, vh, angle):
        band[(band == 0) | ~np.isfinite(band)] = np.nan   # Earth Engine writes 0 (or -inf for angle) where no data
    vv_db, vh_db, heading = s1_clean.clean(vv, vh, angle, dem, pixel_size_m, heading)
    profile.update(count=2, dtype="float32", nodata=np.nan)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(vv_db.astype("float32"), 1)
        dst.write(vh_db.astype("float32"), 2)
        dst.set_band_description(1, "VV")
        dst.set_band_description(2, "VH")
    kept = float(np.isfinite(vv_db).sum()) / max(int(np.isfinite(vv).sum()), 1)
    return heading, kept


def same_grid(path_a: Path, path_b: Path) -> bool:
    import rasterio

    with rasterio.open(path_a) as a, rasterio.open(path_b) as b:
        return (a.width, a.height, a.crs, a.transform) == (b.width, b.height, b.crs, b.transform)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    out_log = REPO / "logs" / f"{datetime.now(timezone.utc):%Y-%m-%d}_clean_radar.log"
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
    scenes = conn.execute("SELECT lake_id, acquired_at, file_path FROM scene WHERE source = 'sentinel-1' "
                          "ORDER BY lake_id, acquired_at").fetchall()
    log.info("%d stored radar passes", len(scenes))
    tally: Counter = Counter()
    fetched = 0
    for row in scenes:
        lake = lakes[row["lake_id"]]
        stored = REPO / row["file_path"]
        name = Path(row["file_path"]).name
        float_path = FLOAT_DIR / lake["code"] / name
        clean_path = CLEAN_DIR / lake["code"] / name
        dem_path = REPO / "data" / "dem" / f"{lake['code']}_dem.tif"
        if not float_path.is_file():
            if args.limit is not None and fetched >= args.limit:
                tally["skipped (limit)"] += 1
                continue
            scene = client.SceneInfo(scene_id=Path(name).stem, lake_code=lake["code"], acquired_at=row["acquired_at"],
                                     tile_cloud_percent=None, lake_cloud_percent=None, source="sentinel-1")
            error = None
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    client.download_s1_float_window(scene, lake, float_path)
                    error = None
                    break
                except Exception as exc:
                    error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    log.warning("%s attempt %d failed: %s", name, attempt, error)
            if error:
                tally["FAILED download"] += 1
                continue
            fetched += 1
            log.info("%s %s: downloaded sha256=%s", lake["code"], name, sha256_of(float_path))
        if stored.is_file() and not same_grid(stored, float_path):
            tally["DIFFERENT grid"] += 1
            log.error("%s: not on the same grid as %s", float_path, stored)
            continue
        if not clean_path.is_file():
            try:
                heading, kept = write_clean(float_path, dem_path, clean_path)
                log.info("%s %s: cleaned, heading %.1f, %.0f%% of pixels kept", lake["code"], name, heading, kept * 100)
            except Exception as exc:
                tally["FAILED cleaning"] += 1
                log.error("%s: cleaning failed: %s: %s", name, type(exc).__name__, exc)
                continue
        tally["cleaned"] += 1
    log.info("finished. Totals:")
    for key in sorted(tally):
        log.info("  %-30s %d", key, tally[key])
    return 1 if any(k.startswith(("FAILED", "DIFFERENT")) for k in tally) else 0


if __name__ == "__main__":
    raise SystemExit(main())
