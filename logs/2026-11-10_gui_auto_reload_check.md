# GUI automatic reload: real-server check (2026-11-10, about 08:23 UTC)

Setup: uvicorn on 127.0.0.1:8004 with a scratch copy of sailab_glof.db as the source
(SAILAB_SOURCE_DB in the scratchpad, never the repository file) and SAILAB_AUTO_RELOAD_SECONDS=10
(the default is 60). A dashboard tab was open in the browser pane and marked with a JavaScript flag.

At 08:23:39 UTC the scratch source was replaced by a database with 2 more scenes (1,053 -> 1,055),
standing in for a `git pull`. `/api/provenance` was read every 5 s:

```
08:23:39 copied 08:23:27  current   last_reload None
08:23:44 copied 08:23:27  current   last_reload None
08:23:49 copied 08:23:27  waiting   last_reload None      <- change seen, not copied yet
08:23:54 copied 08:23:27  waiting   last_reload None
08:23:59 copied 08:23:57  reloaded  last_reload 08:23:57  <- unchanged on the next check, passed SQLite quick_check, copied
```

About 30 s later the open tab, untouched, had reloaded itself (the JavaScript flag was gone) and showed
"Scenes recorded 1055", "copied 10 Nov 2026, 08:23 UTC".

Delay from file change to new numbers on screen: up to 2 x check interval + 30 s page poll
(default 60 s checks: about 2.5 minutes at most).

Automated tests: tests/test_webapp_scenes.py (auto-reload section, 8 tests): waits one check, never
copies a still-changing or broken file, waits for a running live check, reports a missing source, the
watcher thread reloads by itself, pages carry the refresh script and previews do not.
Full suite after the change: 246 passed.
