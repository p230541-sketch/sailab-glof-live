"""scripts/export_static_site.py: the online snapshot works as plain files."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "sailab_export_static", Path(__file__).resolve().parent.parent / "scripts" / "export_static_site.py")
export_static = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(export_static)


def test_every_internal_link_points_to_a_file_that_exists(source_db, tmp_path):
    out = tmp_path / "site"
    counts = export_static.export(source_db, out)
    assert counts["lakes"] == 2 and (out / "index.html").is_file() and (out / ".nojekyll").is_file()
    assert (out / "static" / "style.css").is_file()
    for page in out.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        for target in re.findall(r'(?:href|src)="([^"#]+)"', html):
            if target.startswith(("http://", "https://", "mailto:", "data:")):
                continue
            assert (out / target).is_file(), f"{page.name} links to missing {target}"


def test_laptop_only_parts_are_gone(source_db, tmp_path):
    out = tmp_path / "site"
    export_static.export(source_db, out)
    for page in out.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        for laptop_only in ('href="/scenes', 'href="/live', 'href="/preview', 'action="/reload"',
                            'action="/live/check"', 'fetch("/api/provenance"', 'src="/lakes/'):
            assert laptop_only not in html, f"{page.name} still has {laptop_only}"
        assert "Online snapshot" in html


def test_each_lake_gets_a_page_for_every_range(source_db, tmp_path):
    out = tmp_path / "site"
    export_static.export(source_db, out)
    for code in ("KRB", "ATS"):
        for range_key in export_static.RANGES:
            assert (out / export_static.lake_file(code, range_key, 1)).is_file()
    assert "lake-KRB-all-p1.html" in (out / "index.html").read_text(encoding="utf-8")


def test_rewrite_maps_paging_links_with_either_ampersand():
    html = '<main><a href="?range=all&amp;page=3">x</a><a href="?range=12m&page=2">y</a></main>'
    out = export_static.rewrite(html, "KRB", "now")
    assert 'href="lake-KRB-all-p3.html"' in out and 'href="lake-KRB-12m-p2.html"' in out
