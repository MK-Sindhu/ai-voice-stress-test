"""Metric validation: do the metrics measure what they claim to?

Each test runs a fake agent whose behaviour is known exactly, then checks that
the value measured from the recording matches. If these tests pass, a number
on the leaderboard can be trusted to within the stated tolerance.
"""

import pytest

from arena.agents.fake import FakeAgent
from conftest import make_scenario

ASK = {"say": "Please tell me about your return policy in detail", "id": "ask"}
LISTEN = {"listen": {}}


def simple_turn():
    return make_scenario([ASK, LISTEN], [{"type": "mentions", "reply_to": "ask", "mentions": [["x"]]}])


def paused_turn(pause_s: float):
    return make_scenario(
        [{"say": "I would like a table for", "id": "first"}, {"pause": pause_s},
         {"say": "four people on Friday", "id": "second"}, LISTEN],
        [{"type": "no_false_interruption"}],
    )


def barge_in():
    return make_scenario(
        [ASK, {"wait_agent_speech": {"for": 1.5}},
         {"say": "No wait, I want a replacement instead", "id": "cut", "kind": "barge_in"}, LISTEN],
        [{"type": "barge_in_stops"}], family="barge_in",
    )


def backchannel():
    return make_scenario(
        [ASK, {"wait_agent_speech": {"for": 1.5}},
         {"say": "hmm", "id": "hmm", "kind": "backchannel"}, LISTEN],
        [{"type": "backchannel_ignored"}], family="backchannel",
    )


def long_silence():
    return make_scenario(
        [ASK, LISTEN, {"silence": 8, "id": "quiet"}, {"say": "Sorry, I am back", "id": "back"}, LISTEN],
        [{"type": "checks_in", "during": "quiet"}], family="long_silence",
    )


@pytest.mark.parametrize("delay_ms", [200, 500, 1000, 1500])
def test_response_delay_is_measured(run_call, params, delay_ms):
    call = run_call(FakeAgent(response_delay_ms=delay_ms), simple_turn())
    measured = call["measures"]["turns"][0]["response_delay_ms"]
    assert abs(measured - delay_ms) <= params["tolerance"]["timing_ms"]


@pytest.mark.parametrize("stop_ms", [100, 300, 800, 1200])
def test_barge_in_stop_time_is_measured(run_call, params, stop_ms):
    call = run_call(FakeAgent(reply_ms=8000, stop_after_ms=stop_ms), barge_in())
    entry = call["measures"]["barge_ins"][0]
    assert entry["agent_was_speaking"]
    assert abs(entry["stop_ms"] - stop_ms) <= params["tolerance"]["timing_ms"]
    assert entry["stopped"] is True
    assert call["checks"][0]["passed"] is True


def test_agent_that_never_stops_is_reported(run_call):
    call = run_call(FakeAgent(reply_ms=8000, stop_after_ms=None), barge_in())
    entry = call["measures"]["barge_ins"][0]
    assert entry["stopped"] is False
    assert call["checks"][0]["passed"] is False
    assert call["status"] == "fail"


def test_agent_that_stops_too_late_fails(run_call, params):
    late = params["metrics"]["barge_in"]["max_stop_ms"] + 300
    call = run_call(FakeAgent(reply_ms=8000, stop_after_ms=late), barge_in())
    entry = call["measures"]["barge_ins"][0]
    assert abs(entry["stop_ms"] - late) <= params["tolerance"]["timing_ms"]
    assert entry["stopped"] is False


def test_quick_agent_interrupts_a_pause(run_call):
    # Replies 500 ms into a 2 s pause: a false interruption.
    call = run_call(FakeAgent(response_delay_ms=500), paused_turn(2.0))
    pause = call["measures"]["pauses"][0]
    assert pause["interrupted"] is True
    assert abs((pause["agent_onset"] - pause["start"]) * 1000 - 500) <= 30
    assert call["status"] == "fail"


def test_patient_agent_does_not_interrupt_a_pause(run_call):
    # Waits 2.5 s, longer than the 2 s pause: no interruption, and one reply.
    call = run_call(FakeAgent(response_delay_ms=2500), paused_turn(2.0))
    assert call["measures"]["pauses"][0]["interrupted"] is False
    assert abs(call["measures"]["turns"][0]["response_delay_ms"] - 2500) <= 30
    assert call["status"] == "pass"


def test_agent_that_stops_on_a_filler_word_is_caught(run_call):
    call = run_call(FakeAgent(reply_ms=8000, stop_after_ms=200), backchannel())
    assert call["measures"]["backchannels"][0]["agent_stopped"] is True
    assert call["status"] == "fail"


def test_agent_that_ignores_a_filler_word_passes(run_call):
    agent = FakeAgent(reply_ms=8000, stop_after_ms=800, min_interrupt_ms=800)
    call = run_call(agent, backchannel())
    assert call["measures"]["backchannels"][0]["agent_stopped"] is False
    assert call["status"] == "pass"


def test_agent_that_ignores_fillers_still_stops_for_a_real_interruption(run_call, params):
    agent = FakeAgent(reply_ms=8000, stop_after_ms=800, min_interrupt_ms=800)
    call = run_call(agent, barge_in())
    assert abs(call["measures"]["barge_ins"][0]["stop_ms"] - 800) <= params["tolerance"]["timing_ms"]


def test_silent_agent_is_reported_as_no_response(run_call):
    call = run_call(FakeAgent(silent=True), simple_turn())
    assert call["measures"]["turns"][0]["responded"] is False
    assert call["status"] == "fail"


def test_check_in_during_long_silence(run_call):
    with_checkin = run_call(FakeAgent(reply_ms=2000, checkin_after_ms=4000), long_silence())
    assert with_checkin["checks"][0]["passed"] is True
    without = run_call(FakeAgent(reply_ms=2000), long_silence())
    assert without["checks"][0]["passed"] is False


def test_barge_in_is_untestable_when_the_agent_barely_speaks(run_call):
    # The agent's replies last 0.5 s, so there is never 1.5 s of speech to cut into.
    scenario = barge_in()
    scenario["steps"][1]["wait_agent_speech"]["timeout"] = 5
    call = run_call(FakeAgent(reply_ms=500), scenario)
    assert call["checks"][0]["passed"] is None
    assert call["status"] == "untestable"


def test_real_clock_gives_the_same_measurement(run_call, params):
    # The same agent on a real 20 ms clock must measure the same as on the
    # virtual clock, which is what the other tests use.
    call = run_call(FakeAgent(response_delay_ms=500, reply_ms=600), simple_turn(), clock="real")
    assert abs(call["measures"]["turns"][0]["response_delay_ms"] - 500) <= params["tolerance"]["timing_ms"]
    assert call["clock_lateness_ms"]["p99"] < 20
