"""Save the web app's pages as a ready-made (static) website, for free hosting with no server (GitHub Pages).

    python scripts/export_static_site.py --db sailab_glof.db --out site

Every page is rendered by the real web app (webapp/main.py) from the given database, then saved as a file:
  index.html                          the dashboard
  lake-<CODE>-<range>-p<N>.html        every lake page, for each time range and every observation-log page
  static/                              the style sheet and logo
Links between pages are rewritten to those files. What needs the laptop is turned into plain text with a
note: scene pictures ("View image"), the latest-image panels, Live check, Load newer data, the design
previews and the automatic reload. Nothing is calculated here; the pages show exactly what the app shows.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RANGES = ("12m", "24m", "all")
LAPTOP_ONLY = "Only in the laptop version"
PAGE_COUNT = re.compile(r"Page\s+\d+\s+of\s+(\d+)")


def lake_file(code: str, range_key: str = "all", page: int = 1) -> str:
    return f"lake-{code}-{range_key}-p{page}.html"


def rewrite(html: str, code: str | None, generated: str) -> str:
    """Turn one rendered page into a page that works as a plain file (see the module note)."""
    # The automatic-reload script asks the server for news; a file has no server.
    html = re.sub(r"<script>\s*/\* Automatic reload.*?</script>", "", html, flags=re.S)
    # Buttons that start something on the laptop.
    html = re.sub(r'<form[^>]*action="/(?:reload|live/check)"[^>]*>.*?</form>', "", html, flags=re.S)
    # Pictures that are kept only on the laptop.
    html = re.sub(r'<img[^>]*src="/(?:lakes/[^"]*\.png|scenes/[^"]*)"[^>]*>',
                  f'<p class="footnote">{LAPTOP_ONLY}: the satellite pictures are kept on the laptop.</p>', html)
    # Links to laptop-only pages become plain text.
    html = re.sub(r'<a\b[^>]*href="/(?:scenes|live|preview|api)[^"]*"[^>]*>(.*?)</a>',
                  lambda m: f'<span title="{LAPTOP_ONLY}">{m.group(1)}</span>', html, flags=re.S)
    # Links between lake pages.
    html = re.sub(r'href="/lakes/([A-Z0-9]+)"', lambda m: f'href="{lake_file(m.group(1))}"', html)
    if code is not None:
        html = re.sub(r'href="\?range=([0-9a-z]+)(?:&amp;|&)page=(\d+)"',
                      lambda m: f'href="{lake_file(code, m.group(1), int(m.group(2)))}"', html)
        html = re.sub(r'href="\?range=([0-9a-z]+)"', lambda m: f'href="{lake_file(code, m.group(1))}"', html)
    html = html.replace('href="/"', 'href="index.html"')
    html = re.sub(r'(href|src)="/static/', r'\1="static/', html)
    banner = (f'<div class="banner info" style="margin-bottom:16px"><div><strong>Online snapshot</strong> made '
              f'{escape(generated)} by the nightly run. Satellite pictures, Live check and the design previews '
              f'are only in the laptop version.</div></div>')
    return html.replace("<main>", "<main>" + banner, 1)


def export(db_path: Path, out_dir: Path) -> dict[str, int]:
    os.environ["SAILAB_AUTO_RELOAD_SECONDS"] = "0"           # no background watcher while exporting
    from fastapi.testclient import TestClient

    from sailab import queries
    from webapp.main import create_app

    import sqlite3

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    codes = [lake["code"] for lake in queries.list_lakes(conn)]
    conn.close()

    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    counts = {"pages": 0, "lakes": len(codes)}
    with tempfile.TemporaryDirectory() as work:
        client = TestClient(create_app(source_db=db_path, work_dir=Path(work) / "work", repo=REPO))

        def save(url: str, name: str, code: str | None) -> str:
            response = client.get(url)
            response.raise_for_status()
            (out_dir / name).write_text(rewrite(response.text, code, generated), encoding="utf-8")
            counts["pages"] += 1
            return response.text

        save("/", "index.html", None)
        for code in codes:
            for range_key in RANGES:
                first = save(f"/lakes/{code}?range={range_key}&page=1", lake_file(code, range_key, 1), code)
                match = PAGE_COUNT.search(re.sub(r"<[^>]+>", " ", first))
                for page in range(2, int(match.group(1)) + 1 if match else 2):
                    save(f"/lakes/{code}?range={range_key}&page={page}", lake_file(code, range_key, page), code)
    shutil.copytree(REPO / "webapp" / "static", out_dir / "static")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")   # serve files as they are (no Jekyll processing)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=REPO / "sailab_glof.db")
    parser.add_argument("--out", type=Path, default=REPO / "site")
    args = parser.parse_args(argv)
    counts = export(args.db.resolve(), args.out.resolve())
    print(f"Static site written to {args.out}: {counts['pages']} pages for {counts['lakes']} lakes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
