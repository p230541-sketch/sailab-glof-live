"""Check every number on the Dashboard and Lake Detail screens against the database, independently.

Run before a demo:   .venv/bin/python scripts/verify_gui_numbers.py
It starts the app in-process on a fresh copy of sailab_glof.db (exactly as `uvicorn app:app` does),
renders each page, and looks for every number computed here with separate SQL (none of the app's query
code is reused). Prints a table and exits 1 if any number is missing or different.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from webapp import images  # noqa: E402
from webapp.main import create_app  # noqa: E402

PKT = timezone(timedelta(hours=5))


def page_text(client: TestClient, url: str) -> str:
    html = client.get(url).text
    html = re.sub(r"<svg.*?</svg>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def main() -> int:
    today = datetime.now(timezone.utc).date()
    client = TestClient(create_app(work_dir=Path(tempfile.mkdtemp(prefix="sailab_verify_"))))
    db = sqlite3.connect(REPO / "sailab_glof.db")
    db.row_factory = sqlite3.Row
    q = lambda sql, *a: db.execute(sql, a).fetchone()  # noqa: E731
    fd = lambda iso: datetime.fromisoformat(iso).strftime("%d %b %Y")  # noqa: E731
    rows: list[str] = []
    failures = 0

    def check(screen: str, label: str, text: str, expected: str, source: str) -> None:
        nonlocal failures
        found = expected in text
        failures += not found
        rows.append(f"| {screen} | {label} | `{expected}` | {source} | {'yes' if found else 'NO'} |")

    dash = page_text(client, "/")
    n_scene = q("SELECT COUNT(*) FROM scene")[0]
    n_cloudy = q("SELECT COUNT(*) FROM scene WHERE file_path LIKE 'not_downloaded/%'")[0]
    n_meas = q("SELECT COUNT(*) FROM measurement")[0]
    n_ok = q("SELECT COUNT(*) FROM measurement WHERE status = 'ok'")[0]
    first, last = q("SELECT MIN(acquired_at), MAX(acquired_at) FROM scene")
    check("Dashboard", "Lakes monitored", dash, f"Lakes monitored {q('SELECT COUNT(*) FROM lake')[0]}", "COUNT(lake)")
    check("Dashboard", "Scenes recorded", dash, f"Scenes recorded {n_scene}", "COUNT(scene)")
    check("Dashboard", "Scene date range", dash, f"{fd(first)} to {fd(last)}", "MIN/MAX(scene.acquired_at)")
    check("Dashboard", "Too cloudy", dash, f"{round(100 * n_cloudy / n_scene)}%", "not_downloaded scenes / all scenes")
    check("Dashboard", "Too cloudy count", dash, f"{n_cloudy} of {n_scene} scenes", "same")
    check("Dashboard", "Usable measurements", dash, f"Usable measurements {n_ok} of {n_meas} downloaded", "measurement.status = ok")
    run = q("SELECT * FROM run_log ORDER BY id DESC LIMIT 1")
    check("Dashboard", "Last pipeline run", dash,
          "Last pipeline run " + datetime.fromisoformat(run["started_at"]).astimezone(PKT).strftime("%d %b %Y, %H:%M PKT"),
          f"run_log {run['id']}.started_at")

    for lake in db.execute("SELECT * FROM lake ORDER BY id").fetchall():
        lid, code = lake["id"], lake["code"]
        detail = page_text(client, f"/lakes/{code}")
        latest = q("""SELECT s.acquired_at, m.extent_ha, s.file_path FROM measurement m JOIN scene s ON s.id = m.scene_id
                      WHERE m.lake_id = ? AND m.status = 'ok' ORDER BY s.acquired_at DESC LIMIT 1""", lid)
        if latest is None:
            check("Dashboard", f"{code} latest usable", dash, "No usable measurement yet", "no ok measurement")
            continue
        days = (today - datetime.fromisoformat(latest[0]).date()).days
        check("Dashboard", f"{code} latest usable", dash, f"{latest[1]:.2f} ha on {fd(latest[0])}, {days} days ago", "newest ok measurement")
        score = q("""SELECT r.status, r.baseline_ha, r.deviation_score, s.acquired_at, m.extent_ha FROM risk_score r
                     JOIN measurement m ON m.id = r.measurement_id JOIN scene s ON s.id = m.scene_id
                     WHERE r.lake_id = ? ORDER BY s.acquired_at DESC LIMIT 1""", lid)
        chip = ("Insufficient history" if score["status"] == "insufficient_history"
                else f"Deviation {score['deviation_score']:+.2f}".replace("-", "−"))
        check("Dashboard", f"{code} score", dash, chip, "newest risk_score")
        c = q("""SELECT COUNT(*) n, SUM(s.file_path LIKE 'not_downloaded/%') cloudy, SUM(m.status = 'ok') ok,
                 SUM(m.status = 'insufficient_observation') refused FROM scene s LEFT JOIN measurement m ON m.scene_id = s.id
                 WHERE s.lake_id = ?""", lid)
        check("Lake Detail", f"{code} scenes", detail,
              f"Scenes recorded {c['n']} {c['ok']} usable, {c['refused']} refused, {c['cloudy']} too cloudy", "scene + measurement counts")
        check("Lake Detail", f"{code} latest usable", detail, f"{latest[1]:.2f} ha {fd(latest[0])}, {days} days ago", "newest ok measurement")
        check("Lake Detail", f"{code} settings", detail,
              f"window {lake['boundary_radius_m']:.0f} m, growth limit {lake['growth_distance_limit_m']:.0f} m", "lake row")
        check("Lake Detail", f"{code} score scene", detail, f"Scene {fd(score['acquired_at'])}", "newest risk_score")
        check("Lake Detail", f"{code} score area", detail, f"Measured area {score['extent_ha']:.2f} ha", "its measurement")
        if score["status"] == "ok":
            check("Lake Detail", f"{code} baseline", detail, f"Seasonal baseline {score['baseline_ha']:.2f} ha", "risk_score.baseline_ha")
            check("Lake Detail", f"{code} deviation", detail,
                  f"Deviation score {score['deviation_score']:+.2f}".replace("-", "−"), "risk_score.deviation_score")
        when = datetime.fromisoformat(score["acquired_at"])
        earlier = db.execute("""SELECT substr(s.acquired_at, 1, 4) FROM measurement m JOIN scene s ON s.id = m.scene_id
                                WHERE m.lake_id = ? AND m.status = 'ok' AND substr(s.acquired_at, 6, 2) = ?
                                AND s.acquired_at < ?""", (lid, when.strftime("%m"), score["acquired_at"][:10])).fetchall()
        years = len({r[0] for r in earlier})
        check("Lake Detail", f"{code} same-month values", detail,
              f"Earlier {when.strftime('%B')} values {len(earlier)} from {years} year{'s' if years != 1 else ''}", "ok, same month, earlier")
        tif = REPO / latest[2]
        if tif.is_file():
            px = images.render_scene_png(tif, dict(lake), Path(tempfile.mkdtemp()) / "x.png")
            same = abs(px / 100 - latest[1]) < 1e-9
            failures += not same
            rows.append(f"| Lake Detail | {code} image outline | `{px} px = {px / 100:.2f} ha` | recomputed from {latest[2]} | "
                        f"{'yes' if same else 'NO'} |")
        else:
            rows.append(f"| Lake Detail | {code} image outline | (file not on this machine) | {latest[2]} | skipped |")

    print(f"checked {datetime.now(timezone.utc).isoformat(timespec='seconds')}, database commit "
          f"{client.get('/api/provenance').json()['git_commit']}\n")
    print("| Screen | Number | Expected on page | Source | Found |\n|---|---|---|---|---|")
    print("\n".join(rows))
    print(f"\n{len(rows) - failures} of {len(rows)} checks passed." + ("" if not failures else f" {failures} FAILED."))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
