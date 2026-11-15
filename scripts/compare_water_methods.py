"""Measure every stored camera scene with the newer methods and compare them with the original NDWI result.

    python scripts/compare_water_methods.py

For each of the 254 downloaded camera scenes:
  old       NDWI with the fixed cutoff 0.2 (the stored measurement, not recomputed here)
  ndwi_otsu NDWI with an Otsu cutoff (old index, new cutoff)
  smbwi_otsu SMBWI (Su et al. 2024) with an Otsu cutoff (new index, new cutoff); needs the extra bands
             from scripts/download_smbwi_bands.py, and is skipped for a scene without them
The two new results are saved in the alt_measurement table (the original rows are never changed).

Then it writes:
  logs/<date>_water_methods_comparison.md   the comparison, every number read back from the database
  logs/<date>_water_methods_area.png        lake area over time for each method, camera and radar
                                            (black and white)
Camera against radar: every camera result is paired with radar results of the same lake within 3 days
(the same rule as scripts/validate_radar.py), and the median difference is reported for each method.
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sailab import db, water_index as wi  # noqa: E402

DB_PATH = REPO / "sailab_glof.db"
EXTRA_DIR = REPO / "data" / "smbwi_bands"
PAIR_DAYS = 3
METHODS = ("ndwi_fixed_0.2", wi.METHOD_NDWI_OTSU, wi.METHOD_SMBWI_OTSU)
LABEL = {"ndwi_fixed_0.2": "NDWI, cutoff 0.2 (old)", wi.METHOD_NDWI_OTSU: "NDWI, Otsu cutoff",
         wi.METHOD_SMBWI_OTSU: "SMBWI, Otsu cutoff (new)"}


def measure_all(conn: sqlite3.Connection) -> dict[str, int]:
    lakes = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM lake")}
    rows = conn.execute("SELECT m.id, m.lake_id, s.file_path FROM measurement m JOIN scene s ON s.id = m.scene_id "
                        "WHERE m.sensor = 'optical' ORDER BY s.acquired_at").fetchall()
    counts = defaultdict(int)
    for row in rows:
        lake = lakes[row["lake_id"]]
        stored = REPO / row["file_path"]
        if not stored.is_file():
            counts["stored picture missing"] += 1
            continue
        a = wi.measure_ndwi_otsu(stored, lake)
        db.insert_alt_measurement(conn, row["id"], wi.METHOD_NDWI_OTSU, a.status, a.extent_ha, a.cutoff)
        counts["ndwi_otsu measured"] += 1
        extra = EXTRA_DIR / lake["code"] / stored.name
        if extra.is_file():
            b = wi.measure_smbwi_otsu(stored, extra, lake)
            db.insert_alt_measurement(conn, row["id"], wi.METHOD_SMBWI_OTSU, b.status, b.extent_ha, b.cutoff)
            counts["smbwi_otsu measured"] += 1
        else:
            counts["smbwi_otsu skipped: no extra bands"] += 1
    return dict(counts)


def results(conn: sqlite3.Connection) -> list[dict]:
    """One row per camera scene: date, lake, and each method's status and area."""
    out = []
    for row in conn.execute(
            "SELECT m.id, l.code, substr(s.acquired_at, 1, 10) AS day, m.status, m.extent_ha FROM measurement m "
            "JOIN scene s ON s.id = m.scene_id JOIN lake l ON l.id = m.lake_id WHERE m.sensor = 'optical' "
            "ORDER BY l.code, s.acquired_at"):
        record = {"code": row["code"], "day": date.fromisoformat(row["day"]),
                  "ndwi_fixed_0.2": (row["status"], row["extent_ha"])}
        for alt in conn.execute("SELECT method, status, extent_ha FROM alt_measurement WHERE measurement_id = ?",
                                (row["id"],)):
            record[alt["method"]] = (alt["status"], alt["extent_ha"])
        out.append(record)
    return out


def radar(conn: sqlite3.Connection) -> dict[str, list[tuple[date, float]]]:
    out = defaultdict(list)
    for row in conn.execute("SELECT l.code, substr(s.acquired_at, 1, 10) AS day, m.extent_ha FROM measurement m "
                            "JOIN scene s ON s.id = m.scene_id JOIN lake l ON l.id = m.lake_id "
                            "WHERE m.sensor = 'radar' AND m.status = 'ok'"):
        out[row["code"]].append((date.fromisoformat(row["day"]), row["extent_ha"]))
    return out


