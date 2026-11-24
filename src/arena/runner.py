"""Run an agent through the scenarios and save what happened.

Each call produces two files under results/runs/<agent>/rep<k>/<scenario>/:

    recording.wav   two channels: caller on the left, agent on the right
    timeline.json   every caller action with its exact time

Nothing is scored here. Scoring reads these files back (see score.py), so a
metric can be changed and re-applied without making the calls again.
"""

import asyncio
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from arena.agents import build_agent
from arena.audio import read_mono, write_stereo
from arena.caller import Caller
from arena.config import REPO_ROOT
from arena.engine import run_conversation
from arena.noise import at_level
from arena.scenario import scenario_set_version, step_type
from arena.voices import build_voice

RUNS_DIR = REPO_ROOT / "results" / "runs"
CALLER_AUDIO = REPO_ROOT / "data" / "caller_audio"
AGENT_AUDIO = REPO_ROOT / "data" / "agent_audio"
NOISE_DIR = REPO_ROOT / "data" / "noise"


def git_commit() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                                capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
        return commit + ("-dirty" if dirty else "")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def caller_clips(scenario: dict, voice) -> dict[int, np.ndarray]:
    """Audio for every say step, keyed by step index."""
    return {
        i: voice.speak(step["say"], scenario["language"], step.get("spoken"))
        for i, step in enumerate(scenario["steps"])
        if step_type(step) == "say"
    }


def make_caller(scenario: dict, voice, params: dict, noise_dir: Path = NOISE_DIR) -> Caller:
    cp = params["caller"]
    noise = None
    if "noise" in scenario:
        level = cp["voice"].get("level_dbfs", -20) - scenario["noise"]["snr_db"]
        noise = at_level(read_mono(noise_dir / f"{scenario['noise']['kind']}.wav"), level)
    return Caller(
        scenario,
        caller_clips(scenario, voice),
        noise=noise,
        agent_threshold_dbfs=cp["agent_threshold_dbfs"],
        agent_hangover_ms=cp["agent_hangover_ms"],
        end_silence_ms=cp["end_silence_ms"],
        listen_timeout_s=cp["listen_timeout_s"],
        listen_max_s=cp["listen_max_s"],
        trigger_timeout_s=cp["trigger_timeout_s"],
    )


def run_agent(
    name: str,
    scenarios: list[dict],
    params: dict,
    *,
    repeats: int | None = None,
    out_dir: Path | None = None,
    caller_voice=None,
    agent_voice=None,
    log=print,
) -> Path:
    """Run every scenario against one agent, `repeats` times over."""
    config = params["agents"][name]
    clock = config.get("clock", "real")
    repeats = repeats or config.get("repeats", 1)
    out_dir = Path(out_dir or RUNS_DIR / name)
    caller_voice = caller_voice or build_voice(params["caller"]["voice"], CALLER_AUDIO)
    if agent_voice is None and config["type"] == "oracle":
        agent_voice = build_voice(params["agent_voice"], AGENT_AUDIO)
    context = {"agent_voice": agent_voice, "checkin_text": params["checkin_text"], "params": params}

    agent = build_agent(config)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    for rep in range(1, repeats + 1):
        for n, scenario in enumerate(scenarios, 1):
            call_dir = out_dir / f"rep{rep}" / scenario["id"]
            caller = make_caller(scenario, caller_voice, params)
            agent.events = []
            agent.prepare(scenario, context)
            t0 = time.perf_counter()
            caller_audio, agent_audio, timeline = asyncio.run(
                run_conversation(agent, caller, clock=clock)
            )
            timeline.update(agent=name, rep=rep, language=scenario["language"])
            write_stereo(call_dir / "recording.wav", caller_audio, agent_audio)
            (call_dir / "timeline.json").write_text(
                json.dumps(timeline, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            log(f"[{name} rep{rep}] {n}/{len(scenarios)} {scenario['id']}: "
                f"{timeline['duration_s']:.1f} s of call in {time.perf_counter() - t0:.1f} s")

    manifest = {
        "agent": name,
        "config": config,
        "clock": clock,
        "repeats": repeats,
        "scenarios": [s["id"] for s in scenarios],
        "scenario_set_version": scenario_set_version(scenarios),
        "git_commit": git_commit(),
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (out_dir / "run.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return out_dir
