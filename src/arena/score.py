"""Score saved calls.

For every call: take the timing measurements (metrics.py), transcribe the
agent's replies, apply the scenario's checks, and decide pass or fail. Then
add the calls up into the leaderboard numbers. Every rate is kept as a count
out of a total, never as a bare percentage.
"""

import json
from pathlib import Path

import numpy as np

from arena.audio import SR, read_stereo
from arena.content import has_digits, missing_mentions
from arena.metrics import measure

# A Hinglish caller should be answered in Hindi or Hinglish, which the
# recogniser hears as Hindi. Answering in pure English is a mismatch.
EXPECTED_LANGUAGE = {"en-IN": "en", "hi": "hi", "hinglish": "hi"}


def transcribe_replies(agent_audio, measures: dict, transcriber) -> dict[str, dict]:
    """Transcribe the agent's reply to each caller turn. Keyed by say-step id."""
    replies: dict[str, dict] = {}
    done: dict[tuple, dict] = {}
    for step_id, (start, end) in measures["reply_windows"].items():
        key = (start, end)
        if key not in done:
            clip = agent_audio[int(start * SR) : int(end * SR)]
            spoke = any(e > start and s < end for s, e in measures["agent_segments"])
            done[key] = (
                {**transcriber.transcribe(clip), "seconds": round(len(clip) / SR, 2)}
                if spoke else {"text": "", "language": None, "seconds": 0.0}
            )
        replies[step_id] = done[key]
    return replies


def apply_checks(scenario: dict, measures: dict, replies: dict | None) -> list[dict]:
    """Apply each check. `passed` is True, False, or None when the check could
    not be applied (for example, the agent never talked long enough to be
    interrupted, so a barge-in could not be tried)."""
    results = []
    barge_ins = [b for b in measures["barge_ins"] if b["agent_was_speaking"]]
    backchannels = [b for b in measures["backchannels"] if b["agent_was_speaking"]]
    for check in scenario["checks"]:
        kind = check["type"]
        result = {**check, "passed": None, "note": ""}
        if kind == "no_false_interruption":
            if measures["pauses"]:
                hit = [p for p in measures["pauses"] if p["interrupted"]]
                result["passed"] = not hit
                if hit:
                    into = hit[0]["agent_onset"] - hit[0]["start"]
                    result["note"] = f"agent started talking {into:.2f} s into the caller's pause"
        elif kind == "barge_in_stops":
            if barge_ins:
                result["passed"] = all(b["stopped"] for b in barge_ins)
                stop = barge_ins[0]["stop_ms"]
                result["note"] = "agent never went quiet" if stop is None else f"agent went quiet after {stop} ms"
            else:
                result["note"] = "agent was not talking, so it could not be interrupted"
        elif kind == "backchannel_ignored":
            if backchannels:
                result["passed"] = not any(b["agent_stopped"] for b in backchannels)
                if not result["passed"]:
                    result["note"] = "agent stopped talking when the caller said a filler word"
            else:
                result["note"] = "agent was not talking when the filler word was due"
        elif kind in ("detail", "recovery", "mentions"):
            reached = check["reply_to"] in measures["reply_windows"]
            if kind == "recovery" and not barge_ins:
                result["note"] = "no interruption took place"
            elif not reached:
                result["note"] = "the call ended before this point"
            elif replies is None:
                result["note"] = "replies were not transcribed"
            else:
                text = replies[check["reply_to"]]["text"]
                problems = []
                if "digits" in check and not has_digits(text, check["digits"]):
                    problems.append(f"did not say {check['digits']}")
                if "mentions" in check:
                    for group in missing_mentions(text, check["mentions"]):
                        problems.append(f"did not mention {group[0]!r}")
                result["passed"] = not problems
                result["note"] = "; ".join(problems)
                result["heard"] = text
        elif kind in ("checks_in", "silent_during"):
            window = measures["windows"].get(check["during"])
            if window is None:
                result["note"] = "the call ended before this point"
            elif kind == "checks_in":
                result["passed"] = bool(window["agent_onsets"])
                if not result["passed"]:
                    result["note"] = "agent said nothing while the caller was silent"
            else:
                result["passed"] = not window["agent_made_sound"]
                if not result["passed"]:
                    result["note"] = "agent spoke although the caller had not said anything"
        results.append(result)
    return results


def language_verdict(scenario: dict, replies: dict | None) -> dict:
    expected = EXPECTED_LANGUAGE[scenario["language"]]
    if not replies:
        return {"expected": expected, "detected": None, "match": None}
    seconds: dict[str, float] = {}
    for reply in {id(r): r for r in replies.values()}.values():
        if reply["text"] and reply["language"]:
            seconds[reply["language"]] = seconds.get(reply["language"], 0.0) + reply["seconds"]
    if not seconds:
        return {"expected": expected, "detected": None, "match": None}
    detected = max(seconds, key=seconds.get)
    return {"expected": expected, "detected": detected, "match": detected == expected}


