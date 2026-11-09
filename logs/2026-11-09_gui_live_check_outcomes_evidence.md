# Live-check outcomes: evidence (written 2026-11-09)

## Outcome A: no new scene. Re-run now with the real app and real Earth Engine, because the
first run of this test (2026-11-08 20:11 UTC) left no file: its working copy was deleted for the cold run-through.

- POST /live/check at 2026-11-09T13:32:45+00:00: HTTP 303 -> /live
- outcome status: **no_new_scene**, took 11 s, errors: None
- RunResult: run 9, lakes 2, new scenes recorded 0, downloaded 0
- run_log row written in the app's working copy: (9, '2026-11-09T13:32:45+00:00', '2026-11-09T13:32:56+00:00', 2, 0, None)
- the pipeline's own log lines shown on the page:
    13:32:45 INFO run 9 started
    13:32:49 INFO signed in to Earth Engine as sailab-glof-bot@kaarigar-507118.iam.gserviceaccount.com
    13:32:51 INFO KRB: 1 scenes listed after 2026-11-04
    13:32:51 INFO KRB 20261105T055021_20261105T055015_T43SCA: already recorded, skipped
    13:32:52 INFO KRB: 1 radar scenes listed after 2026-10-27
    13:32:53 INFO KRB S1D_IW_GRDH_1SDV_20261028T130519_20261028T130544_005216_009E76_3B4B: already recorded, skipped
    13:32:55 INFO ATS: 1 scenes listed after 2026-11-04
    13:32:55 INFO ATS 20261105T055021_20261105T055015_T43SCA: already recorded, skipped
    13:32:56 INFO ATS: 1 radar scenes listed after 2026-10-27
    13:32:56 INFO ATS S1D_IW_GRDH_1SDV_20261028T130454_20261028T130519_005216_009E76_6D2E: already recorded, skipped
    13:32:56 INFO run 9 finished: RunResult(run_id=9, lakes_processed=2, scenes_recorded=0, scenes_downloaded=0, measurements=0, risk_scores=0, errors=None, notes=[])
- page shows: "Results are written to this laptop's working copy of the database only, never to the published record that the nightly run commits. From October to May both lakes are usually cloud..."

## Outcome B: failure (network cut). Run on 2026-11-08 at 20:16 UTC by a separate app instance (port 8001)
started with HTTPS_PROXY/HTTP_PROXY pointing at 127.0.0.1:9, where nothing listens: the app's HTTPS connections
fail at the connection level (not a typed-in message). Artifacts copied from that instance's working directory:

- live_checks.json: [{"run_id": 6, "status": "failed", "started_at": "2026-11-08T20:16:20+00:00", "finished_at": "2026-11-08T20:16:53+00:00"}]
- run_log row in that working copy: id 6, started 2026-11-08T20:16:21+00:00, finished 2026-11-08T20:16:53+00:00, lakes 0, downloads 0
- recorded error (first 400 chars): 'EarthEngineError: Earth Engine sign-in failed for sailab-glof-bot@kaarigar-507118.iam.gserviceaccount.com: ConnectionError: HTTPSConnectionPool(host=\'oauth2.googleapis.com\', port=443): Max retries exceeded with url: /token (Caused by ProxyError(\'Unable to connect to proxy\', NewConnectionError("HTTPSConnection(host=\'127.0.0.1\', port=9): Failed to establish a new connection: [Errno 111] Connection r'

## Outcome C: new scenes found and measured. Port 8002, copy rewound to 2026-08-15, 2026-11-08 20:13-20:14 UTC:
- live_checks.json: [{"run_id": 6, "status": "new_scenes", "started_at": "2026-11-08T20:13:29+00:00", "finished_at": "2026-11-08T20:14:50+00:00"}]
- run_log row in that working copy: (6, '2026-11-08T20:13:29+00:00', '2026-11-08T20:14:50+00:00', 2, 12, None)
- row-by-row and file-by-file comparison with the backfill: logs/2026-11-08_gui_live_check_new_scenes_vs_backfill.log (42/42 rows, 12/12 files identical)

## Correction to Outcome A above
The "page shows" line above quoted the explanatory paragraph by mistake (both start with "Result"). The result banner is:
- Not captured from the page in this run. The template text for status no_new_scene (webapp/templates/live.html line 38) is: "No new scene for either lake since the newest one already stored. Earth Engine answered normally; Sentinel-2 passes about every 2 to 5 days and new scenes take some hours to appear."
- That this banner is actually rendered for that status is checked by tests/test_webapp_live.py::test_no_new_scene_says_so (passing). The run itself (status no_new_scene, run_log row 9, 11 s) is recorded above.
