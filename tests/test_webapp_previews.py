"""The three design-only screens must be unmistakably previews and must not be able to do anything."""
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from webapp.main import create_app

PREVIEWS = ["confirm-advisory", "delivery-status", "risk-threshold"]
BANNER = "Design preview only. Downstream Analysis and Alerting are not built."


@pytest.fixture
def client(source_db, tmp_path):
    return TestClient(create_app(source_db=source_db, work_dir=tmp_path / "work", today=lambda: date(2026, 11, 9),
                                 repo=tmp_path / "repo"))


@pytest.mark.parametrize("name", PREVIEWS)
def test_every_preview_carries_the_banner_and_watermark(client, name):
    r = client.get(f"/preview/{name}")
    assert r.status_code == 200
    assert BANNER in r.text
    assert 'class="preview-body"' in r.text                    # the diagonal "NOT CONNECTED" watermark
    assert "sample from the design" in r.text


@pytest.mark.parametrize("name", PREVIEWS)
def test_every_control_on_a_preview_is_disabled(client, name):
    html = client.get(f"/preview/{name}").text
    controls = re.findall(r"<(button|input|select|textarea)\b[^>]*>", html)
    tags = re.findall(r"<(?:button|input|select|textarea)\b[^>]*>", html)
    if name != "delivery-status":                               # that design has no buttons or fields at all
        assert controls, "expected the design's buttons and fields to be present"
    for tag in tags:
        assert re.search(r"\bdisabled\b", tag), tag
        assert "title=" in tag, f"disabled control without an explanation: {tag}"


@pytest.mark.parametrize("name", PREVIEWS)
def test_previews_have_no_forms_scripts_or_handlers(client, name):
    html = client.get(f"/preview/{name}").text.lower()
    assert "<form" not in html and "<script" not in html and "onclick" not in html


def test_the_only_route_that_can_change_anything_is_the_live_check(client):
    """Previews and pages are GET only. The single exception is POST /live/check, which writes to the
    app's working copy only (see test_webapp_live.py for the proof that the published file is untouched)."""
    changing = {(route.path, m) for route in client.app.routes for m in getattr(route, "methods", set())
                if m not in {"GET", "HEAD"}}
    assert changing == {("/live/check", "POST")}, changing


def test_real_pages_do_not_carry_the_preview_banner(client):
    for url in ("/", "/lakes/KRB", "/lakes/ATS"):
        assert BANNER not in client.get(url).text


def test_previews_are_labelled_in_the_sidebar(client):
    html = client.get("/").text
    assert "Design previews (not built)" in html
    assert html.count('class="sub preview-link') == 3


def test_unknown_preview_is_404(client):
    assert client.get("/preview/send-everything").status_code == 404
