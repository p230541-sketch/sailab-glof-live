"""Which roads, alone or in small groups, would cut each village below Shishper off, and are they on the
likely flood path?

    python scripts/critical_roads_shishper.py

Inputs (from the earlier project's folder, outside this repository):
  roads.geojson   OpenStreetMap roads (Geofabrik extract), clipped around the valley
  places.geojson  OpenStreetMap villages and towns
Method: sailab/critical_links.py (Sugiura and Kurauchi 2023), checked against sailab/network.py (bridges).
Flood path: the D8 path from scripts/compare_flow_paths.py (same lake cell, same height map).

Our own choices (the paper sets up supporting and receiving bases for its city; these are ours for a valley):
  - Roads a vehicle can use: every OpenStreetMap road class except footway, path, steps, cycleway,
    bridleway, pedestrian. Points shared by two or more road lines are junctions; a stretch between two
    junctions is one road.
  - Supporting bases ("where help comes from"): the ends of roads that leave the mapped area, i.e. road
    ends within EXIT_M of the edge of the road data.
  - Receiving base for a village: the road junction nearest to the village's point.
  - A road "is on the flood path" when any point of it lies within one height-map cell of the D8 path.
Village names that are not written in Latin letters are shown as "village <number>" (this project's
reports use English only).

Writes logs/<date>_critical_roads_shishper.md.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from math import cos, hypot, radians
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from sailab import critical_links as cl  # noqa: E402
from sailab.network import RoadGraph, find_bridges  # noqa: E402

VALLEY = Path(r"D:\University\FYP\data\downstream\shishper")
NOT_FOR_VEHICLES = {"footway", "path", "steps", "cycleway", "bridleway", "pedestrian"}
EXIT_M = 300.0
NEAREST_JUNCTION_MAX_M = 2000.0


def metres(lon1, lat1, lon2, lat2):
    return hypot((lat2 - lat1) * 110_574.0, (lon2 - lon1) * 111_320.0 * cos(radians(lat1)))


def latin_name(props, number):
    name = (props.get("name") or "").strip()
    return name if name and all(ord(ch) < 0x0250 for ch in name) else f"village {number}"


def build_roads():
    """Junction-to-junction roads from the OpenStreetMap lines. Returns ([(a, b, info)], {node: (lon, lat)})."""
    data = json.load(open(VALLEY / "roads.geojson", encoding="utf-8"))
    lines = []
    for feature in data["features"]:
        props, geom = feature["properties"], feature["geometry"]
        if props.get("fclass") in NOT_FOR_VEHICLES:
            continue
        parts = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
        for part in parts:
            lines.append(([(round(x, 7), round(y, 7)) for x, y in part], props))
    use = defaultdict(int)
    for points, _ in lines:
        for p in set(points):
            use[p] += 1
        use[points[0]] += 1
        use[points[-1]] += 1                  # line ends are always junctions (dead ends or joins)
    roads = []
    for points, props in lines:
        start = 0
        for k in range(1, len(points)):
            if use[points[k]] >= 2 or k == len(points) - 1:
                if points[start] != points[k]:
                    roads.append((points[start], points[k],
                                  {"name": props.get("name") or "", "fclass": props.get("fclass") or "",
                                   "osm_id": props.get("osm_id"), "points": points[start:k + 1]}))
                start = k
    return roads


def main() -> int:
    roads = build_roads()
    nodes = {p for a, b, _ in roads for p in (a, b)}
    xs, ys = [p[0] for p in nodes], [p[1] for p in nodes]
    west, east, south, north = min(xs), max(xs), min(ys), max(ys)
    degree = defaultdict(int)
    for a, b, _ in roads:
        degree[a] += 1
        degree[b] += 1
    exits = [p for p in nodes if degree[p] == 1 and min(
        metres(p[0], p[1], west, p[1]), metres(p[0], p[1], east, p[1]),
        metres(p[0], p[1], p[0], south), metres(p[0], p[1], p[0], north)) <= EXIT_M]
    info = {frozenset({a, b}): extra for a, b, extra in roads}

    # The D8 flood path (same as scripts/compare_flow_paths.py), as lon/lat cell centres.
    import compare_flow_paths as cfp
    from sailab.terrain import fill_sinks, trace_flood_path_2d
    dem, transform, dx, dy, lake = cfp.read_window()
    d8 = trace_flood_path_2d(fill_sinks(dem), lake)
    near_path = {(r + dr, c + dc) for r, c in d8 for dr in (-1, 0, 1) for dc in (-1, 0, 1)}

    def on_path(road_key):
        for lon, lat in info[road_key]["points"]:
            col, row = ~transform * (lon, lat)
            if (int(row), int(col)) in near_path:
                return True
        return False

    graph = RoadGraph()
    for a, b, _ in roads:
        graph.add_edge(a, b)
    bridges = find_bridges(graph)

    places = json.load(open(VALLEY / "places.geojson", encoding="utf-8"))["features"]
    rows = []
    for number, feature in enumerate(places, start=1):
        lon, lat = feature["geometry"]["coordinates"][:2]
        nearest = min(nodes, key=lambda p: metres(lon, lat, p[0], p[1]))
        gap = metres(lon, lat, nearest[0], nearest[1])
        name = latin_name(feature["properties"], number)
        if gap > NEAREST_JUNCTION_MAX_M:
            rows.append((name, None, [], gap))
            continue
        lec, sets = cl.critical_link_sets([(a, b) for a, b, _ in roads], exits, nearest)
        rows.append((name, lec, sets, gap))

    def describe(road_key):
        extra = info[road_key]
        label = extra["name"] if extra["name"] and all(ord(ch) < 0x0250 for ch in extra["name"]) else extra["fclass"]
        return f"{label} (OSM {extra['osm_id']})" + (" [on flood path]" if on_path(road_key) else "")

    lines = [
        "# Critical roads below Shishper lake (Sugiura and Kurauchi 2023)",
        "",
        f"Written by `scripts/critical_roads_shishper.py` on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.",
        f"Roads: {len(roads)} junction-to-junction roads from OpenStreetMap ({len(nodes)} junctions); "
        f"{len(exits)} road ends leave the mapped area and are used as the places help comes from.",
        f"Bridges found by Tarjan's method in the whole road graph: {len(bridges)}.",
        "",
        "LEC = how many roads must ALL be lost before the village is cut off from every road leaving the area.",
        "LEC 1 = a single road is enough; each critical set then holds one road.",
        "",
        "| Village | LEC | Smallest road sets that cut it off | Sets with a road on the flood path | Nearest junction |",
        "|---|---|---|---|---|",
    ]
    details = []
    for name, lec, sets, gap in rows:
        if lec is None:
            lines.append(f"| {name} | - | no road within {NEAREST_JUNCTION_MAX_M:.0f} m | - | {gap:.0f} m |")
            continue
        flooded = sum(1 for s in sets if any(on_path(r) for r in s))
        lines.append(f"| {name} | {lec} | {len(sets)}{'+' if len(sets) >= cl.MAX_CUTS else ''} | {flooded} | {gap:.0f} m |")
        if lec and flooded:
            details.append(f"- **{name}** (LEC {lec}): " + "; ".join(
                " + ".join(describe(r) for r in s) for s in sets if any(on_path(r) for r in s))[:900])
    lines += ["", "### Sets that include a road on the likely flood path", "", *(details or ["None."]), "",
              "This is a likely path, not a flood simulation: a road on the path may or may not be damaged."]
    out = REPO / "logs" / f"{datetime.now(timezone.utc):%Y-%m-%d}_critical_roads_shishper.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[:12]))
    print(f"... {len(rows)} villages. Written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
