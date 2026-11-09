"""SailAb GLOF web app: read-only views over a working copy of sailab_glof.db.

Why a copy (decided with the project owner, 2026-11-09): the nightly GitHub Actions run commits its
own sailab_glof.db. If this laptop also wrote to that file (the live-trigger button does write), the two
binary copies could never be merged. So at start-up the app copies the repository's database to
.webapp/ and works only on that copy. The copy's origin (file checksum, git commit, time) is recorded
and shown on every page, so a viewer can tell exactly which published state they are looking at.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sailab import queries
from webapp import images, pages
from webapp.live import LiveChecker

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DB = REPO / "sailab_glof.db"
DEFAULT_WORK_DIR = REPO / ".webapp"
WORKING_COPY_NAME = "sailab_glof_working_copy.db"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def make_working_copy(source_db: Path, work_dir: Path) -> dict[str, Any]:
    """Copy the source database and describe exactly where the copy came from."""
    if not source_db.is_file():
        raise FileNotFoundError(f"source database not found: {source_db}")
    work_dir.mkdir(parents=True, exist_ok=True)
    copy = work_dir / WORKING_COPY_NAME
    shutil.copy2(source_db, copy)
    rel = os.path.relpath(source_db, REPO)
    committed_db_status = _git("status", "--porcelain", "--", rel)
    return {
        "source_db": str(source_db),
        "source_sha256": _sha256(source_db),
        "working_copy": str(copy),
        "copied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_commit_time": _git("log", "-1", "--format=%cI"),
        "git_commit_subject": _git("log", "-1", "--format=%s"),
        # True if the source file differs from what is committed (e.g. a local run wrote to it):
        "source_differs_from_commit": None if committed_db_status is None else committed_db_status != "",
    }


def create_app(source_db: Path | None = None, work_dir: Path | None = None,
               today: Callable[[], Any] | None = None, repo: Path | None = None,
               live_runner: Callable[..., Any] | None = None) -> FastAPI:
    source_db = Path(source_db or os.environ.get("SAILAB_SOURCE_DB", DEFAULT_SOURCE_DB))
    work_dir = Path(work_dir or os.environ.get("SAILAB_WORK_DIR", DEFAULT_WORK_DIR))
    today = today or (lambda: datetime.now(timezone.utc).date())

    app = FastAPI(title="SailAb GLOF", docs_url="/api/docs", redoc_url=None)
    app.state.provenance = make_working_copy(source_db, work_dir)
    working_copy = Path(app.state.provenance["working_copy"])
    # A fresh copy means earlier live checks (and any half-finished one's resume file) no longer apply.
    for stale in (work_dir / "live_checks.json", working_copy.with_suffix(".resume.json")):
        stale.unlink(missing_ok=True)
    live = LiveChecker(working_copy, work_dir / "live_scenes", work_dir / "live_checks.json", runner=live_runner)
    app.state.live = live

    @contextmanager
    def read_only() -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(f"file:{working_copy}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.state.read_only = read_only

    def lake_or_404(conn: sqlite3.Connection, code: str) -> dict[str, Any]:
        lake = queries.get_lake(conn, code)
        if lake is None:
            raise HTTPException(status_code=404, detail=f"no lake with code {code!r} in the database")
        return lake

    @app.get("/api/provenance")
    def provenance() -> dict[str, Any]:
        return app.state.provenance

    @app.get("/api/lakes")
    def lakes() -> list[dict[str, Any]]:
        with read_only() as conn:
            return [{**lake, "summary": queries.lake_summary(conn, lake["id"], today())}
                    for lake in queries.list_lakes(conn)]

    @app.get("/api/lakes/{code}")
    def lake(code: str) -> dict[str, Any]:
        with read_only() as conn:
            found = lake_or_404(conn, code)
            return {**found, "summary": queries.lake_summary(conn, found["id"], today())}

    @app.get("/api/lakes/{code}/history")
    def lake_history(code: str) -> list[dict[str, Any]]:
        with read_only() as conn:
            return queries.lake_history(conn, lake_or_404(conn, code)["id"])

    @app.get("/api/run-log")
    def run_log(limit: int = 20) -> list[dict[str, Any]]:
        with read_only() as conn:
            return queries.run_log(conn, limit)

    @app.get("/api/run-log/latest")
    def run_log_latest() -> dict[str, Any]:
        with read_only() as conn:
            row = queries.latest_run(conn)
        if row is None:
            raise HTTPException(status_code=404, detail="run_log is empty")
        return row

    @app.get("/api/totals")
    def totals() -> dict[str, int]:
        with read_only() as conn:
            return queries.database_totals(conn)

    # --- HTML pages -------------------------------------------------------------------------
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    templates.env.filters.update({"date": pages.fmt_date, "utc_time": pages.fmt_utc_time, "pkt": pages.fmt_pkt,
                                  "ha": pages.fmt_ha, "score": pages.fmt_score,
                                  "month": lambda iso: datetime.fromisoformat(iso).strftime("%B")})
    templates.env.globals.update({"quality": pages.scene_quality, "stale_days": pages.STALE_AFTER_DAYS})
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    repo_root = Path(repo or os.environ.get("SAILAB_REPO", REPO))   # where scene file paths are resolved

    def render(request: Request, name: str, nav: str, d: dict[str, Any]) -> HTMLResponse:
        with read_only() as conn:
            nav_lakes = queries.list_lakes(conn)
        return templates.TemplateResponse(request, name, {"d": d, "nav": nav, "nav_lakes": nav_lakes,
                                                          "provenance": app.state.provenance,
                                                          "live_run_ids": live.live_run_ids()})

    @app.get("/", response_class=HTMLResponse)
    def dashboard_page(request: Request) -> HTMLResponse:
        with read_only() as conn:
            d = pages.dashboard(conn, today())
        return render(request, "dashboard.html", "dashboard", d)

    @app.get("/lakes/{code}", response_class=HTMLResponse)
    def lake_page(request: Request, code: str, range: str = "all", page: int = 1) -> HTMLResponse:
        with read_only() as conn:
            d = pages.lake_detail(conn, lake_or_404(conn, code), today(), range, page, repo_root, work_dir)
        return render(request, "lake.html", code, d)

    # Design previews: static templates with the design's own sample data. They read nothing from the
    # database, and the app has no POST/PUT/DELETE route at all, so nothing on them can act.
    previews = {"confirm-advisory": ("preview_confirm_advisory.html", "p-confirm"),
                "delivery-status": ("preview_delivery_status.html", "p-delivery"),
                "risk-threshold": ("preview_risk_threshold.html", "p-threshold")}

    @app.get("/preview/{name}", response_class=HTMLResponse)
    def preview_page(request: Request, name: str) -> HTMLResponse:
        if name not in previews:
            raise HTTPException(status_code=404, detail=f"no design preview called {name!r}")
        template, nav = previews[name]
        return render(request, template, nav, {})

    @app.get("/lakes/{code}/latest-radar.png")
    def lake_latest_radar(code: str) -> FileResponse:
        with read_only() as conn:
            found = lake_or_404(conn, code)
            latest = queries.lake_summary(conn, found["id"], today())["radar"]["latest_ok_measurement"]
        if latest is None:
            raise HTTPException(status_code=404, detail=f"{code} has no usable radar measurement yet")
        tif = repo_root / latest["file_path"]
        if not tif.is_file() and (work_dir / latest["file_path"]).is_file():
            tif = work_dir / latest["file_path"]
        dem = repo_root / "data" / "dem" / f"{code}_dem.tif"
        if not tif.is_file() or not dem.is_file():
            raise HTTPException(status_code=404, detail=f"radar or DEM file not on this machine: {latest['file_path']}")
        png = work_dir / "images" / f"{code}_{tif.stem}_radar.png"
        if not png.is_file():
            images.render_radar_png(tif, found, dem, png)
        return FileResponse(png, media_type="image/png")

    # --- live check: the ONLY route that changes anything, and only the working copy ------------
    @app.get("/live", response_class=HTMLResponse)
    def live_page(request: Request) -> HTMLResponse:
        return render(request, "live.html", "live", {"state": live.snapshot(), "history": list(reversed(live.history))})

    @app.post("/live/check")
    def live_check() -> RedirectResponse:
        live.start()                     # does nothing if a check is already running
        return RedirectResponse("/live", status_code=303)

    @app.get("/lakes/{code}/latest-image.png")
    def lake_latest_image(code: str) -> FileResponse:
        with read_only() as conn:
            found = lake_or_404(conn, code)
            latest = queries.lake_summary(conn, found["id"], today())["latest_ok_measurement"]
        if latest is None:
            raise HTTPException(status_code=404, detail=f"{code} has no usable measurement yet")
        tif = repo_root / latest["file_path"]
        if not tif.is_file() and (work_dir / latest["file_path"]).is_file():
            tif = work_dir / latest["file_path"]          # downloaded by a live check on this laptop
        if not tif.is_file():
            raise HTTPException(status_code=404, detail=f"image file not on this machine: {latest['file_path']}")
        png = work_dir / "images" / f"{code}_{tif.stem}.png"
        if not png.is_file():
            images.render_scene_png(tif, found, png)
        return FileResponse(png, media_type="image/png")

    return app