def score_call(call_dir: Path, scenario: dict, mp: dict, transcriber=None) -> dict:
    """Score one saved call."""
    _, agent_audio = read_stereo(call_dir / "recording.wav")
    timeline = json.loads((call_dir / "timeline.json").read_text(encoding="utf-8"))
    measures = measure(agent_audio, timeline, mp)
    replies = transcribe_replies(agent_audio, measures, transcriber) if transcriber else None
    checks = apply_checks(scenario, measures, replies)

    unanswered = [t for t in measures["turns"] if not t["responded"]]
    failed = [c for c in checks if c["passed"] is False]
    unknown = [c for c in checks if c["passed"] is None]
    if failed or unanswered:
        status = "fail"
    elif unknown:
        status = "untestable"
    else:
        status = "pass"
    reasons = [c["note"] or c["type"] for c in failed]
    if unanswered:
        reasons.append(f"agent did not reply to {len(unanswered)} caller turn(s)")
    if status == "untestable":
        reasons = [c["note"] or c["type"] for c in unknown]

    return {
        "scenario": scenario["id"],
        "family": scenario["family"],
        "language": scenario["language"],
        "status": status,
        "reasons": reasons,
        "checks": checks,
        "language_match": language_verdict(scenario, replies),
        "replies": replies,
        "measures": measures,
        "duration_s": timeline["duration_s"],
        "clock_lateness_ms": timeline["clock_lateness_ms"],
    }


def _rate(count: int, of: int) -> dict:
    return {"count": count, "of": of, "rate": round(count / of, 4) if of else None}


def summarize(calls: list[dict]) -> dict:
    """Add scored calls up into the leaderboard numbers."""
    turns = [t for c in calls for t in c["measures"]["turns"]]
    delays = [t["response_delay_ms"] for t in turns if t["response_delay_ms"] is not None]
    pauses = [p for c in calls for p in c["measures"]["pauses"]]
    barge = [b for c in calls for b in c["measures"]["barge_ins"] if b["agent_was_speaking"]]
    stops = [b["stop_ms"] for b in barge if b["stop_ms"] is not None]
    back = [b for c in calls for b in c["measures"]["backchannels"] if b["agent_was_speaking"]]
    checks = [k for c in calls for k in c["checks"] if k["passed"] is not None]
    details = [k for k in checks if k["type"] == "detail"]
    recoveries = [k for k in checks if k["type"] == "recovery"]
    languages = [c["language_match"] for c in calls if c["language_match"]["match"] is not None]
    return {
        "calls": len(calls),
        "response_delay_ms": {
            "median": float(np.median(delays)) if delays else None,
            "p95": float(np.percentile(delays, 95)) if delays else None,
            "turns": len(delays),
        },
        "false_interruptions": _rate(sum(p["interrupted"] for p in pauses), len(pauses)),
        "barge_in_stopped": _rate(sum(bool(b["stopped"]) for b in barge), len(barge)),
        "barge_in_stop_ms": {
            "median": float(np.median(stops)) if stops else None,
            "interruptions": len(stops),
        },
        "barge_in_recovery": _rate(sum(k["passed"] for k in recoveries), len(recoveries)),
        "backchannel_ignored": _rate(sum(not b["agent_stopped"] for b in back), len(back)),
        "detail_accuracy": _rate(sum(k["passed"] for k in details), len(details)),
        "language_match": _rate(sum(v["match"] for v in languages), len(languages)),
        "task_completion": {
            **_rate(sum(c["status"] == "pass" for c in calls), len(calls)),
            "untestable": sum(c["status"] == "untestable" for c in calls),
        },
        "no_response": _rate(sum(not t["responded"] for t in turns), len(turns)),
    }


def score_agent(run_dir: Path, scenarios: list[dict], params: dict, transcriber=None,
                log=print) -> dict:
    """Score every call of one agent's run."""
    manifest = json.loads((run_dir / "run.json").read_text())
    by_id = {s["id"]: s for s in scenarios}
    reps = []
    for rep in range(1, manifest["repeats"] + 1):
        calls = []
        for scenario_id in manifest["scenarios"]:
            call_dir = run_dir / f"rep{rep}" / scenario_id
            calls.append(score_call(call_dir, by_id[scenario_id], params["metrics"], transcriber))
            log(f"[{manifest['agent']} rep{rep}] {scenario_id}: {calls[-1]['status']}")
        reps.append({"rep": rep, "summary": summarize(calls), "calls": calls})
    return {
        "agent": manifest["agent"],
        "run": manifest,
        "content_scored": transcriber is not None,
        "summary": summarize([c for r in reps for c in r["calls"]]),
        "reps": reps,
    }
