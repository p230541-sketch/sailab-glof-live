"""Wires Acquisition -> Measurement -> Risk Scoring into one automatic run.

Scope of this build (agreed): optical only. When choose_sensor() picks radar for
a scene (too cloudy over the lake), the scene is still recorded in the `scene`
table, so the history shows it existed and why it was skipped, but it is not
downloaded or measured, and no number is invented for it.

Every stage uses the already-tested functions unchanged:
  choose_sensor, ResumableRun      (acquisition.py)
  classify_water_ndwi, region_grow, extent_area_m2  (measurement.py)
  score_against_seasonal_baseline  (risk.py)
"""
from __future__ import annotations

import hashlib
import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from math import floor
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from sailab import db
from sailab.acquisition import ResumableRun, RunLog, choose_sensor
from sailab.measurement import Pixel, classify_water_ndwi, extent_area_m2, region_grow
from sailab.risk import score_against_seasonal_baseline

log = logging.getLogger("sailab.pipeline")

GREEN_BAND_INDEX = 2   # 1-based rasterio band numbers in B2, B3, B4, B8, B11, SCL order: B3 = green
NIR_BAND_INDEX = 4     # B8 = near-infrared
SCL_BAND_INDEX = 6     # Sentinel-2 scene classification, added to downloads on 2026-11-08

# Checks C and D (added 2026-11-08, agreed with the project owner after the backfill outliers in
# logs/2026-11-08_backfill_outliers_true_colour_vs_detected.png): SCL classes that make a measurement
# untrustworthy when they touch the detected lake. These only ever REJECT a measurement; a wrong SCL
# label can make the pipeline more cautious, never produce a false area.
SCL_SNOW_ICE = 11
SCL_CLOUD_CLASSES = (3, 8, 9, 10)          # cloud shadow, cloud medium/high probability, thin cirrus
SNOW_COVER_LIMIT = 0.5                     # check C: more than half the lake circle snow/ice = frozen/snowed in

# Check F (added 2026-11-08): no risk score unless the scene's calendar month already has at least
# this many earlier usable measurements, from at least this many different years. With 2-3 values the
# spread is tiny and a modest change gave scores like -49 in the first backfill.
MIN_SAME_MONTH_VALUES = 5
MIN_SAME_MONTH_YEARS = 2
NOT_DOWNLOADED_PREFIX = "not_downloaded/"   # scene.file_path for scenes skipped as too cloudy for optical
RISK_STATUS_FROM_RISK_MODULE = {"ok": "ok", "insufficient history": "insufficient_history"}

# Cloud over the lake above this -> not measured optically. Passed to the unchanged choose_sensor(), whose
# own default (50%) is the test limit from TC-ACQ-06. Set to 10% on 2026-11-08, agreed with the project
# owner, after the August 2026 smoke test: scenes with 28.8% and 34.7% lake cloud under-measured the lakes
# (Atro Sar 87.0 ha vs ~106; Karambar 79.65 ha vs ~256), while clear scenes were 0-7%. Based on one month
# of data, so a judgement call, not a calibrated value. Evidence: logs/2026-11-08_step5_smoke_test_aug2026.log
OPTICAL_CLOUD_LIMIT_PERCENT = 10.0


@dataclass
class MeasurementOutcome:
    status: str                 # 'ok' or 'insufficient_observation'
    extent_ha: float | None
    reason: str                 # human-readable, written to the run log


@dataclass
class RunResult:
    run_id: int
    lakes_processed: int = 0
    scenes_recorded: int = 0
    scenes_downloaded: int = 0
    measurements: int = 0
    risk_scores: int = 0
    errors: str | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Measurement on a real downloaded GeoTIFF
# ---------------------------------------------------------------------------
def lake_centre_in_pixels(path: str | Path, lon: float, lat: float) -> tuple[float, float]:
    """Fractional (row, col) of a lon/lat inside a GeoTIFF, from the file's own georeferencing.

    This replaces the manual tests' shortcut (centre = rows//2, cols//2), which
    only worked because those exports happened to be centred on the lake.
    """
    import rasterio
    from rasterio.warp import transform as warp_transform

    with rasterio.open(path) as src:
        xs, ys = warp_transform("EPSG:4326", src.crs, [lon], [lat])
        col, row = ~src.transform @ (xs[0], ys[0])
    return row, col