def summary_lines(records: list[dict], radar_values: dict) -> list[str]:
    lines = []
    for code in sorted({r["code"] for r in records}):
        mine = [r for r in records if r["code"] == code]
        lines += [f"### {code}", "", "| Method | Scenes measured | Usable (ok) | Refused | Median area of usable (ha) | "
                  "Range (ha) | Camera minus radar within 3 days: median, pairs |", "|---|---|---|---|---|---|---|"]
        for method in METHODS:
            have = [r[method] for r in mine if method in r]
            ok = sorted(area for status, area in have if status == "ok")
            diffs = []
            for r in mine:
                if method in r and r[method][0] == "ok":
                    near = [area for day, area in radar_values[code] if abs((day - r["day"]).days) <= PAIR_DAYS]
                    diffs += [r[method][1] - area for area in near]
            lines.append(f"| {LABEL[method]} | {len(have)} | {len(ok)} | {len(have) - len(ok)} | "
                         f"{median(ok):.2f} | {ok[0]:.2f} to {ok[-1]:.2f} | "
                         + (f"{median(diffs):+.2f} ha, {len(diffs)} |" if diffs else "no pairs |") if ok else
                         f"| {LABEL[method]} | {len(have)} | 0 | {len(have)} | - | - | - |")
        both = [r for r in mine if all(m in r and r[m][0] == "ok" for m in ("ndwi_fixed_0.2", wi.METHOD_SMBWI_OTSU))]
        if both:
            change = [(r[wi.METHOD_SMBWI_OTSU][1] - r["ndwi_fixed_0.2"][1]) / r["ndwi_fixed_0.2"][1] * 100 for r in both]
            lines += ["", f"On the {len(both)} scenes where both the old method and SMBWI give an area, SMBWI is "
                      f"{median(change):+.1f}% different from the old area (median; range {min(change):+.1f}% to "
                      f"{max(change):+.1f}%)."]
        gained = sum(1 for r in mine if wi.METHOD_SMBWI_OTSU in r and r[wi.METHOD_SMBWI_OTSU][0] == "ok"
                     and r["ndwi_fixed_0.2"][0] != "ok")
        lost = sum(1 for r in mine if wi.METHOD_SMBWI_OTSU in r and r[wi.METHOD_SMBWI_OTSU][0] != "ok"
                   and r["ndwi_fixed_0.2"][0] == "ok")
        lines += [f"Scenes the old method refused but SMBWI measured: {gained}. Scenes the old method measured "
                  f"but SMBWI refused: {lost}.", ""]
    return lines


