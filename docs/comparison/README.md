# Built screens vs the reference designs (2026-11-08)

Each image in this folder puts a reference design (left) next to the built screen (right), both at
1600 px wide. The built screens show real data from `sailab_glof.db`; the references show the design's
sample data.

## Matched from the references
- Colours (measured from the reference PNGs): header `#1f4e5f`, primary `#0e6b5e`, banner `#fff3cc`
  with `#9a7300` stripe, page `#f3f6f8`, card border `#dfe4e9`, optical points `#1e4e8c`.
- Layout: top bar, yellow banner, left navigation, KPI row of five cards, map + list row, cards with the
  same radius, tables with the same header style, monospace codes and dates.
- Lake Detail: header card, lake-extent chart with range selector, a "why this score" panel, three
  context panels, observation log with date / sensor / cloud / extent / quality.
- The three preview screens follow their references closely (they reuse the design's sample data).

## Different on purpose (because the real data is different)
| Reference shows | Built screen shows | Why |
|---|---|---|
| 33 lakes, Critical 0.86, tiers, 0.60 threshold bar | 2 lakes, "Deviation −0.96" or "Insufficient history", no tiers or threshold | The 0–1 score and tiers come from the trained model, which is not built. The real score is a seasonal deviation. |
| "2 advisories need your review", bell with badge, Advisories menu | "No usable observation in 7 days for 2 of 2 lakes" banner; previews in their own section | Alerting is not built; the banner states a real fact from the data. |
| OpenStreetMap basemap with rivers | Plain latitude/longitude grid with the real lake positions | A basemap needs an internet connection; only the live check may use the network. |
| "Ranked by risk" | "Lakes" in database order | Deviation scores are not danger levels, so ranking by them would mislead. |
| Sentinel-1 radar points, "no usable observation" band | Only Sentinel-2 points; every scene shown as a tick (measured / refused / too cloudy) | Radar is not built; gaps are shown as the real scenes that caused them. |
| Dam and glacier, terrain, weather values | Same panels, dashed, "No data: not part of this build" | Agreed with the project owner: keep the design intent visible without inventing values. |
| "Sample data" chip in the header | "Data: commit …, copied …" chip | Shows exactly which published database state is on screen. |
| Sign-in screen | No sign-in | Agreed with the project owner: no real accounts exist, so a login would only look like security. |
| (not in the references) | Live check page; real Sentinel-2 image with the measured outline | Added by the GUI brief; both use real data only. |
