"""Check our hand-written slope code against two independent references, on the real DEM windows.

Run:   .venv/bin/python scripts/check_slope_reference.py          (reference B needs Earth Engine + internet)

The radar slope mask drops pixels steeper than 10 degrees, using sailab.radar.slope_degrees on the stored
Copernicus DEM window (data/dem/<code>_dem.tif, 30 m DEM resampled to the 10 m lake grid).

Reference A, numpy.gradient: numpy's own central-difference gradient (one-sided at the edges) on the same
  file. Same formula, independent implementation: any coding mistake in ours would show as a difference.
Reference B, Earth Engine ee.Terrain.slope: Google's slope algorithm, computed by Earth Engine on the
  NATIVE 30 m DEM and then resampled to the same 10 m grid. Different algorithm and different order
  (slope-then-resample vs resample-then-slope), so values will not match exactly; what matters for the
  mask is whether the two put the same pixels on the same side of 10 degrees.

What this cannot check: whether 10 degrees is the RIGHT limit. That needs ground truth (a surveyed
shoreline or a high-resolution lake outline for a dated radar pass), which this project does not have.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sailab import db, earth_engine_client as eec  # noqa: E402
from sailab.radar import load_slope  # noqa: E402

LIMIT = 10.0


def numpy_slope(dem_path: Path) -> np.ndarray:
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(float)
        px = float(src.res[0])
    dem[~np.isfinite(dem)] = np.nan
    gy, gx = np.gradient(dem, px)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def ee_slope(lake, out: Path) -> np.ndarray:
    import ee
    import requests

    tiles = ee.ImageCollection(eec.DEM_COLLECTION).select("DEM")
    dem = tiles.mosaic().setDefaultProjection(tiles.first().projection())
    slope = ee.Terrain.slope(dem).resample("bilinear").toFloat()
    region = eec.export_region(lake)
    params = {**eec.download_params(lake, region), "bands": ["slope"]}
    response = requests.get(slope.clip(region).getDownloadURL(params), timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    out.write_bytes(response.content)
    with rasterio.open(out) as src:
        return src.read(1).astype(float)


def compare(name: str, ours: np.ndarray, ref: np.ndarray) -> None:
    both = np.isfinite(ours) & np.isfinite(ref)
    diff = np.abs(ours[both] - ref[both])
    same_side = ((ours[both] > LIMIT) == (ref[both] > LIMIT))
    print(f"  {name}: {both.sum()} pixels compared; |difference| median {np.median(diff):.4f} deg, "
          f"95th pct {np.percentile(diff, 95):.4f}, max {diff.max():.4f}")
    print(f"    same side of {LIMIT:.0f} deg: {same_side.mean():.2%} of pixels "
          f"(ours steep {np.mean(ours[both] > LIMIT):.1%}, reference steep {np.mean(ref[both] > LIMIT):.1%})")


def main() -> int:
    print(f"checked {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    conn = db.connect(REPO / "sailab_glof.db")
    lakes = {row["code"]: dict(row) for row in db.get_lakes(conn)}
    use_ee = "--no-ee" not in sys.argv
    if use_ee:
        print(f"Earth Engine: signed in as {eec.initialize()}")
    for code, lake in lakes.items():
        dem_path = REPO / "data" / "dem" / f"{code}_dem.tif"
        sha = hashlib.sha256(dem_path.read_bytes()).hexdigest()[:16]
        ours = load_slope(dem_path)
        print(f"\n{code}: {dem_path.relative_to(REPO)} (sha256 {sha}…), grid {ours.shape}")
        compare("A numpy.gradient (same file)", ours, numpy_slope(dem_path))
        if use_ee:
            out = Path(tempfile.mkdtemp(prefix="sailab_ee_slope_")) / f"{code}_ee_slope.tif"
            ref = ee_slope(lake, out)
            if ref.shape != ours.shape:
                print(f"  B Earth Engine: grid {ref.shape} differs from ours {ours.shape}; not compared")
                continue
            compare("B Earth Engine ee.Terrain.slope (30 m, then resampled)", ours, ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())
