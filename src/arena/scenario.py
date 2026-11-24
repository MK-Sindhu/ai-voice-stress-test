"""Scenario files: loading and validation.

A scenario is a YAML file with a scripted list of caller steps and the checks
to apply to the agent's behaviour. Step types:

  say                 the caller speaks a line (kind: turn, barge_in or backchannel)
  pause               the caller stops mid-thought for a set time, then carries on
  listen              the caller's turn is over; wait for the agent to reply and finish
  wait_agent_speech   wait until the agent has been talking for a set time
                      (used to time a barge-in or a backchannel)
  silence             the caller stays quiet for a set time whatever the agent does
"""

import hashlib
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from arena.config import REPO_ROOT

SCHEMA_PATH = Path(__file__).parent / "schema" / "scenario.schema.json"
SCENARIO_DIR = REPO_ROOT / "scenarios"
STEP_TYPES = ("say", "pause", "listen", "wait_agent_speech", "silence")
REPLY_STEPS = ("listen", "wait_agent_speech")


def step_type(step: dict) -> str:
    return next(t for t in STEP_TYPES if t in step)


def say_kind(step: dict) -> str:
    return step.get("kind", "turn")


def reply_slots(scenario: dict) -> list[dict]:
    """The steps at which the agent is expected to be talking, in order."""
    return [s[step_type(s)] for s in scenario["steps"] if step_type(s) in REPLY_STEPS]


def semantic_errors(scenario: dict) -> list[str]:
    """Problems the JSON schema cannot express."""
    errors = []
    steps = scenario["steps"]
    types = [step_type(s) for s in steps]
    ids = [s["id"] for s in steps if "id" in s]
    if len(ids) != len(set(ids)):
        errors.append("step ids are not unique")
    say_ids = {s["id"] for s in steps if "say" in s and "id" in s}
    silence_ids = {s["id"] for s in steps if "silence" in s and "id" in s}

    if types[0] not in ("say", "silence"):
        errors.append("the first step must be say or silence")
    for i, (step, kind) in enumerate(zip(steps, types)):
        prev = types[i - 1] if i else None
        nxt = types[i + 1] if i + 1 < len(steps) else None
        if kind == "pause" and (prev != "say" or nxt != "say"):
            errors.append(f"step {i}: a pause must sit between two say steps")
        if kind == "say" and say_kind(step) in ("barge_in", "backchannel"):
            if prev != "wait_agent_speech":
                errors.append(f"step {i}: {say_kind(step)} must follow wait_agent_speech")
        if kind == "say" and say_kind(step) != "backchannel" and nxt not in ("pause", "listen", "wait_agent_speech"):
            errors.append(f"step {i}: a caller turn must be followed by listen or wait_agent_speech")
        if kind == "say" and say_kind(step) == "backchannel" and nxt not in ("listen", "wait_agent_speech"):
            errors.append(f"step {i}: a backchannel must be followed by listen or wait_agent_speech")

    kinds = {say_kind(s) for s in steps if "say" in s}
    has_pause = "pause" in types
    for check in scenario["checks"]:
        t = check["type"]
        if t in ("detail", "recovery", "mentions") and check["reply_to"] not in say_ids:
            errors.append(f"check {t}: reply_to '{check['reply_to']}' is not the id of a say step")
        if t in ("checks_in", "silent_during") and check["during"] not in silence_ids:
            errors.append(f"check {t}: during '{check['during']}' is not the id of a silence step")
        if t == "no_false_interruption" and not has_pause:
            errors.append("check no_false_interruption needs a pause step")
        if t == "barge_in_stops" and "barge_in" not in kinds:
            errors.append("check barge_in_stops needs a barge_in say step")
        if t == "backchannel_ignored" and "backchannel" not in kinds:
            errors.append("check backchannel_ignored needs a backchannel say step")
    if not scenario["checks"]:
        errors.append("a scenario needs at least one check")
    if scenario["family"] == "background_noise" and "noise" not in scenario:
        errors.append("a background_noise scenario needs a noise block")
    return errors


def validate(scenario: dict, path: Path | None = None) -> list[str]:
    """All problems with one scenario; an empty list means it is valid."""
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))
    errors = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in validator.iter_errors(scenario)
    ]
    if errors:
        return errors
    errors = semantic_errors(scenario)
    if path is not None and path.stem != scenario["id"]:
        errors.append(f"id '{scenario['id']}' does not match file name '{path.name}'")
    return errors


def load_scenario(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        scenario = yaml.safe_load(f)
    errors = validate(scenario, path)
    if errors:
        raise ValueError(f"{path}: " + "; ".join(errors))
    return scenario


def scenario_paths(patterns: list[str] | None = None) -> list[Path]:
    if not patterns:
        return sorted(SCENARIO_DIR.glob("*.yaml"))
    paths: set[Path] = set()
    for pattern in patterns:
        p = Path(pattern)
        if p.is_dir():
            paths.update(p.glob("*.yaml"))
        elif p.exists():
            paths.add(p)
        else:
            paths.update(Path().glob(pattern))
    return sorted(paths)


def load_scenarios(patterns: list[str] | None = None) -> list[dict]:
    return [load_scenario(p) for p in scenario_paths(patterns)]


def scenario_set_version(scenarios: list[dict]) -> str:
    """A short fingerprint of the scenario set, so results can name what they ran."""
    blob = json.dumps(sorted(scenarios, key=lambda s: s["id"]), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]
