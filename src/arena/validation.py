"""Measure how far the timing metrics are from known values.

Fake agents with exact, configured timings are run through small scenarios,
and each measured value is compared with the value the agent was set to. The
result is written to results/metric_validation.json and quoted in the README.
The same comparisons run as tests on every push.
"""

import asyncio
import tempfile
from pathlib import Path

from arena.agents.fake import FakeAgent
from arena.audio import write_stereo
from arena.caller import Caller
from arena.engine import run_conversation
from arena.metrics import measure
from arena.runner import caller_clips
from arena.voices import SyntheticVoice

ASK = {"say": "Please tell me about your return policy in detail", "id": "ask"}


def _scenario(steps: list[dict]) -> dict:
    return {"id": "validation", "language": "en-IN", "steps": steps, "checks": []}


SIMPLE = _scenario([ASK, {"listen": {}}])
BARGE = _scenario([ASK, {"wait_agent_speech": {"for": 1.5}},
                   {"say": "No wait, I want a replacement instead", "id": "cut", "kind": "barge_in"},
                   {"listen": {}}])
FILLER = _scenario([ASK, {"wait_agent_speech": {"for": 1.5}},
                    {"say": "hmm", "id": "hmm", "kind": "backchannel"}, {"listen": {}}])


def _paused(seconds: float) -> dict:
    return _scenario([{"say": "I would like a table for", "id": "a"}, {"pause": seconds},
                      {"say": "four people on Friday", "id": "b"}, {"listen": {}}])


def _run(agent: FakeAgent, scenario: dict, mp: dict, clock: str = "virtual") -> dict:
    caller = Caller(scenario, caller_clips(scenario, SyntheticVoice()))
    caller_audio, agent_audio, timeline = asyncio.run(run_conversation(agent, caller, clock=clock))
    with tempfile.TemporaryDirectory() as tmp:  # go through the saved file, as scoring does
        from arena.audio import read_stereo

        write_stereo(Path(tmp) / "r.wav", caller_audio, agent_audio)
        _, agent_audio = read_stereo(Path(tmp) / "r.wav")
    return measure(agent_audio, timeline, mp)


def run_validation(params: dict) -> dict:
    mp, tolerance = params["metrics"], params["tolerance"]["timing_ms"]
    rows: list[dict] = []

    def timing(metric: str, expected: float, measured: float | None) -> None:
        error = None if measured is None else measured - expected
        rows.append({"metric": metric, "expected": expected, "measured": measured, "error_ms": error,
                     "ok": error is not None and abs(error) <= tolerance})

    def outcome(metric: str, expected, measured) -> None:
        rows.append({"metric": metric, "expected": expected, "measured": measured, "error_ms": None,
                     "ok": expected == measured})

    for delay in (200, 300, 500, 700, 1000, 1500, 2000):
        m = _run(FakeAgent(response_delay_ms=delay), SIMPLE, mp)
        timing(f"response delay, agent set to {delay} ms", delay, m["turns"][0]["response_delay_ms"])
    m = _run(FakeAgent(response_delay_ms=500, reply_ms=600), SIMPLE, mp, clock="real")
    timing("response delay on a real clock, agent set to 500 ms", 500, m["turns"][0]["response_delay_ms"])

    for stop in (100, 200, 300, 500, 800, 1200):
        m = _run(FakeAgent(reply_ms=8000, stop_after_ms=stop), BARGE, mp)
        timing(f"barge-in stop time, agent set to {stop} ms", stop, m["barge_ins"][0]["stop_ms"])
    m = _run(FakeAgent(reply_ms=8000, stop_after_ms=None), BARGE, mp)
    outcome("agent that never stops is reported as not stopping", False, m["barge_ins"][0]["stopped"])

    for delay, pause, expected in ((500, 2.0, True), (1000, 2.0, True), (1500, 1.0, False), (2500, 2.0, False)):
        m = _run(FakeAgent(response_delay_ms=delay), _paused(pause), mp)
        outcome(f"false interruption: agent replies after {delay} ms, caller pauses {pause} s",
                expected, m["pauses"][0]["interrupted"])

    m = _run(FakeAgent(response_delay_ms=1000, reply_ms=8000, stop_after_ms=200), FILLER, mp)
    outcome("agent that stops on 'hmm' is reported as stopping", True, m["backchannels"][0]["agent_stopped"])
    m = _run(FakeAgent(reply_ms=8000, stop_after_ms=800, min_interrupt_ms=800), FILLER, mp)
    outcome("agent that ignores 'hmm' is reported as carrying on", False, m["backchannels"][0]["agent_stopped"])

    m = _run(FakeAgent(silent=True), SIMPLE, mp)
    outcome("silent agent is reported as not responding", False, m["turns"][0]["responded"])

    errors = [abs(r["error_ms"]) for r in rows if r["error_ms"] is not None]
    return {
        "tolerance_ms": tolerance,
        "timing_checks": len(errors),
        "max_timing_error_ms": max(errors),
        "mean_timing_error_ms": round(sum(errors) / len(errors), 1),
        "outcome_checks": sum(r["error_ms"] is None for r in rows),
        "all_ok": all(r["ok"] for r in rows),
        "rows": rows,
    }
