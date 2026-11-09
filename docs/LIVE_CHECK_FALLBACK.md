# Live check: fallback plan for the defence

The Live check button is the only step in the demo that depends on the network and on Google. This page
says what can go wrong, what the screen shows in each case (already built and tested, nothing new to
build), and what to say out loud.

## What the screen shows (already built)

| What happens | What the page shows | Tested by |
|---|---|---|
| No internet / network blocked | Red box: "The check could not complete. Could not reach Google's servers: this laptop has no internet connection, or the network is blocking it." Below it: how many seconds it took, that nothing was recorded or assumed, the run number, and the exact error under "Technical details". Appears after **about 20-35 s** (Google's client retries: 32 s on 8 Nov, 23 s on 9 Nov). Screenshot: `docs/screenshots/2026-11-09/live_check_failed_no_network.png`. | Real run on port 8001 with a dead proxy, 8 Nov 20:16:21-20:16:53 UTC (`logs/2026-11-09_gui_live_check_outcomes_evidence.md`); `tests/test_webapp_live.py` |
| Earth Engine usage limit | Red box: "Earth Engine declined the request because of a usage limit. Trying again later usually works." | `tests/test_webapp_live.py` (error text from a mocked failure; not seen for real) |
| Key revoked or missing | Red box: "Earth Engine refused the sign-in…" or "No Earth Engine key was found on this laptop." | `tests/test_webapp_live.py` (mocked) |
| Any other error | Red box: "The pipeline reported an error." plus the exact error text | `tests/test_webapp_live.py` (mocked) |
| Earth Engine answers, nothing new | Blue box: "No new scene for either lake" (about 10-20 s) | Real run, 9 Nov 13:32:45 UTC, 11 s (same evidence file) |
| The page itself freezes or the laptop crashes | Nothing: use the backup below | — |

In every failure case the other pages keep showing the last stored data; nothing is filled in.

## Before the defence (the day before)

1. Check `~/.config/sailab/ee-key.json` exists and run one live check at home: it must end in a blue or
   ochre box, not red.
2. Ask the venue for a wired or known-good Wi-Fi connection; have a phone hotspot ready.
3. Have these open in tabs before you start (they need no internet):
   - `logs/2026-11-08_gui_live_check_new_scenes_vs_backfill.log`: the real run that found 42 scenes and measured 12
   - `logs/2026-11-09_gui_live_check_outcomes_evidence.md`: all three tested outcomes with timestamps
   - `docs/screenshots/2026-11-09/live_check.png`
   - the repository's GitHub Actions page (loaded while online)

## During the demo

- Click **Check both lakes now** **once**. If nothing happens for 35 s, still do not click again: a second check
  cannot start while one is running, and the page refreshes itself every 3 s.
- If the red box appears, switch to hotspot **only if the jury agrees to wait**; otherwise go on to the backup.

## What to say if it fails (about 30 seconds)

> "The check could not reach Google. That is the system behaving correctly: it says plainly that it failed,
> it shows the real error underneath, and it does not invent a result. The failure is itself written to the
> run log, the same way run 1 of the pipeline, a real failure, is still in the record.
>
> Here is the same button working on a real run." *(open `logs/2026-11-08_gui_live_check_new_scenes_vs_backfill.log`)*
> "We rewound a copy of the database to 15 August and pressed it. It found 42 real scenes, measured 12, and every
> row and every downloaded file was identical to what the nightly pipeline had stored."
>
> *(then the Actions tab)* "And this is the same pipeline running every night on GitHub, with timestamps from GitHub,
> not from us."

## What to say if it works but finds nothing (the most likely result)

> "Earth Engine answered and there is no new Sentinel-2 pass since the last stored one. In November both lakes
> are frozen: in our whole record, from 2023 to now, there has never been a usable optical measurement of either
> lake between October and December (`logs/2026-11-09_live_demo_lake_odds.md`). So 'nothing new' or 'refused:
> frozen' is the honest expected result, and that is what the system says."

## What not to do

- Do not re-run the check repeatedly hoping for a different answer.
- Do not describe a red box as "a small glitch": say what it says.
- Do not open `sailab_glof.db` and edit anything live.
