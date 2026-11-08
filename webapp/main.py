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

from fastapi import FastAPI, HTTPException

from sailab import queries

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
               today: Callable[[], Any] | None = None) -> FastAPI:
    source_db = Path(source_db or os.environ.get("SAILAB_SOURCE_DB", DEFAULT_SOURCE_DB))
    work_dir = Path(work_dir or os.environ.get("SAILAB_WORK_DIR", DEFAULT_WORK_DIR))
    today = today or (lambda: datetime.now(timezone.utc).date())

    app = FastAPI(title="SailAb GLOF", docs_url="/api/docs", redoc_url=None)
    app.state.provenance = make_working_copy(source_db, work_dir)
    working_copy = Path(app.state.provenance["working_copy"])

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

    return app
