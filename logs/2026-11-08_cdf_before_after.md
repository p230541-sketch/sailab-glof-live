# Backfill before vs after checks C, D, F (2026-11-08)

Before: run_log 2, archived at data/archive_v1/sailab_glof_v1_before_CDF.db. After: run_log 3 (live DB).
Same 611 scenes and 254 downloads in both (2023-01-05 .. 2026-11-05).

| | KRB before | KRB after | ATS before | ATS after |
|---|---|---|---|---|
| ok measurements | 38 | 20 | 66 | 25 |
| ok range (ha) | 167.82-462.88 | 198.31-257.83 | 0.14-110.55 | 105.16-107.17 |
| ok mean (ha) | 260.66 | 244.19 | 101.53 | 106.10 |
| risk scores 'ok' | 26 | 8 | 44 | 11 |
| largest abs(score) | 49.57 | 2.96 | 40.64 | 1.74 |

Implausible values removed: KRB 6 of 9, ATS 10 of 10.
Still accepted, likely NDWI under-detection (problem 4, not addressed): KRB 2024-08-02 210.61, 2025-07-05 221.71,
2025-08-12 198.31 (this one gives the largest remaining score, -2.96).

Cost (over-caution): plausible v1 values now rejected: KRB 12 (7 by D, 5 by C), ATS 31 (19 by C, 12 by D).
Several were rejected for 1-15 touching pixels (SCL is a 20 m product; edge labels are noisy), and in
spring/autumn snow on the shore touches a lake that is itself fully visible.
