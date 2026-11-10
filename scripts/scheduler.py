"""Local scheduler: runs the pipeline on a timer, with no GitHub Actions and no bot.

Start it once and leave it running:

    python scripts/scheduler.py

It wakes up every SAILAB_RUN_INTERVAL_HOURS (default 24), runs the test suite, then runs
scripts/run_once.py, which signs in to Earth Engine with the key named in .env and writes to
sailab_glof.db and logs/runs/ on this machine. Then it sleeps until the next wake-up.
Nothing is committed or pushed: the database on this machine is the record.

Keys are read from the .env file next to this repository (see .env.example); a variable that is
already set in the environment wins over the file. The key never goes to the test step.

Each run is a separate process, so a crashed run cannot stop the scheduler, and every run still
gets its own log file in logs/runs/ exactly as before.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, MutableMapping

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env"
SCHEDULER_LOG = REPO / "logs" / "scheduler.log"
DEFAULT_KEY_FILE = Path("~/.config/sailab/ee-key.json").expanduser()   # same default as earth_engine_client

DEFAULT_INTERVAL_HOURS = 24.0
DEFAULT_RETRY_MINUTES = 30.0
# After this many failed runs in a row, stop retrying early and wait the full interval again, so a
# revoked key cannot fill run_log with a failure row every half hour.
MAX_QUICK_RETRIES = 3
KEY_VARIABLES = ("EE_SERVICE_ACCOUNT_KEY", "EE_SERVICE_ACCOUNT_KEY_FILE")

EXIT_TESTS_FAILED = 3

log = logging.getLogger("scheduler")


# ---------------------------------------------------------------------------
# Keys and settings
# ---------------------------------------------------------------------------
def load_env_file(path: Path, environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Read KEY=VALUE lines from a .env file into the environment. Returns the names it set.

    Blank lines and lines starting with # are skipped; one pair of surrounding quotes is removed.
    A variable that is already set is left alone, so a real environment variable beats the file.
    """
    environ = os.environ if environ is None else environ
    if not path.is_file():
        return []
    loaded: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and name not in environ:
            environ[name] = value
            loaded.append(name)
    return loaded


def key_problem(environ: Mapping[str, str] | None = None) -> str | None:
    """None if an Earth Engine key can be found; otherwise a plain sentence saying what is missing."""
    environ = os.environ if environ is None else environ
    if environ.get("EE_SERVICE_ACCOUNT_KEY"):
        return None
    key_file = Path(environ.get("EE_SERVICE_ACCOUNT_KEY_FILE") or DEFAULT_KEY_FILE).expanduser()
    if key_file.is_file():
        return None
    return (f"no Earth Engine key found: set EE_SERVICE_ACCOUNT_KEY_FILE (or EE_SERVICE_ACCOUNT_KEY) "
            f"in {ENV_FILE}; looked for a key file at {key_file}")


def _number_setting(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = float(raw)   # a typo in .env should stop the scheduler at start-up, not be ignored
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0, got {raw!r}")
    return value


# ---------------------------------------------------------------------------
# One wake-up
# ---------------------------------------------------------------------------
def run_cycle(run_tests: bool = True, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
              environ: Mapping[str, str] | None = None) -> int:
    """Tests first (a broken build must not write to the database), then one pipeline run.

    Returns 0 for a clean run, EXIT_TESTS_FAILED if the tests failed (pipeline not started),
    otherwise run_once.py's own exit code (1 = an error recorded in run_log).
    """
    environ = dict(os.environ if environ is None else environ)
    if run_tests:
        # The key is kept out of the test step, as it was on GitHub: tests never need it.
        test_env = {name: value for name, value in environ.items() if name not in KEY_VARIABLES}
        tests = runner([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=REPO, env=test_env)
        if tests.returncode != 0:
            log.error("tests failed (exit %s): pipeline NOT run", tests.returncode)
            return EXIT_TESTS_FAILED
    pipeline = runner([sys.executable, str(REPO / "scripts" / "run_once.py")], cwd=REPO, env=environ)
    return pipeline.returncode


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
def next_wait_seconds(exit_code: int, failures_in_a_row: int, interval_s: float, retry_s: float) -> float:
    """Full interval after a clean run; a shorter retry after a failure, for the first few failures only."""
    if exit_code != 0 and failures_in_a_row <= MAX_QUICK_RETRIES:
        return min(retry_s, interval_s)
    return interval_s


def run_forever(interval_s: float, retry_s: float, run_tests: bool = True,
                cycle: Callable[[bool], int] = run_cycle, sleep: Callable[[float], None] = time.sleep,
                max_cycles: int | None = None) -> int:
    """Run, sleep, wake, run again. Returns the last cycle's exit code (only when max_cycles is set)."""
    failures_in_a_row = 0
    exit_code = 0
    done = 0
    while max_cycles is None or done < max_cycles:
        log.info("wake-up %d: starting a run", done + 1)
        try:
            exit_code = cycle(run_tests)
        except Exception:   # the scheduler itself must survive anything a run throws at it
            log.exception("the run could not be started")
            exit_code = 1
        done += 1
        failures_in_a_row = 0 if exit_code == 0 else failures_in_a_row + 1
        log.info("run finished: %s", "OK" if exit_code == 0 else f"FAILED (exit {exit_code})")
        if max_cycles is not None and done >= max_cycles:
            break
        wait = next_wait_seconds(exit_code, failures_in_a_row, interval_s, retry_s)
        wake_at = datetime.now(timezone.utc) + timedelta(seconds=wait)
        log.info("sleeping %.1f h; next wake-up at %s UTC", wait / 3600, wake_at.strftime("%Y-%m-%d %H:%M"))
        sleep(wait)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    load_env_file(ENV_FILE)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval-hours", type=float,
                        default=_number_setting(os.environ, "SAILAB_RUN_INTERVAL_HOURS", DEFAULT_INTERVAL_HOURS),
                        help="hours between runs (default: SAILAB_RUN_INTERVAL_HOURS or 24)")
    parser.add_argument("--retry-minutes", type=float,
                        default=_number_setting(os.environ, "SAILAB_RETRY_MINUTES", DEFAULT_RETRY_MINUTES),
                        help="minutes to wait after a failed run (default: SAILAB_RETRY_MINUTES or 30)")
    parser.add_argument("--once", action="store_true", help="do one run now and exit (no sleeping)")
    parser.add_argument("--skip-tests", action="store_true", help="do not run the test suite before each run")
    args = parser.parse_args(argv)
    if args.interval_hours <= 0 or args.retry_minutes <= 0:
        parser.error("--interval-hours and --retry-minutes must be greater than 0")

    SCHEDULER_LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(SCHEDULER_LOG), logging.StreamHandler(sys.stdout)],
    )
    logging.Formatter.converter = time.gmtime   # UTC, like the run logs

    problem = key_problem()
    if problem:
        log.error(problem)
        return 2
    log.info("scheduler started: a run every %.2f h, retry after %.0f min on failure, tests %s",
             args.interval_hours, args.retry_minutes, "skipped" if args.skip_tests else "run first")
    try:
        return run_forever(args.interval_hours * 3600, args.retry_minutes * 60, run_tests=not args.skip_tests,
                           max_cycles=1 if args.once else None)
    except KeyboardInterrupt:
        log.info("stopped by hand (Ctrl+C)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
