"""Shared helpers: run a small scenario against an agent and score it.

The tests use the synthetic voice (bursts of noise) and the virtual clock, so
they need no speech models and finish in seconds.
"""

import asyncio
import json

import pytest

from arena.audio import write_stereo
from arena.caller import Caller
from arena.config import load_params
from arena.engine import run_conversation
from arena.runner import caller_clips
from arena.scenario import validate
from arena.score import score_call
from arena.voices import SyntheticVoice


def make_scenario(steps: list[dict], checks: list[dict], **extra) -> dict:
    scenario = {
        "id": "test_case", "family": "mid_thought_pause", "language": "en-IN",
        "title": "Test case", "description": "A scenario built inside a test.",
        "steps": steps, "checks": checks, **extra,
    }
    assert validate(scenario) == []
    return scenario


@pytest.fixture(scope="session")
def params() -> dict:
    return load_params()


@pytest.fixture
def run_call(tmp_path, params):
    """run_call(agent, scenario) -> the scored call."""

    def run(agent, scenario, *, clock="virtual", transcriber=None, context=None):
        voice = SyntheticVoice()
        caller = Caller(scenario, caller_clips(scenario, voice))
        agent.prepare(scenario, context or {})
        caller_audio, agent_audio, timeline = asyncio.run(
            run_conversation(agent, caller, clock=clock)
        )
        write_stereo(tmp_path / "recording.wav", caller_audio, agent_audio)
        (tmp_path / "timeline.json").write_text(json.dumps(timeline))
        return score_call(tmp_path, scenario, params["metrics"], transcriber)

    return run
