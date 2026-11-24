"""The audio engine, the caller and the oracle agent."""

import asyncio

import numpy as np
import pytest

from arena.agents.base import Agent
from arena.agents.fake import FakeAgent, OracleAgent
from arena.audio import FRAME, SR, dbfs, speech_segments
from arena.caller import Caller
from arena.engine import run_conversation
from arena.noise import at_level, build
from arena.runner import caller_clips
from arena.voices import SyntheticVoice, split_by_script
from conftest import make_scenario

SCENARIO = make_scenario(
    [{"say": "I would like a table for", "id": "a"}, {"pause": 1.0},
     {"say": "four people on Friday", "id": "b"}, {"listen": {}}],
    [{"type": "no_false_interruption"}],
)


def run(agent, scenario=SCENARIO, **caller_args):
    caller = Caller(scenario, caller_clips(scenario, SyntheticVoice()), **caller_args)
    return asyncio.run(run_conversation(agent, caller, clock="virtual"))


def test_recording_has_both_sides_in_step():
    caller_audio, agent_audio, timeline = run(FakeAgent(response_delay_ms=1500))
    assert len(caller_audio) == len(agent_audio)
    assert len(caller_audio) % FRAME == 0
    assert abs(len(caller_audio) / SR - timeline["duration_s"]) < 1e-6
    assert timeline["completed"] is True


def test_timeline_records_what_the_caller_did_in_order():
    _, _, timeline = run(FakeAgent(response_delay_ms=1500))
    kinds = [e["type"] for e in timeline["events"]]
    assert kinds == ["speech_start", "speech_end", "pause_start", "pause_end", "speech_start",
                     "speech_end", "listen_start", "listen_end", "script_end"]
    times = [e["t"] for e in timeline["events"]]
    assert times == sorted(times)
    first_end, second_start = timeline["events"][1], timeline["events"][4]
    assert second_start["t"] - first_end["t"] == pytest.approx(1.0, abs=0.03)
    assert first_end["turn_end"] is False and timeline["events"][5]["turn_end"] is True


def test_caller_audio_matches_its_timeline():
    caller_audio, _, timeline = run(FakeAgent(response_delay_ms=1500))
    spoken = speech_segments(caller_audio, -45, 60, 100)
    starts = [e["t"] for e in timeline["events"] if e["type"] == "speech_start"]
    ends = [e["t"] for e in timeline["events"] if e["type"] == "speech_end"]
    assert [round(s, 2) for s, _ in spoken] == [round(t, 2) for t in starts]
    assert [round(e, 2) for _, e in spoken] == [round(t, 2) for t in ends]


def test_listen_gives_up_on_a_silent_agent():
    _, _, timeline = run(FakeAgent(silent=True), listen_timeout_s=3.0)
    end = next(e for e in timeline["events"] if e["type"] == "listen_end")
    assert end["reason"] == "no_response"


def test_virtual_clock_refuses_agents_that_need_real_time():
    class RealTimeAgent(Agent):
        async def send_audio(self, frame):
            pass

        async def receive_audio(self):
            return self.silence()

    with pytest.raises(ValueError, match="real clock"):
        run(RealTimeAgent())


def test_noise_is_mixed_into_the_caller_channel_at_the_set_level():
    noise = at_level(build("street", 10, seed=1), -30)
    assert dbfs(noise) == pytest.approx(-30, abs=0.5)
    caller_audio, _, timeline = run(FakeAgent(silent=True), listen_timeout_s=2.0, noise=noise)
    pause = next(e for e in timeline["events"] if e["type"] == "pause_start")
    quiet = caller_audio[int((pause["t"] + 0.2) * SR) : int((pause["t"] + 0.8) * SR)]
    assert dbfs(quiet) == pytest.approx(-30, abs=4)


def test_oracle_replies_to_turns_and_stops_for_interruptions():
    scenario = make_scenario(
        [{"say": "Please explain the policy in detail", "id": "ask"}, {"wait_agent_speech": {"for": 1.5}},
         {"say": "No wait, something else", "id": "cut", "kind": "barge_in"}, {"listen": {"oracle": "Sure thing"}}],
        [{"type": "barge_in_stops"}], family="barge_in",
    )
    agent = OracleAgent(response_delay_ms=600, stop_after_ms=200)
    agent.prepare(scenario, {"agent_voice": SyntheticVoice(), "checkin_text": {"en-IN": "Hello?"}})
    _, agent_audio, timeline = run(agent, scenario)
    segments = speech_segments(agent_audio, -45, 60, 500)
    cut = next(e for e in timeline["events"] if e["type"] == "speech_start" and e["kind"] == "barge_in")
    assert len(segments) == 2
    assert segments[0][1] - cut["t"] == pytest.approx(0.2, abs=0.03)


def test_mixed_script_text_is_split_for_the_two_voices():
    assert split_by_script("Hello there") == [("Hello there", False)]
    assert split_by_script("नमस्ते 4 7 9") == [("नमस्ते 4 7 9", True)]
    assert split_by_script("आपका order number 4 7 है") == [("आपका", True), ("order number 4 7", False), ("है", True)]


def test_agent_frames_must_be_the_right_size():
    class BadAgent(FakeAgent):
        async def receive_audio(self):
            return np.zeros(100, dtype=np.int16)

    with pytest.raises(ValueError, match="samples"):
        run(BadAgent())