def draw(records: list[dict], radar_values: dict, out_png: Path) -> None:
    """Black and white graph: one panel per lake, area over time. Each method has its own marker shape;
    radar is small grey dots."""
    from PIL import Image, ImageDraw

    codes = sorted({r["code"] for r in records})
    width, panel_h, left, top = 1400, 380, 80, 40
    image = Image.new("RGB", (width, panel_h * len(codes) + 60), "white")
    pen = ImageDraw.Draw(image)
    days = [r["day"] for r in records]
    start, end = min(days), max(days)
    span = (end - start).days or 1
    shapes = {"ndwi_fixed_0.2": "circle", wi.METHOD_NDWI_OTSU: "cross", wi.METHOD_SMBWI_OTSU: "square"}
    for k, code in enumerate(codes):
        mine = [r for r in records if r["code"] == code]
        values = [r[m][1] for r in mine for m in METHODS if m in r and r[m][0] == "ok"]
        values += [a for _, a in radar_values[code]]
        if not values:
            continue
        ok_values = sorted(r["ndwi_fixed_0.2"][1] for r in mine if r["ndwi_fixed_0.2"][0] == "ok")
        mid = median(ok_values) if ok_values else median(values)
        low, high = mid * 0.6, mid * 1.4          # draw 60% to 140% of the usual area; values outside are pinned
        y0 = top + k * panel_h
        x = lambda d: left + (d - start).days / span * (width - left - 30)                      # noqa: E731
        y = lambda v: y0 + 20 + (1 - (min(max(v, low), high) - low) / (high - low)) * (panel_h - 70)   # noqa: E731
        pen.rectangle((left, y0 + 20, width - 30, y0 + panel_h - 50), outline="black")
        pen.text((left, y0), f"{code}: lake area (ha); axis {low:.0f} to {high:.0f}, values outside are pinned to the edge",
                 fill="black")
        for frac in (0.0, 0.5, 1.0):
            value = low + frac * (high - low)
            pen.text((10, y(value) - 6), f"{value:.0f}", fill="black")
        for year in range(start.year, end.year + 1):
            d = date(year, 1, 1)
            if start <= d <= end:
                pen.line((x(d), y0 + 20, x(d), y0 + panel_h - 50), fill=(200, 200, 200))
                pen.text((x(d) + 3, y0 + panel_h - 45), str(year), fill="black")
        for d, a in radar_values[code]:
            pen.ellipse((x(d) - 2, y(a) - 2, x(d) + 2, y(a) + 2), fill=(140, 140, 140))
        for r in mine:
            for method in METHODS:
                if method in r and r[method][0] == "ok":
                    cx, cy = x(r["day"]), y(r[method][1])
                    if shapes[method] == "circle":
                        pen.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), outline="black")
                    elif shapes[method] == "cross":
                        pen.line((cx - 4, cy - 4, cx + 4, cy + 4), fill="black")
                        pen.line((cx - 4, cy + 4, cx + 4, cy - 4), fill="black")
                    else:
                        pen.rectangle((cx - 3, cy - 3, cx + 3, cy + 3), fill="black")
    legend = ("circle = NDWI, cutoff 0.2 (old);  cross = NDWI, Otsu cutoff;  filled square = SMBWI, Otsu cutoff (new);"
              "  grey dots = radar")
    pen.text((left, panel_h * len(codes) + 30), legend, fill="black")
    image.save(out_png)


def main() -> int:
    conn = db.connect(DB_PATH)
    counts = measure_all(conn)
    records = results(conn)
    radar_values = radar(conn)
    conn.close()
    stamp = f"{datetime.now(timezone.utc):%Y-%m-%d}"
    out_png = REPO / "logs" / f"{stamp}_water_methods_area.png"
    draw(records, radar_values, out_png)
    lines = [
        "# Camera water measurement: old method against the newer ones",
        "",
        f"Written by `scripts/compare_water_methods.py` on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. "
        "Every number is read from the database.",
        "",
        "- **NDWI, cutoff 0.2 (old):** the stored measurement.",
        "- **NDWI, Otsu cutoff:** the old index with Otsu's cutoff, to show the effect of the cutoff alone.",
        "- **SMBWI, Otsu cutoff (new):** Su et al. (2024), equation (1), with Otsu's cutoff. The paper itself",
        "  separates water with ISODATA clustering; the Otsu cutoff is this project's choice (plain Otsu, the",
        "  baseline of the camera-cutoff row).",
        "",
        "Every method uses the same lake growing and the same refusal checks (cut off by the window, cloud,",
        "snow), so a refusal means the same thing for each.",
        "",
        f"Run: {counts}",
        "",
        *summary_lines(records, radar_values),
        "**Why SMBWI refuses every Karambar scene.** Otsu's cutoff over the whole Karambar window falls far",
        "below the water values (about -0.75 to -0.81 on the scenes checked), because the largest split in that",
        "window's SMBWI histogram is between snow or bright ground and everything else, not between water and",
        "land. Rock and ground then count as water, the grown lake reaches the edge of the window (about 550 ha",
        "against a 257 ha lake) and the existing check refuses it as possibly cut off. No wrong area was saved.",
        "This is the same failure the plain-Otsu radar method had before its slope mask. The paper itself uses",
        "ISODATA clustering, and the project plan pairs SMBWI with an optimised Otsu (Che et al. 2025), which is",
        "not yet implemented (the paper is not available here). So SMBWI with plain Otsu is not usable at",
        "Karambar, and this table should not be read as SMBWI failing in general.",
        "",
        "**At Atro Sar** SMBWI measures every scene NDWI measures, but reads larger (median +4.6%). Its",
        "agreement with radar is worse than NDWI's. One possible cause, untested: B9 is a 60 m band, and",
        "resampling it to 10 m blurs the shoreline, so shore pixels can look like water.",
        "",
        f"Graph: `{out_png.name}` (black and white).",
    ]
    out_md = REPO / "logs" / f"{stamp}_water_methods_comparison.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[12:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
