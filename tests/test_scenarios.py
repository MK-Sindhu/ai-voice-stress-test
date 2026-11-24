"""The scenario files themselves: valid, complete, and balanced."""

from collections import Counter

import pytest
import yaml

from arena.scenario import SCENARIO_DIR, load_scenarios, say_kind, step_type, validate

PATHS = sorted(SCENARIO_DIR.glob("*.yaml"))


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_scenario_file_is_valid(path):
    scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert validate(scenario, path) == []


def test_set_covers_every_family_and_language():
    scenarios = load_scenarios()
    assert len(scenarios) >= 28
    families = Counter(s["family"] for s in scenarios)
    assert set(families) == {
        "mid_thought_pause", "barge_in", "backchannel", "numbers_details",
        "background_noise", "change_of_mind", "long_silence",
    }
    assert min(families.values()) >= 3
    languages = Counter(s["language"] for s in scenarios)
    assert min(languages.values()) >= len(scenarios) // 4  # roughly a third each


def test_hinglish_lines_carry_a_pronunciation():
    # Hinglish is typed in Latin script; the Hindi voice needs a Devanagari form to read.
    for scenario in load_scenarios():
        if scenario["language"] != "hinglish":
            continue
        for step in scenario["steps"]:
            if step_type(step) == "say":
                assert "spoken" in step, f"{scenario['id']}: '{step['say']}' has no spoken form"


def test_every_content_check_can_be_passed_and_failed_by_the_oracle():
    # A reply that is checked for content needs a reference answer, so the
    # oracle can show the check is passable.
    for scenario in load_scenarios():
        steps = scenario["steps"]
        for check in scenario["checks"]:
            if check["type"] not in ("detail", "recovery", "mentions"):
                continue
            index = next(i for i, s in enumerate(steps) if s.get("id") == check["reply_to"])
            reply = next(s for s in steps[index + 1 :] if step_type(s) == "listen")
            assert reply["listen"].get("oracle"), f"{scenario['id']}: no oracle reply for {check['reply_to']}"
            if check["type"] == "detail":
                assert reply["listen"].get("wrong"), f"{scenario['id']}: no wrong reply for {check['reply_to']}"


def test_invalid_scenarios_are_rejected():
    base = {
        "id": "x", "family": "barge_in", "language": "hi", "title": "Test", "description": "A test scenario.",
        "steps": [{"say": "hello", "id": "a"}, {"listen": {}}],
        "checks": [{"type": "mentions", "reply_to": "a", "mentions": [["x"]]}],
    }
    assert validate(base) == []
    assert validate({**base, "family": "telepathy"})
    assert validate({**base, "checks": [{"type": "mentions", "reply_to": "missing", "mentions": [["x"]]}]})
    assert validate({**base, "checks": [{"type": "barge_in_stops"}]})  # no barge-in step to check
    assert validate({**base, "steps": [{"say": "hello", "id": "a"}, {"pause": 2}, {"listen": {}}]})
    cut = {"say": "wait", "id": "b", "kind": "barge_in"}
    assert validate({**base, "steps": [{"say": "hello", "id": "a"}, cut, {"listen": {}}]})
    assert say_kind(cut) == "barge_in"
