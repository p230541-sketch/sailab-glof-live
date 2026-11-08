"""True-colour picture of a stored Sentinel-2 window, with the measured lake region drawn on top.

The region is recomputed from the stored file with the same unchanged functions the pipeline used
(classify_water_ndwi, region_grow), so the outline is what produced the stored area. The pixel count is
returned so the page can show that it matches the stored measurement.
"""
from __future__ import annotations

from math import floor
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

from sailab.measurement import Pixel, classify_water_ndwi, region_grow
from sailab.pipeline import lake_centre_in_pixels

REGION_RGB = (255, 196, 0)       # outline colour: stands out against water, rock and snow


def render_scene_png(tif_path: Path, lake: Mapping[str, Any], out_path: Path) -> int:
    """Write the PNG and return the number of pixels in the recomputed lake region."""
    import rasterio

    with rasterio.open(tif_path) as src:
        b2, b3, b4, b8 = (src.read(i).astype(float) for i in (1, 2, 3, 4))
        pixel_size_m = float(src.res[0])
    rows, cols = b3.shape
    row_f, col_f = lake_centre_in_pixels(tif_path, lake["centre_lon"], lake["centre_lat"])
    is_water = {Pixel(r, c): classify_water_ndwi(b3[r, c], b8[r, c]) for r in range(rows) for c in range(cols)}
    region = region_grow(is_water, Pixel(floor(row_f), floor(col_f)), (row_f * pixel_size_m, col_f * pixel_size_m),
                         pixel_size_m, float(lake["growth_distance_limit_m"]))

    rgb = np.clip(np.stack([b4, b3, b2], axis=-1) / 3000.0, 0, 1) ** 0.6 * 255
    inside = np.zeros((rows, cols), dtype=bool)
    for p in region:
        inside[p.row, p.col] = True
    edge = inside & ~(np.roll(inside, 1, 0) & np.roll(inside, -1, 0) & np.roll(inside, 1, 1) & np.roll(inside, -1, 1))
    rgb[edge] = REGION_RGB
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(rgb.astype(np.uint8))
    scale = max(1, 480 // max(rows, cols))
    image.resize((cols * scale, rows * scale), Image.NEAREST).save(out_path)
    return len(region)
