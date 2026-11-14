"""Count the past floods in both databases after every filter, and save the usable ones.

    python scripts/count_flood_events.py

Reads the two published files (paths below; they live outside the repository, in D:\\University\\FYP\\data\\events),
prints the count after each filter for each database, merges the two lists (a flood in both is kept once),
and writes:
  logs/<date>_flood_event_counts.md   the counts, per filter and per database
  data/flood_events_usable.csv        the floods that pass every filter, from both databases

Every number comes from the files; nothing is typed in by hand. See sailab/flood_events.py for the rules.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sailab import flood_events as fe  # noqa: E402

EVENTS_DIR = Path(r"D:\University\FYP\data\events")
GLOBAL_FILE = EVENTS_DIR / "glofdatabase_v4-2.ods"
HMA_FILE = EVENTS_DIR / "shrestha2023" / "unpacked" / "fidelsteiner-HMAGLOFDB-1d975de" / "Database" / "GLOFs" / "HMAGLOFDB.csv"
OUT_CSV = REPO / "data" / "flood_events_usable.csv"


def counts_table(title: str, steps: list[tuple[str, int, int]]) -> list[str]:
    lines = [f"### {title}", "", "| Step | Floods left | of which in Pakistan | Removed by this step |", "|---|---|---|---|"]
    previous = None
    for step, left, pakistan in steps:
        removed = "-" if previous is None else str(previous - left)
        lines.append(f"| {step} | {left} | {pakistan} | {removed} |")
        previous = left
    return lines + [""]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--global-file", type=Path, default=GLOBAL_FILE)
    parser.add_argument("--hma-file", type=Path, default=HMA_FILE)
    args = parser.parse_args(argv)

    global_events = fe.read_global(args.global_file)
    hma_events = fe.read_hma(args.hma_file)
    global_steps, global_left = fe.apply_filters(global_events)
    hma_steps, hma_left = fe.apply_filters(hma_events)
    merged, in_both = fe.merge(global_left, hma_left)
    pakistan = [e for e in merged if e.country == "Pakistan"]
    outside = len(merged) - len(pakistan)

    lines = [
        "# Past floods usable for the risk model: counts after every filter",
        "",
        f"Written by `scripts/count_flood_events.py` on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC, from these files:",
        f"- Global database (Lützow, Veh, Korup 2023), `{args.global_file.name}`, High Mountain Asia sheets only",
        f"- High Mountain Asia database (Shrestha, Steiner and others 2023), `{args.hma_file.name}` (release v1.3.0)",
        "",
        "Filters, in this order: event year 2016 or later; exact day known; lake coordinates to at least "
        f"{fe.LOCATION_DECIMALS} decimal places (about 100 m); dammed by moraine or ice.",
        "",
        *counts_table("Global database", global_steps),
        *counts_table("High Mountain Asia database", hma_steps),
        "### Both databases together",
        "",
        f"A flood is counted once when both databases have it on the same day for lakes within {fe.SAME_EVENT_KM:g} km.",
        "",
        f"- Usable in the global database: **{len(global_left)}**",
        f"- Usable in the High Mountain Asia database: **{len(hma_left)}**",
        f"- In both: **{in_both}**",
        f"- **Usable floods, counted once: {len(merged)}**",
        f"- of which in Pakistan (never used for training): **{len(pakistan)}**",
        f"- **Left for training, outside Pakistan: {outside}**",
        f"- Dam type of the usable floods: {dict(Counter(e.dam_type for e in merged))}",
        f"- Countries: {dict(Counter(e.country for e in merged).most_common())}",
        "",
        "**What this means for a trained model.** These are counts of flood events, not of training rows. A model",
        "also needs each lake's area history from before its flood, which has to be measured from satellite",
        "pictures first; that step has not been done.",
    ]
    out_md = REPO / "logs" / f"{datetime.now(timezone.utc):%Y-%m-%d}_flood_event_counts.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "record_id", "country", "lake_name", "date", "lon", "lat", "dam_type"])
        for e in sorted(merged, key=lambda e: (e.day, e.country)):
            writer.writerow([e.source, e.record_id, e.country, e.lake_name, e.day.isoformat(), e.lon, e.lat, e.dam_type])

    for title, steps in (("Global database", global_steps), ("High Mountain Asia database", hma_steps)):
        print(title)
        for step, left, pk in steps:
            print(f"  {step:24s} {left:5d}   (Pakistan {pk})")
    print(f"Usable, counted once: {len(merged)} ({in_both} in both); Pakistan {len(pakistan)}; outside Pakistan {outside}")
    print(f"Written: {out_md}\nWritten: {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