def measure_scene(path: str | Path, lake: Mapping[str, Any], cutoff: float = 0.2,
                  scl_checks: bool = True) -> MeasurementOutcome:
    """NDWI per pixel -> water map -> region grown from the lake centre -> area.

    Returns 'insufficient_observation' (never a zero) when:
      - the lake centre falls outside the downloaded window;
      - the centre pixel itself is not water (or has no data), since growing
        from a non-water seed would report a 1-pixel "lake";
      - the grown lake touches a no-data pixel, since the lake may continue
        into the missing area and would be measured too small without warning;
      - (check D) cloud or cloud shadow touches the grown lake: part of it may be hidden;
      - (check C) snow/ice touches the grown lake (it may have leaked into snow, or the
        lake may be partly frozen), or covers more than half of the lake circle.

    scl_checks=False is only for the project's original 5-band manual exports, which have
    no SCL band; any file the pipeline downloads has it, and a missing band is an error.

    No-data pixels elsewhere are expected and harmless: the export's
    .bounds() rectangle is drawn in lat/lon, so clipping to it leaves a thin
    zero border (up to 6 px, measured on the original Karambar file) along
    the edges of the UTM window.
    """
    import rasterio

    with rasterio.open(path) as src:
        green = src.read(GREEN_BAND_INDEX).astype(float)
        nir = src.read(NIR_BAND_INDEX).astype(float)
        pixel_size_m = float(src.res[0])
        if scl_checks:
            if src.count < SCL_BAND_INDEX:
                raise ValueError(f"{path} has {src.count} bands, no SCL band: cannot run the cloud and snow checks")
            scl = src.read(SCL_BAND_INDEX)
    rows, cols = green.shape
    row_f, col_f = lake_centre_in_pixels(path, lake["centre_lon"], lake["centre_lat"])
    seed = Pixel(floor(row_f), floor(col_f))

    if not (0 <= seed.row < rows and 0 <= seed.col < cols):
        return MeasurementOutcome("insufficient_observation", None, f"lake centre {seed} is outside the {cols}x{rows} window")
    no_data = (green == 0) & (nir == 0)

    is_water = {Pixel(r, c): classify_water_ndwi(green[r, c], nir[r, c], cutoff) for r in range(rows) for c in range(cols)}
    if not is_water[seed]:
        return MeasurementOutcome("insufficient_observation", None, f"centre pixel {seed} is not water (NDWI <= {cutoff})")

    region = region_grow(is_water, seed, (row_f * pixel_size_m, col_f * pixel_size_m), pixel_size_m,
                         float(lake["growth_distance_limit_m"]))
    touching = _pixels_touching(region, no_data)
    if touching:
        return MeasurementOutcome("insufficient_observation", None,
                                  f"lake region ({len(region)} px) borders {touching} no-data pixels; it may be cut off")
    if scl_checks:
        cloud_touching = _pixels_touching(region, np.isin(scl, SCL_CLOUD_CLASSES))
        if cloud_touching:
            return MeasurementOutcome("insufficient_observation", None,
                                      f"check D: lake region ({len(region)} px) borders {cloud_touching} cloud/shadow pixels")
        snow = scl == SCL_SNOW_ICE
        snow_touching = _pixels_touching(region, snow)
        if snow_touching:
            return MeasurementOutcome("insufficient_observation", None,
                                      f"check C: lake region ({len(region)} px) borders {snow_touching} snow/ice pixels")
        circle = _inside_circle(rows, cols, row_f, col_f, float(lake["boundary_radius_m"]) / pixel_size_m) & (scl != 0)
        snow_share = float((snow & circle).sum()) / max(int(circle.sum()), 1)
        if snow_share > SNOW_COVER_LIMIT:
            return MeasurementOutcome("insufficient_observation", None,
                                      f"check C: {snow_share:.0%} of the lake circle is snow/ice (limit {SNOW_COVER_LIMIT:.0%})")
    extent_ha = extent_area_m2(region, pixel_size_m) / 10_000
    return MeasurementOutcome("ok", extent_ha, f"{len(region)} water pixels connected to the centre")


def _inside_circle(rows: int, cols: int, centre_row: float, centre_col: float, radius_px: float):
    """True for pixels whose centre lies within radius_px of the (fractional) lake centre."""
    r = np.arange(rows)[:, None] + 0.5
    c = np.arange(cols)[None, :] + 0.5
    return np.hypot(r - centre_row, c - centre_col) <= radius_px


