"""The single-job runner a worker uses (job.py)."""

import json

import pytest

from arena.job import JobError, check_spec, run_job
from arena.voices import SyntheticVoice

AGENT = {"type": "elevenlabs", "agent_id": "abc"}


def test_spec_defaults():
    job = check_spec({"job_id": "a1", "agent": AGENT})
    assert job == {"job_id": "a1", "agent": AGENT, "repeats": 1, "scenarios": None}


@pytest.mark.parametrize("spec", [
    [],
    {"agent": AGENT},
    {"job_id": "../etc", "agent": AGENT},                       # ends up in a path
    {"job_id": "a", "agent": {"agent_id": "abc"}},
    {"job_id": "a", "agent": {"type": "local"}},                # the worker has no local models
    {"job_id": "a", "agent": {"type": "fake"}},                 # only with allow_test_agents
    {"job_id": "a", "agent": {**AGENT, "api_key": "sk-123"}},   # keys never travel in the job
    {"job_id": "a", "agent": {**AGENT, "clock": "virtual"}},
    {"job_id": "a", "agent": AGENT, "repeats": 50},
    {"job_id": "a", "agent": AGENT, "scenarios": "all"},
])
def test_bad_specs_are_refused(spec):
    with pytest.raises(JobError):
        check_spec(spec)


def test_fake_agent_allowed_for_trials():
    assert check_spec({"job_id": "a", "agent": {"type": "fake"}}, allow_test_agents=True)


def test_refused_job_is_reported_not_raised(tmp_path, params):
    status = run_job({"job_id": "a", "agent": {"type": "local"}}, tmp_path, params)
    assert status["state"] == "failed" and "agent type" in status["error"]
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "failed"


def test_job_end_to_end(tmp_path, params):
    """One real-time call with a fake agent: every output file is written."""
    spec = {"job_id": "t1", "agent": {"type": "fake", "response_delay_ms": 400, "reply_ms": 1500},
            "scenarios": ["scenarios/numbers_order_double_en.yaml"]}
    status = run_job(spec, tmp_path, params, allow_test_agents=True, caller_voice=SyntheticVoice(),
                     log=lambda *_: None)
    assert status["state"] == "done", status
    assert status["calls"] == 1
    for name in ("status.json", "score.json", "summary.json", "index.html",
                 "runs/rep1/numbers_order_double_en/recording.wav"):
        assert (tmp_path / name).exists(), name
    score = json.loads((tmp_path / "score.json").read_text())
    delay = score["reps"][0]["calls"][0]["measures"]["turns"][0]["response_delay_ms"]
    assert abs(delay - 400) <= 60
    assert "job-t1" in (tmp_path / "index.html").read_text()
