# Original export pattern, recovered from the original GeoTIFFs (2026-11-08)

The Code Editor export script itself was not found on this machine. The pattern below is read
from the GeoTIFF tags of the files the real results were computed from:
~/Documents/FYP/otherMaterial (SOURCES)/SailAb_GLOF_PROOF_Package/03_Real_Data_Files_You_Uploaded/

| File | CRS | Pixel | Size (cols x rows) | Top-left (E, N) | Bands | Type |
|---|---|---|---|---|---|---|
| KarambarLake_Sentinel2_RAW.tif | EPSG:32643 | 10 m | 505 x 507 | 382100, 4084970 | B2,B3,B4,B8,B11 | uint16, LZW |
| AtroSar_Sentinel2_RAW.tif      | EPSG:32643 | 10 m | 163 x 163 | 378540, 4057110 | B2,B3,B4,B8,B11 | uint16, LZW |

Seeded centre projected to EPSG:32643 by Earth Engine:
- KRB (73.7053229, 36.880833) -> (384622.4, 4082435.3): centre sits at col 252.24 / row 253.47; window middle is 252.5 / 253.5
- ATS (73.65037, 36.64458)    -> (379355.4, 4056293.8): centre sits at col 81.54 / row 81.62; window middle is 81.5 / 81.5

Conclusion: each original window is the bounding box of a circle of boundary_radius_m
(2500 m / 800 m) around the exact seeded coordinate, snapped outward to the 10 m grid,
in EPSG:32643, 10 m pixels, bands B2 B3 B4 B8 B11. Both centres agree with the window
middle to within 0.3 pixel.