def _pixels_touching(region: set[Pixel], flagged) -> int:
    """How many distinct flagged pixels are 4-connected neighbours of the region (same connectivity as region_grow)."""
    rows, cols = flagged.shape
    touching: set[tuple[int, int]] = set()
    for p in region:
        for r, c in ((p.row - 1, p.col), (p.row + 1, p.col), (p.row, p.col - 1), (p.row, p.col + 1)):
            if 0 <= r < rows and 0 <= c < cols and flagged[r, c]:
                touching.add((r, c))
    return len(touching)


# ---------------------------------------------------------------------------
# Resume state (FR-04): which lake the last unfinished run got through
# ---------------------------------------------------------------------------
def resume_state_path(db_path: str | Path) -> Path:
    return Path(db_path).with_suffix(".resume.json")


def load_resume_state(db_path: str | Path) -> RunLog:
    path = resume_state_path(db_path)
    if not path.exists():
        return RunLog()
    data = json.loads(path.read_text())
    return RunLog(last_completed_lake_id=data["last_completed_lake_id"], download_count=data["download_count"])


def save_resume_state(db_path: str | Path, state: RunLog) -> None:
    resume_state_path(db_path).write_text(json.dumps(
        {"last_completed_lake_id": state.last_completed_lake_id, "download_count": state.download_count}))


