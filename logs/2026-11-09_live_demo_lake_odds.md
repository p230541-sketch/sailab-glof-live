# Which lake has better odds of a clean optical scene for the live-check demo?

Generated 2026-11-09T15:05:15Z from sailab_glof.db (commit 88d4a87) with the SQL shown. Read-only.

## 1. Optical scenes in Oct-Dec, all years (2023-2025, Oct-Nov 2026)

```sql
select l.code, substr(s.acquired_at,6,2) month, count(*) scenes, sum(s.cloud_fraction <= 10) clear_10pct, sum(m.status='ok') usable, sum(m.status='insufficient_observation') refused from scene s join lake l on l.id=s.lake_id left join measurement m on m.scene_id=s.id where s.source='sentinel-2' and substr(s.acquired_at,6,2) in ('10','11','12') group by 1,2;
```
```
code  month  scenes  clear_10pct  usable  refused
----  -----  ------  -----------  ------  -------
ATS   10     30      10           0       10     
ATS   11     21      12           0       12     
ATS   12     18      12           0       12     
KRB   10     31      12           0       12     
KRB   11     21      13           0       13     
KRB   12     18      11           0       11     
```

## 2. Last usable optical measurement of each year

```sql
select l.code, substr(s.acquired_at,1,4) year, max(s.acquired_at) last_usable_optical from scene s join lake l on l.id=s.lake_id join measurement m on m.scene_id=s.id where m.status='ok' and m.sensor='optical' group by 1,2;
```
```
code  year  last_usable_optical      
----  ----  -------------------------
ATS   2023  2023-09-12T05:59:03+00:00
ATS   2024  2024-08-12T05:59:02+00:00
ATS   2025  2025-09-01T05:59:16+00:00
ATS   2026  2026-08-27T05:58:56+00:00
KRB   2023  2023-09-12T05:59:03+00:00
KRB   2024  2024-09-21T05:58:54+00:00
KRB   2025  2025-09-01T05:59:16+00:00
KRB   2026  2026-09-06T05:58:56+00:00
```

## 3. Why the clear Oct-Dec optical scenes were refused (backfill run log)

```
grep insufficient_observation logs/runs/2026-11-08T112314Z_backfill.log, scenes dated Oct-Dec:
      9 ATS centre pixel
     16 ATS check C
      7 ATS check D
      2 ATS lake region
     15 KRB centre pixel
      7 KRB check C
      6 KRB check D
      8 KRB lake region
```

## 4. Radar passes in Oct-Dec

```sql
select l.code, substr(s.acquired_at,6,2) month, count(*) passes, sum(m.status='ok') usable from scene s join lake l on l.id=s.lake_id join measurement m on m.scene_id=s.id where s.source='sentinel-1' and substr(s.acquired_at,6,2) in ('10','11','12') group by 1,2;
```
```
code  month  passes  usable
----  -----  ------  ------
ATS   10     21      20    
ATS   11     14      14    
ATS   12     16      16    
KRB   10     21      21    
KRB   11     14      14    
KRB   12     16      16    
```

## Conclusion

- **Clear sky (≤ 10 % cloud over the lake), Oct-Dec:** Karambar 36 of 70 scenes (51 %), Atro Sar 34 of 69 (49 %).
  November alone: Karambar 13 of 21, Atro Sar 12 of 21. The difference is one or two scenes: **no real
  difference between the lakes.**
- **Usable optical measurement, Oct-Dec: 0 for both lakes, in every year on record.** Every clear scene was
  refused, mostly because the lake centre is not water (frozen: NDWI ≤ 0.2) or snow/ice touches the lake
  (check C). In no year was there a usable optical value after mid-September (latest: 21 Sep 2024, Karambar).
- **So neither lake has real odds of a clean, measurable optical scene for a November-December demo.** The
  realistic live-check results are "no new scene" or "new scene: too cloudy / refused (frozen)". Picking one
  lake would not change that; the button checks both anyway.
- **Radar** was usable in 101 of 102 Oct-Dec passes, so a new radar pass would almost certainly be measured.
  But winter radar values are unvalidated (they probably measure the frozen surface), radar is not scored, and
  on 9 Nov Earth Engine had no Sentinel-1 pass for these lakes newer than 28 Oct (to be re-checked).
