"""Run one test job: one agent through the scenarios, scored, with a results page.

This is what a worker runs for each request to test an agent. It is the
pipeline's run, score and report steps for a single agent, writing everything
into one folder instead of the repository's results/ and docs/:

    <out>/status.json    queued -> running -> done or failed, with the error if any
    <out>/runs/          recording.wav and timeline.json for every call
    <out>/score.json     every measurement
    <out>/summary.json   the headline numbers
    <out>/index.html     the results page, with audio/ beside it

A job is described by a small JSON document:

    {"job_id": "a1b2c3",
     "agent": {"type": "elevenlabs", "agent_id": "...", "label": "My agent"},
     "scenarios": ["scenarios/barge_in_*.yaml"],     (optional, default: all)
     "repeats": 1}                                   (optional, default: 1)

API keys are never part of the job. Each platform adapter reads its key from
an environment variable (see COMMERCIAL.md), and nothing here writes the
environment anywhere.
"""

import copy
import json
import os
import re
import traceback
from datetime import UTC, datetime
from pathlib import Path

from arena.agents.base import AGENT_TYPES
from arena.scenario import load_scenarios

# Agents a job may ask for. The local baseline needs speech models and a
# language model the worker does not carry.
PLATFORM_TYPES = ("elevenlabs", "vapi", "retell", "smallest")
# Stand-in agents for trying the worker out without a platform account.
TEST_TYPES = ("fake",)

JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_REPEATS = 3
# Settings that would let a job change how the run itself is carried out.
RESERVED = ("clock", "repeats", "calibration", "untested")


class JobError(ValueError):
    """The job description is not acceptable."""


def check_spec(spec: dict, allow_test_agents: bool = False) -> dict:
    """Return the job with defaults filled in, or raise JobError saying what is wrong."""
    if not isinstance(spec, dict):
        raise JobError("the job must be a JSON object")
    job_id = spec.get("job_id")
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise JobError("job_id must be 1 to 64 letters, digits, '-' or '_'")
    agent = spec.get("agent")
    if not isinstance(agent, dict) or "type" not in agent:
        raise JobError("agent must be an object with a type")
    allowed = PLATFORM_TYPES + (TEST_TYPES if allow_test_agents else ())
    if agent["type"] not in allowed or agent["type"] not in AGENT_TYPES:
        raise JobError(f"agent type must be one of: {', '.join(allowed)}")
    for key in agent:
        if key in RESERVED:
            raise JobError(f"agent setting {key!r} cannot be set by a job")
        if "key" in key.lower() or "secret" in key.lower() or "token" in key.lower():
            raise JobError(f"agent setting {key!r} looks like a credential; keys are passed in the "
                           "environment, never in the job")
    repeats = spec.get("repeats", 1)
    if not isinstance(repeats, int) or not 1 <= repeats <= MAX_REPEATS:
        raise JobError(f"repeats must be a whole number from 1 to {MAX_REPEATS}")
    patterns = spec.get("scenarios")
    if patterns is not None and not (isinstance(patterns, list) and all(isinstance(p, str) for p in patterns)):
        raise JobError("scenarios must be a list of file names or patterns")
    return {"job_id": job_id, "agent": dict(agent), "repeats": repeats, "scenarios": patterns}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_job(spec: dict, out_dir: Path, params: dict, *, allow_test_agents: bool = False,
            caller_voice=None, transcriber=None, log=print) -> dict:
    """Run a job from start to finish and return its final status.

    Never raises for a failed job: the failure is written to status.json so
    whoever is waiting for the result can be told.
    """
    out_dir = Path(out_dir)
    status = {"job_id": spec.get("job_id") if isinstance(spec, dict) else None,
              "state": "running", "started_at": now()}
    write_json(out_dir / "status.json", status)
    try:
        job = check_spec(spec, allow_test_agents)
        result = _run(job, out_dir, params, caller_voice, transcriber, log)
        status.update(state="done", **result)
    except JobError as error:
        status.update(state="failed", error=str(error))
    except Exception as error:  # a platform refusing the call, a dropped connection, ...
        log(traceback.format_exc())
        status.update(state="failed", error=f"{type(error).__name__}: {error}")
    status["finished_at"] = now()
    write_json(out_dir / "status.json", status)
    return status


def _run(job: dict, out_dir: Path, params: dict, caller_voice, transcriber, log) -> dict:
    from arena.report import build_result_page, flat_metrics
    from arena.runner import run_agent
    from arena.score import score_agent

    name = f"job-{job['job_id']}"
    config = job["agent"]
    config.setdefault("label", f"{config['type']} agent")
    if config["type"] in TEST_TYPES:
        config.setdefault("tone_only", True)  # a fake agent answers with a tone: nothing to transcribe
    params = copy.deepcopy(params)
    params["agents"][name] = config

    scenarios = load_scenarios(job["scenarios"])
    if not scenarios:
        raise JobError("no scenario matches the job's scenarios list")
    run_dir = run_agent(name, scenarios, params, repeats=job["repeats"], out_dir=out_dir / "runs",
                        caller_voice=caller_voice, log=log)

    if os.environ.get("ARENA_VERSION"):
        # A container has no git checkout, so its image carries the code version.
        manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        manifest["git_commit"] = os.environ["ARENA_VERSION"]
        write_json(run_dir / "run.json", manifest)

    if transcriber is None and not config.get("tone_only"):
        from arena.transcribe import Transcriber

        settings = dict(params["metrics"]["transcriber"])
        if os.environ.get("ARENA_COMPUTE_TYPE"):
            settings["compute_type"] = os.environ["ARENA_COMPUTE_TYPE"]
        transcriber = Transcriber(**settings)
    score = score_agent(run_dir, scenarios, params, transcriber, log=log)
    write_json(out_dir / "score.json", score)
    summary = flat_metrics(score)
    write_json(out_dir / "summary.json", summary)

    note = ""
    if os.environ.get("ARENA_WORKER_LOCATION"):
        note = (f"Calls were placed from {os.environ['ARENA_WORKER_LOCATION']}. Response delay includes the "
                "network time between there and the agent.")
    build_result_page(score, scenarios, params, run_dir, out_dir, note=note)
    return {"calls": summary["calls"], "scenarios_passed": summary["task_completion_count"],
            "scenarios_total": summary["task_completion_of"], "page": "index.html"}
