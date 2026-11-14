"""Past glacial lake outburst floods in High Mountain Asia, from two published databases, and how many
of them are usable for training or testing a risk model.

Databases (both read straight from the published files):
  GLOBAL  Lützow, Veh and Korup (2023), "A global database of historic glacier lake outburst floods",
          Earth System Science Data 15, 2983-3000. Zenodo 10.5281/zenodo.7330344 (file glofdatabase_v4-2.ods).
          Only its three High Mountain Asia sheets are read (RGI regions 13, 14 and 15).
  HMA     Shrestha, Steiner and others (2023), "A comprehensive and version-controlled database of glacial
          lake outburst floods in High Mountain Asia", Earth System Science Data 15, 3941-3961.
          Zenodo 10.5281/zenodo.7271187 (file HMAGLOFDB.csv, release v1.3.0).

The filters, in this order (the order the project plan gives). A count is kept after every one:
  1. after 2015       the event's year is 2016 or later. Sentinel-2 imagery starts in mid-2015, so only
                      later events can be checked against the pictures this project uses.
  2. exact date       the day is known (year, month and day), not only the year or month.
  3. exact location   the lake has coordinates given to at least LOCATION_DECIMALS decimal places
                      (3 places is about 100 m). Neither database has a precision flag, so this rule is ours.
  4. dam type         the lake was dammed by a moraine or by ice. Other types (water pockets inside the
                      glacier, supraglacial ponds, bedrock, landslide, unknown) are left out.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, replace
from datetime import date
from math import cos, hypot, radians
from pathlib import Path

from sailab.ods import read_sheets

GLOBAL_HMA_SHEETS = ("RGI60_13_CentralAsia", "RGI60_14_SouthAsiaWest", "RGI60_15_SouthAsiaEast")
GLOBAL_FIRST_DATA_ROW = 3          # row 0 = column names, row 1 = descriptions, row 2 = unit hints
FIRST_YEAR = 2016                  # "after 2015"
LOCATION_DECIMALS = 3
SAME_EVENT_KM = 2.0                # two records are the same flood if same day and lakes this close
                                   # (the distance the earlier project's labels.mjs used)
DAM_TYPES = {
    "global": {"moraine": "moraine", "ice": "ice"},
    "hma": {"Moraine dammed": "moraine", "Ice dammed": "ice"},
}
FILTERS = ("after 2015", "exact date", "exact location", "moraine or ice dammed")


@dataclass(frozen=True)
class FloodEvent:
    source: str                    # "global" or "hma"
    record_id: str
    country: str
    lake_name: str
    year: int | None
    day: date | None               # only when the exact day is known
    lon: float | None
    lat: float | None
    location_decimals: int         # decimal places of the less precise of the two coordinates
    dam_type: str                  # "moraine", "ice", or the database's own word for anything else


def _number(text: str) -> tuple[float | None, int]:
    """A coordinate written with a decimal comma or point -> (value, decimal places). (None, 0) if not a number."""
    text = text.strip().replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        return None, 0
    return float(text), len(text.split(".")[1]) if "." in text else 0


def _coordinates(lon_text: str, lat_text: str) -> tuple[float | None, float | None, int]:
    lon, lon_places = _number(lon_text)
    lat, lat_places = _number(lat_text)
    if lon is None or lat is None:
        return None, None, 0
    return lon, lat, min(lon_places, lat_places)


def _whole_number(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isdigit() else None


def read_global(path: str | Path) -> list[FloodEvent]:
    """Every record in the global database's High Mountain Asia sheets."""
    sheets = read_sheets(path)
    events = []
    for name in GLOBAL_HMA_SHEETS:
        rows = sheets[name]
        header = rows[0]
        column = {title: i for i, title in enumerate(header)}
        for number, raw in enumerate(rows[GLOBAL_FIRST_DATA_ROW:], start=GLOBAL_FIRST_DATA_ROW):
            row = raw + [""] * (len(header) - len(raw))
            if not any(cell.strip() for cell in row):
                continue
            get = lambda title: row[column[title]].strip()   # noqa: E731
            when = get("Date") or get("Date_Min")
            year_match = re.match(r"(\d{4})", when)
            day = None
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", get("Date")):
                try:
                    day = date.fromisoformat(get("Date"))
                except ValueError:
                    day = None
            lon, lat, places = _coordinates(get("Longitude"), get("Latitude"))
            dam = get("Lake_type")
            events.append(FloodEvent("global", f"{name}:{number}", get("Country"), get("Lake") or get("Glacier"),
                                     int(year_match.group(1)) if year_match else None, day, lon, lat, places,
                                     DAM_TYPES["global"].get(dam, dam or "not given")))
    return events


