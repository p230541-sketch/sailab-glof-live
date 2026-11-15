# Deployment: free, no card, runs with the laptop off

Set up on 2026-11-15. Everything runs on GitHub's free services.

| Part | Where | How often |
|---|---|---|
| Nightly pipeline (tests, then fetch, measure and score every lake) | GitHub Actions, `.github/workflows/nightly.yml` | Every night at 18:00 UTC (23:00 Pakistan time); GitHub may start it late |
| Database and run logs | The `data` branch of this repository (`sailab_glof.db`, `runs/`) | Saved after every run, also after a failed one |
| Online dashboard | GitHub Pages, rebuilt after every run by `scripts/export_static_site.py` | After every run |
| Earth Engine key | Repository secret `EE_SERVICE_ACCOUNT_KEY` (encrypted; never in the code) | - |

`main` holds the code only. The nightly run commits only to `data`.

## What the online dashboard does not have

- **Satellite pictures** ("View image"): pictures are measured during the run and then dropped, because
  git cannot hold gigabytes of images. The full picture archive stays on the laptop (`data/backfill/`).
- **Live check** and **Load newer data**: they need a running server; the online pages are plain files.
- **Design previews.**

## On the laptop

Get the latest database from the cloud (for the local web app, which also shows the pictures):

```
git fetch origin data
git show origin/data:sailab_glof.db > sailab_glof.db
.venv\Scripts\python -m uvicorn app:app
```

The laptop must not also run the nightly job, or two copies of the database would drift apart. The Windows
scheduled task "SailAb GLOF" was removed when this deployment went live.

## First set-up (done once)

1. The database is pushed to the `data` branch:
   `git switch --orphan data`, add `sailab_glof.db`, commit, `git push origin data`.
   Until the `data` branch exists the nightly run does nothing (it says so in its log).
2. The secret `EE_SERVICE_ACCOUNT_KEY` holds the whole text of the service-account key file.
3. GitHub Pages is set to "GitHub Actions" as its source.

## Limits (GitHub's free plan)

- A run may last at most 6 hours (a nightly run takes about 5 to 15 minutes).
- Scheduled runs can start late or, rarely, be skipped; the Actions tab shows what really ran.
- In a public repository scheduled runs switch off after 60 days without activity (the nightly commits
  to `data` count as activity; if they ever stop, re-enable the workflow in the Actions tab).
- Files must be under 100 MB each; the database is about 1 MB.
