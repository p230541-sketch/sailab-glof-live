"""Offline SVG charts, drawn on the server from real query results (no internet, no JavaScript library).

Each function only places the values it is given; it never smooths, interpolates or fills gaps. A gap
in the data (cloud, frozen lake) stays a visible gap.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from math import cos, radians

OPTICAL = "#1e4e8c"
BASELINE = "#5b6470"
GRID = "#e3e8ec"
AXIS_TEXT = "#5b6470"
TICK_COLOURS = {"ok": OPTICAL, "insufficient_observation": "#b08a2e", "too_cloudy": "#a7b0ba"}
MAX_LINE_GAP_DAYS = 45      # points further apart than this are not joined (a winter gap is not a trend)


def _d(value: str | date) -> date:
    return value if isinstance(value, date) else datetime.fromisoformat(value).date()


def sparkline(values: list[float], width: int = 84, height: int = 22) -> str:
    """Tiny line of the most recent usable extents, oldest left. Fewer than 2 values: no line is drawn."""
    if len(values) < 2:
        return (f'<svg class="spark" width="{width}" height="{height}" role="img" aria-label="not enough usable '
                f'measurements for a trend"><line x1="0" y1="{height / 2}" x2="{width}" y2="{height / 2}" '
                f'stroke="{GRID}" stroke-dasharray="3 3"/></svg>')
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = width / (len(values) - 1)
    pts = " ".join(f"{i * step:.1f},{height - 2 - (v - lo) / span * (height - 4):.1f}" for i, v in enumerate(values))
    return (f'<svg class="spark" width="{width}" height="{height}" role="img" aria-label="last {len(values)} '
            f'usable extents, {lo:.1f} to {hi:.1f} ha"><polyline points="{pts}" fill="none" stroke="#16191d" '
            f'stroke-width="1.3"/></svg>')


def extent_chart(history: list[dict], start: date, end: date, width: int = 760, height: int = 300) -> str:
    """Lake extent over time from lake_history() rows.

    - Each usable measurement is a dot; dots closer than MAX_LINE_GAP_DAYS are joined.
    - Where a risk score was computed, its seasonal baseline is drawn as a short grey dash at that date.
    - Below the plot, every scene is a tick: blue measured, ochre refused by the quality checks,
      grey too cloudy to download. So every gap in the line is explained by real scenes.
    """
    rows = [r for r in history if start <= _d(r["acquired_at"]) <= end]
    ok = [r for r in rows if r["measurement_status"] == "ok"]
    left, right, top, plot_bottom = 56, 16, 16, height - 74
    strip_y = plot_bottom + 30
    span_days = max((end - start).days, 1)

    def x(day: date) -> float:
        return left + (day - start).days / span_days * (width - left - right)

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="lake extent chart">']
    if ok:
        values = [r["extent_ha"] for r in ok] + [r["baseline_ha"] for r in ok if r["baseline_ha"] is not None]
        lo, hi = min(values), max(values)
        pad = max((hi - lo) * 0.15, 1.0)
        lo, hi = lo - pad, hi + pad

        def y(v: float) -> float:
            return plot_bottom - (v - lo) / (hi - lo) * (plot_bottom - top)

        for i in range(5):
            v = lo + (hi - lo) * i / 4
            parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{GRID}"/>'
                         f'<text x="{left - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="axis">{v:.0f}</text>')
        for a, b in zip(ok, ok[1:]):
            if (_d(b["acquired_at"]) - _d(a["acquired_at"])).days <= MAX_LINE_GAP_DAYS:
                parts.append(f'<line x1="{x(_d(a["acquired_at"])):.1f}" y1="{y(a["extent_ha"]):.1f}" '
                             f'x2="{x(_d(b["acquired_at"])):.1f}" y2="{y(b["extent_ha"]):.1f}" stroke="{OPTICAL}" '
                             f'stroke-width="1.5"/>')
        for r in ok:
            cx = x(_d(r["acquired_at"]))
            if r["baseline_ha"] is not None:
                parts.append(f'<line class="baseline" x1="{cx - 7:.1f}" x2="{cx + 7:.1f}" y1="{y(r["baseline_ha"]):.1f}" '
                             f'y2="{y(r["baseline_ha"]):.1f}" stroke="{BASELINE}" stroke-width="2.5"/>')
            label = f'{r["acquired_at"][:10]}: {r["extent_ha"]:.2f} ha'
            if r["deviation_score"] is not None:
                label += f', baseline {r["baseline_ha"]:.2f} ha, score {r["deviation_score"]:+.2f}'
            parts.append(f'<circle class="pt" cx="{cx:.1f}" cy="{y(r["extent_ha"]):.1f}" r="3.6" fill="{OPTICAL}">'
                         f'<title>{escape(label)}</title></circle>')
    else:
        parts.append(f'<text x="{width / 2}" y="{(top + plot_bottom) / 2}" text-anchor="middle" class="empty">'
                     f'No usable measurement in this period</text>')

    # x axis: one label per month boundary (thinned to keep them readable)
    months, d = [], date(start.year, start.month, 1)
    while d <= end:
        if d >= start:
            months.append(d)
        d = date(d.year + (d.month // 12), d.month % 12 + 1, 1)
    stride = max(1, len(months) // 12)
    for m in months[::stride]:
        label = m.strftime("%b") if m.month != 1 else m.strftime("%b %Y")
        parts.append(f'<line x1="{x(m):.1f}" x2="{x(m):.1f}" y1="{top}" y2="{plot_bottom}" stroke="{GRID}" '
                     f'stroke-dasharray="2 3"/><text x="{x(m):.1f}" y="{plot_bottom + 16}" text-anchor="middle" '
                     f'class="axis">{label}</text>')
    parts.append(f'<text x="{left - 8}" y="{strip_y + 4}" text-anchor="end" class="axis">scenes</text>')
    for r in rows:
        kind = "too_cloudy" if r["too_cloudy"] else (r["measurement_status"] or "too_cloudy")
        parts.append(f'<rect class="tick tick-{kind}" x="{x(_d(r["acquired_at"])) - 1:.1f}" y="{strip_y - 7}" width="2" '
                     f'height="14" fill="{TICK_COLOURS[kind]}"><title>{escape(r["acquired_at"][:10])}: '
                     f'{kind.replace("_", " ")}</title></rect>')
    parts.append("</svg>")
    return "".join(parts)


def location_map(lakes: list[dict], width: int = 620, height: int = 420) -> str:
    """The lakes at their real coordinates on a plain lon/lat frame (no basemap: that would need internet).

    lakes: dicts with code, name, centre_lon, centre_lat, data_gap (bool), link.
    """
    lons = [l["centre_lon"] for l in lakes]
    lats = [l["centre_lat"] for l in lakes]
    pad = 0.12
    lon0, lon1 = min(lons) - pad, max(lons) + pad
    lat0, lat1 = min(lats) - pad, max(lats) + pad
    # keep 1 degree of longitude the right width for this latitude, so distances look right
    kx = cos(radians((lat0 + lat1) / 2))
    scale = min((width - 60) / ((lon1 - lon0) * kx), (height - 50) / (lat1 - lat0))
    ox = (width - (lon1 - lon0) * kx * scale) / 2
    oy = (height - (lat1 - lat0) * scale) / 2

    def px(lon: float, lat: float) -> tuple[float, float]:
        return ox + (lon - lon0) * kx * scale, height - oy - (lat - lat0) * scale

    parts = [f'<svg class="map" viewBox="0 0 {width} {height}" role="img" aria-label="lake locations">',
             f'<rect width="{width}" height="{height}" fill="#e9edef"/>']
    step = 0.1
    g = round(lon0 / step) * step
    while g <= lon1:
        a, _ = px(g, lat0)
        parts.append(f'<line x1="{a:.1f}" x2="{a:.1f}" y1="0" y2="{height}" stroke="#dde3e7"/>'
                     f'<text x="{a + 3:.1f}" y="{height - 6}" class="axis">{g:.1f}°E</text>')
        g += step
    g = round(lat0 / step) * step
    while g <= lat1:
        _, b = px(lon0, g)
        parts.append(f'<line x1="0" x2="{width}" y1="{b:.1f}" y2="{b:.1f}" stroke="#dde3e7"/>'
                     f'<text x="4" y="{b - 3:.1f}" class="axis">{g:.1f}°N</text>')
        g += step
    for l in lakes:
        cx, cy = px(l["centre_lon"], l["centre_lat"])
        marker = (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="9" fill="#ffffff" stroke="#5b6470" stroke-width="2" '
                  f'stroke-dasharray="3 2"/>' if l["data_gap"] else
                  f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="{OPTICAL}" stroke="#ffffff" stroke-width="2"/>')
        parts.append(f'<a href="{escape(l["link"])}"><g class="lake-marker">{marker}'
                     f'<rect x="{cx + 14:.1f}" y="{cy - 12:.1f}" width="{len(l["code"]) * 9 + 14}" height="22" rx="3" '
                     f'fill="#ffffff"/><text x="{cx + 21:.1f}" y="{cy + 4:.1f}" class="mono">{escape(l["code"])}</text>'
                     f'<title>{escape(l["name"])}: {l["centre_lat"]:.5f} N, {l["centre_lon"]:.5f} E</title></g></a>')
    parts.append("</svg>")
    return "".join(parts)
