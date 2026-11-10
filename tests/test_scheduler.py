"""The local scheduler (scripts/scheduler.py): key loading, the test gate, and the sleep/wake loop.

No real process is started and no real sleeping happens: the runner and sleep are replaced.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "sailab_scheduler", Path(__file__).resolve().parent.parent / "scripts" / "scheduler.py")
scheduler = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scheduler)


# --- .env loading -------------------------------------------------------------------------------
def test_env_file_sets_variables_and_skips_comments_and_blanks(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# a comment\n\nEE_SERVICE_ACCOUNT_KEY_FILE=C:\\keys\\ee.json\nSAILAB_RUN_INTERVAL_HOURS = 6\n")
    environ: dict[str, str] = {}
    assert scheduler.load_env_file(env_file, environ) == ["EE_SERVICE_ACCOUNT_KEY_FILE", "SAILAB_RUN_INTERVAL_HOURS"]
    assert environ == {"EE_SERVICE_ACCOUNT_KEY_FILE": "C:\\keys\\ee.json", "SAILAB_RUN_INTERVAL_HOURS": "6"}


def test_env_file_strips_one_pair_of_quotes_and_keeps_json_intact(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('A="quoted value"\nEE_SERVICE_ACCOUNT_KEY={"client_email": "x@y", "project_id": "p"}\n')
    environ: dict[str, str] = {}
    scheduler.load_env_file(env_file, environ)
    assert environ["A"] == "quoted value"
    assert environ["EE_SERVICE_ACCOUNT_KEY"] == '{"client_email": "x@y", "project_id": "p"}'


def test_real_environment_variable_beats_the_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SAILAB_RUN_INTERVAL_HOURS=6\n")
    environ = {"SAILAB_RUN_INTERVAL_HOURS": "12"}
    assert scheduler.load_env_file(env_file, environ) == []
    assert environ["SAILAB_RUN_INTERVAL_HOURS"] == "12"


def test_missing_env_file_is_not_an_error(tmp_path):
    assert scheduler.load_env_file(tmp_path / "nope.env", {}) == []


# --- key check ----------------------------------------------------------------------------------
def test_key_problem_none_when_key_text_is_set():
    assert scheduler.key_problem({"EE_SERVICE_ACCOUNT_KEY": "{}"}) is None


def test_key_problem_none_when_key_file_exists(tmp_path):
    key = tmp_path / "ee-key.json"
    key.write_text("{}")
    assert scheduler.key_problem({"EE_SERVICE_ACCOUNT_KEY_FILE": str(key)}) is None


def test_key_problem_names_the_missing_file(tmp_path):
    missing = tmp_path / "gone.json"
    problem = scheduler.key_problem({"EE_SERVICE_ACCOUNT_KEY_FILE": str(missing)})
    assert problem is not None and str(missing) in problem


# --- one wake-up --------------------------------------------------------------------------------
def _recording_runner(return_codes):
    calls = []

    def runner(command, cwd=None, env=None):
        calls.append(SimpleNamespace(command=command, env=env))
        return SimpleNamespace(returncode=return_codes[len(calls) - 1])

    return runner, calls


def test_cycle_runs_tests_then_pipeline_and_keeps_the_key_out_of_the_tests():
    runner, calls = _recording_runner([0, 0])
    environ = {"EE_SERVICE_ACCOUNT_KEY": "secret", "EE_SERVICE_ACCOUNT_KEY_FILE": "k.json", "PATH": "p"}
    assert scheduler.run_cycle(True, runner, environ) == 0
    assert len(calls) == 2
    assert "pytest" in calls[0].command and calls[0].env == {"PATH": "p"}
    assert calls[1].command[-1].endswith("run_once.py") and calls[1].env == environ


def test_cycle_does_not_run_the_pipeline_when_tests_fail():
    runner, calls = _recording_runner([1])
    assert scheduler.run_cycle(True, runner, {}) == scheduler.EXIT_TESTS_FAILED
    assert len(calls) == 1


def test_cycle_returns_the_pipeline_exit_code_and_can_skip_tests():
    runner, calls = _recording_runner([1])
    assert scheduler.run_cycle(False, runner, {}) == 1
    assert len(calls) == 1 and calls[0].command[-1].endswith("run_once.py")


# --- the loop -----------------------------------------------------------------------------------
def test_loop_sleeps_the_full_interval_after_a_clean_run():
    sleeps: list[float] = []
    assert scheduler.run_forever(3600, 60, cycle=lambda run_tests: 0, sleep=sleeps.append, max_cycles=3) == 0
    assert sleeps == [3600, 3600]   # no sleep after the last cycle


def test_loop_retries_sooner_after_a_failure_then_goes_back_to_the_interval():
    codes = iter([1, 0, 0])
    sleeps: list[float] = []
    scheduler.run_forever(3600, 60, cycle=lambda run_tests: next(codes), sleep=sleeps.append, max_cycles=3)
    assert sleeps == [60, 3600]


def test_loop_stops_quick_retries_after_too_many_failures_in_a_row():
    sleeps: list[float] = []
    cycles = scheduler.MAX_QUICK_RETRIES + 3
    scheduler.run_forever(3600, 60, cycle=lambda run_tests: 1, sleep=sleeps.append, max_cycles=cycles)
    assert sleeps == [60] * scheduler.MAX_QUICK_RETRIES + [3600] * 2


def test_loop_survives_a_cycle_that_raises():
    def exploding(run_tests):
        raise RuntimeError("boom")

    sleeps: list[float] = []
    assert scheduler.run_forever(3600, 60, cycle=exploding, sleep=sleeps.append, max_cycles=2) == 1
    assert sleeps == [60]


def test_retry_wait_is_never_longer_than_the_interval():
    assert scheduler.next_wait_seconds(1, 1, interval_s=600, retry_s=1800) == 600


def test_bad_interval_setting_is_refused():
    with pytest.raises(ValueError):
        scheduler._number_setting({"SAILAB_RUN_INTERVAL_HOURS": "0"}, "SAILAB_RUN_INTERVAL_HOURS", 24.0)