def read_hma(path: str | Path) -> list[FloodEvent]:
    """Every record in the High Mountain Asia database (HMAGLOFDB.csv)."""
    events = []
    # The file is not UTF-8: it has Windows-1252 characters (e.g. byte 0x96, an en dash, in the references).
    # Its schema.ini does not name an encoding, so cp1252 is used; only the text columns are affected.
    with open(path, encoding="cp1252", newline="") as handle:
        for row in csv.DictReader(handle):
            year = _whole_number(row["Year_exact"]) or _whole_number(row["Year_approx"])
            exact_year, month, day_of_month = (_whole_number(row[k]) for k in ("Year_exact", "Month", "Day"))
            day = None
            if exact_year and month and day_of_month:
                try:
                    day = date(exact_year, month, day_of_month)
                except ValueError:
                    day = None
            lon, lat, places = _coordinates(row["Lon_lake"], row["Lat_lake"])
            dam = row["Lake_type"].strip()
            events.append(FloodEvent("hma", row["GF_ID"].strip(), row["Country"].strip(),
                                     row["Lake_name"].strip() or row["Glacier_name"].strip(), year, day, lon, lat,
                                     places, DAM_TYPES["hma"].get(dam, dam or "not given")))
    return events


def passes(event: FloodEvent, step: str) -> bool:
    """Does the event pass this one filter? (Each filter on its own; apply_filters() chains them.)"""
    if step == "after 2015":
        return event.year is not None and event.year >= FIRST_YEAR
    if step == "exact date":
        return event.day is not None
    if step == "exact location":
        return event.lon is not None and event.location_decimals >= LOCATION_DECIMALS
    if step == "moraine or ice dammed":
        return event.dam_type in ("moraine", "ice")
    raise ValueError(f"unknown filter {step!r}")


def apply_filters(events: list[FloodEvent]) -> tuple[list[tuple[str, int, int]], list[FloodEvent]]:
    """Run the filters in order. Returns ([(step, events left, of which in Pakistan)], events left at the end)."""
    remaining = list(events)
    steps = [("all records", len(remaining), sum(e.country == "Pakistan" for e in remaining))]
    for step in FILTERS:
        remaining = [e for e in remaining if passes(e, step)]
        steps.append((step, len(remaining), sum(e.country == "Pakistan" for e in remaining)))
    return steps, remaining


def km_between(a: FloodEvent, b: FloodEvent) -> float:
    """Straight-line distance between two lakes (a flat-earth approximation, fine within a few km)."""
    north = (b.lat - a.lat) * 110.574
    east = (b.lon - a.lon) * 111.32 * cos(radians(a.lat))
    return hypot(north, east)


def merge(global_events: list[FloodEvent], hma_events: list[FloodEvent]) -> tuple[list[FloodEvent], int]:
    """One list of floods from both databases. A flood in both (same day, lakes within SAME_EVENT_KM)
    is kept once, as the HMA record. Returns (merged list, how many were found in both)."""
    merged = list(hma_events)
    in_both = 0
    for g in global_events:
        twin = next((h for h in hma_events if h.day == g.day and km_between(g, h) <= SAME_EVENT_KM), None)
        if twin is None:
            merged.append(g)
        else:
            in_both += 1
            if twin.source == "hma":
                merged[merged.index(twin)] = replace(twin, source="both")
    return merged, in_both