def clear_resume_state(db_path: str | Path) -> None:
    resume_state_path(db_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def _since_date_for(conn, lake_id: int, initial_since_date: date) -> date:
    """The day before the newest scene already stored (so a same-day second scene is not missed;
    duplicates are skipped by scene id), or initial_since_date for a lake with no scenes yet."""
    row = conn.execute("SELECT MAX(acquired_at) FROM scene WHERE lake_id = ?", (lake_id,)).fetchone()
    if row[0] is None:
        return initial_since_date
    return date.fromisoformat(row[0][:10]) - timedelta(days=1)


def _already_recorded(conn, lake_id: int, scene_id: str) -> bool:
    """True if this Earth Engine scene is already stored for this lake, wherever its file was saved
    (data/backfill/..., data/scenes/..., or not_downloaded/...). Matching on the scene id, not the
    whole path, is what stops a scheduled run re-downloading a scene the backfill already has."""
    return conn.execute(
        "SELECT 1 FROM scene WHERE lake_id = ? AND (file_path LIKE ? OR file_path LIKE ?)",
        (lake_id, f"%/{scene_id}.tif", f"{NOT_DOWNLOADED_PREFIX}%/{scene_id}"),
    ).fetchone() is not None


def sha256_of(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_pipeline_once(db_path: str | Path, data_dir: str | Path, initial_since_date: date,
                      lakes: list[int] | None = None, client: Any = None,
                      until_date: date | None = None) -> RunResult:
    """One full run over every lake. Never raises for a stage failure: the error is written to
    run_log.errors and returned in RunResult.errors, so the caller can exit non-zero."""
    sign_in_needed = client is None
    if client is None:
        from sailab import earth_engine_client as client  # the real Earth Engine connection
    data_dir = Path(data_dir)
    repo_root = Path(db_path).resolve().parent
    conn = db.connect(db_path)
    result = RunResult(run_id=db.start_run_log(conn))
    log.info("run %s started", result.run_id)

    try:
        if sign_in_needed:
            # Inside the try on purpose: a bad or expired key must end up in run_log.errors like any other
            # failure. (The first real backfill on 2026-11-08 failed because this call was missing: run_log 1.)
            log.info("signed in to Earth Engine as %s", client.initialize())
        lake_rows = {row["id"]: row for row in db.get_lakes(conn)}
        lake_ids = lakes if lakes is not None else sorted(lake_rows)
        state = load_resume_state(db_path)
        resuming = state.last_completed_lake_id is not None
        if resuming:
            note = f"resuming after lake {state.last_completed_lake_id} (previous run did not finish)"
            log.warning(note)
            result.notes.append(note)

        def process_lake(lake_id: int) -> None:
            if not resuming:
                save_resume_state(db_path, run.log)   # survives even a hard kill part way through this lake
            lake = lake_rows[lake_id]
            since = _since_date_for(conn, lake_id, initial_since_date)
            scenes = client.find_new_scenes(lake, since, until_date)
            log.info("%s: %d scenes listed after %s", lake["code"], len(scenes), since)
            for scene in scenes:
                _process_scene(conn, client, lake, scene, data_dir, repo_root, result)
            result.lakes_processed += 1

        run = ResumableRun(lakes=lake_ids, downloader=process_lake, log=state)
        try:
            run.run()
        except Exception:
            # A first failure leaves resume state so the next run picks up after the last finished lake.
            # A resumed run that fails again clears it: otherwise one lake failing every day would stop the
            # lakes before it from ever being checked again. Re-doing a lake is safe: stored scenes are skipped.
            if resuming:
                clear_resume_state(db_path)
            else:
                save_resume_state(db_path, run.log)
            raise
        clear_resume_state(db_path)
    except Exception as exc:  # recorded, never hidden
        result.errors = f"{type(exc).__name__}: {exc}\n" + "".join(traceback.format_exception(exc)[-6:])
        log.error("run %s failed: %s", result.run_id, result.errors)
    finally:
        db.finish_run_log(conn, result.run_id, result.lakes_processed, result.scenes_downloaded, result.errors)
        conn.close()
        log.info("run %s finished: %s", result.run_id, result)
    return result


def _process_scene(conn, client, lake, scene, data_dir: Path, repo_root: Path, result: RunResult) -> None:
    raster = data_dir / lake["code"] / f"{scene.scene_id}.tif"
    try:
        stored_path = str(raster.resolve().relative_to(repo_root))
    except ValueError:
        stored_path = str(raster.resolve())
    skipped_path = f"{NOT_DOWNLOADED_PREFIX}{lake['code']}/{scene.scene_id}"
    if _already_recorded(conn, lake["id"], scene.scene_id):
        log.info("%s %s: already recorded, skipped", lake["code"], scene.scene_id)
        return

    sensor = choose_sensor(scene.lake_cloud_percent, cloud_limit_percent=OPTICAL_CLOUD_LIMIT_PERCENT)
    if sensor == "radar":
        db.insert_scene(conn, lake["id"], "sentinel-2", scene.acquired_at, scene.lake_cloud_percent, skipped_path)
        result.scenes_recorded += 1
        log.info("%s %s: lake cloud %s%% > %s%% limit -> radar; optical-only build, recorded but not measured",
                 lake["code"], scene.scene_id, scene.lake_cloud_percent, OPTICAL_CLOUD_LIMIT_PERCENT)
        return

    client.download_scene_window(scene, lake, raster)
    scene_id = db.insert_scene(conn, lake["id"], "sentinel-2", scene.acquired_at, scene.lake_cloud_percent, stored_path)
    result.scenes_recorded += 1
    result.scenes_downloaded += 1
    # The checksum goes into the run log, so anyone can re-download the scene and confirm it is the same file.
    log.info("%s %s: downloaded %s sha256=%s", lake["code"], scene.scene_id, stored_path, sha256_of(raster))

    outcome = measure_scene(raster, lake)
    measurement_id = db.insert_measurement(conn, scene_id, lake["id"], "optical", outcome.extent_ha, outcome.status)
    result.measurements += 1
    log.info("%s %s: %s %s (%s)", lake["code"], scene.scene_id, outcome.status, outcome.extent_ha, outcome.reason)
    if outcome.status != "ok":
        return   # nothing to score: an unobserved lake has no extent to compare

    acquired_on = date.fromisoformat(scene.acquired_at[:10])
    # Only scenes from before this one: a backfilled 2024 scene must never be scored against 2025 data.
    history = [record for record in db.get_extent_history(conn, lake["id"], exclude_measurement_id=measurement_id)
               if record.observed_on < acquired_on]
    same_month = [record for record in history if record.observed_on.month == acquired_on.month]
    same_month_years = {record.observed_on.year for record in same_month}
    if len(same_month) < MIN_SAME_MONTH_VALUES or len(same_month_years) < MIN_SAME_MONTH_YEARS:
        # Check F: too little history for this month to say what "normal" is.
        db.insert_risk_score(conn, lake["id"], measurement_id, "anomaly_detector", "insufficient_history", None, None)
        result.risk_scores += 1
        log.info("%s %s: risk insufficient_history (check F: %d earlier values for month %02d from %d years; "
                 "need %d from %d)", lake["code"], scene.scene_id, len(same_month), acquired_on.month,
                 len(same_month_years), MIN_SAME_MONTH_VALUES, MIN_SAME_MONTH_YEARS)
        return
    score = score_against_seasonal_baseline(history, acquired_on, outcome.extent_ha)
    db.insert_risk_score(conn, lake["id"], measurement_id, "anomaly_detector",
                         RISK_STATUS_FROM_RISK_MODULE[score.status], score.baseline_ha, score.deviation_score)
    result.risk_scores += 1
    log.info("%s %s: risk %s baseline=%s score=%s", lake["code"], scene.scene_id, score.status,
             score.baseline_ha, score.deviation_score)
