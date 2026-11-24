"""The `arena` command.

    arena validate        check every scenario file against the schema
    arena noise           generate the background-noise files
    arena render          render the caller's lines (and the oracle's replies) to audio
    arena check-audio     confirm a speech recogniser can understand every caller line
    arena run             run an agent through the scenarios and save the recordings
    arena score           score an agent's saved recordings
    arena check-metrics   measure how far the metrics are from the fake agents' known values
    arena report          build the leaderboard and the website in docs/
    arena job             run, score and report one agent into one folder (what a worker runs)
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from arena.config import REPO_ROOT, load_params
from arena.scenario import (
    REPLY_STEPS,
    SCENARIO_DIR,
    load_scenarios,
    say_kind,
    scenario_set_version,
    step_type,
    validate,
)

RESULTS = REPO_ROOT / "results"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_validate(args) -> int:
    import yaml

    errors: dict[str, list[str]] = {}
    scenarios = []
    for path in sorted(SCENARIO_DIR.glob("*.yaml")):
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        problems = validate(scenario, path)
        if problems:
            errors[path.name] = problems
        else:
            scenarios.append(scenario)
    report = {
        "scenarios": len(scenarios),
        "invalid": len(errors),
        "scenario_set_version": scenario_set_version(scenarios),
        "by_family": dict(sorted(Counter(s["family"] for s in scenarios).items())),
        "by_language": dict(sorted(Counter(s["language"] for s in scenarios).items())),
        "errors": errors,
    }
    write_json(RESULTS / "validation.json", report)
    for name, problems in errors.items():
        for problem in problems:
            print(f"{name}: {problem}")
    print(f"{len(scenarios)} valid, {len(errors)} invalid")
    return 1 if errors else 0


def cmd_noise(args) -> int:
    from arena.audio import write_mono
    from arena.noise import build
    from arena.runner import NOISE_DIR
    from arena.voices import KokoroVoice

    params = load_params()
    voices: dict[str, KokoroVoice] = {}

    def voice(name: str) -> KokoroVoice:
        if name not in voices:
            voices[name] = KokoroVoice(voice=name, level_dbfs=-20)
        return voices[name]

    for kind in ("street", "crowd", "tv"):
        audio = build(kind, params["noise"]["seconds"], params["noise"]["seed"], voice)
        write_mono(NOISE_DIR / f"{kind}.wav", audio)
        print(f"wrote {kind}.wav ({len(audio) / 16000:.0f} s)")
    return 0


def spoken_lines(scenarios: list[dict]) -> tuple[list[dict], list[dict]]:
    """Every line the caller says, and every line the oracle says."""
    caller, oracle = [], []
    for scenario in scenarios:
        for index, step in enumerate(scenario["steps"]):
            kind = step_type(step)
            base = {"scenario": scenario["id"], "step": index, "language": scenario["language"]}
            if kind == "say":
                caller.append({**base, "text": step["say"], "spoken": step.get("spoken"),
                               "kind": say_kind(step)})
            elif kind in REPLY_STEPS:
                for variant in ("oracle", "wrong"):
                    if variant in step[kind]:
                        oracle.append({**base, "text": step[kind][variant],
                                       "spoken": step[kind].get(f"{variant}_spoken"), "variant": variant})
    return caller, oracle


def cmd_render(args) -> int:
    from arena.runner import AGENT_AUDIO, CALLER_AUDIO
    from arena.voices import build_voice

    params = load_params()
    scenarios = load_scenarios()
    caller_lines, oracle_lines = spoken_lines(scenarios)
    caller_voice = build_voice(params["caller"]["voice"], CALLER_AUDIO)
    agent_voice = build_voice(params["agent_voice"], AGENT_AUDIO)
    report = {"caller_voice": caller_voice.fingerprint(), "lines": []}
    for line in caller_lines:
        path = caller_voice.path_for(line["text"], line["language"], line["spoken"])
        fresh = not path.exists()
        audio = caller_voice.speak(line["text"], line["language"], line["spoken"])
        report["lines"].append({**line, "file": path.name, "seconds": round(len(audio) / 16000, 2)})
        if fresh:
            print(f"rendered {line['scenario']}[{line['step']}] {len(audio) / 16000:.1f} s")
    for line in oracle_lines:
        agent_voice.speak(line["text"], line["language"], line["spoken"])
    for language, text in params["checkin_text"].items():
        agent_voice.speak(text, language)
    report["caller_seconds"] = round(sum(x["seconds"] for x in report["lines"]), 1)
    write_json(RESULTS / "render.json", report)
    print(f"{len(caller_lines)} caller lines ({report['caller_seconds']} s), {len(oracle_lines)} oracle lines")
    return 0


def cmd_check_audio(args) -> int:
    from arena.audio import read_mono
    from arena.content import character_error_rate, digit_stream, sound_error_rate
    from arena.runner import CALLER_AUDIO
    from arena.transcribe import Transcriber

    params = load_params()
    max_cer = params["intelligibility"]["max_cer"]
    render = json.loads((RESULTS / "render.json").read_text(encoding="utf-8"))
    transcriber = Transcriber(params["intelligibility"]["model"])
    lines, failed = [], 0
    for line in render["lines"]:
        audio = read_mono(CALLER_AUDIO / line["file"])
        language = "en" if line["language"] == "en-IN" else "hi"
        heard = transcriber.transcribe(audio, language=language)["text"]
        detected, _ = transcriber.detect_language(audio)
        reference = line["spoken"] or line["text"]
        entry = {**line, "heard": heard, "detected_language": detected}
        if line["kind"] == "backchannel":
            # A filler word like "hmm" has no fixed spelling. It only needs to
            # be a short burst of sound.
            entry["ok"] = 0.15 <= line["seconds"] <= 1.5
        else:
            # Hinglish is written two ways, so take the kinder of the spelling
            # comparison and the sound comparison.
            entry["cer"] = round(min(character_error_rate(reference, heard),
                                     sound_error_rate(reference, heard)), 3)
            entry["digits_ok"] = digit_stream(reference) == digit_stream(heard)
            entry["ok"] = entry["cer"] <= max_cer and entry["digits_ok"]
        failed += not entry["ok"]
        lines.append(entry)
        print(f"{'ok  ' if entry['ok'] else 'FAIL'} {line['scenario']}[{line['step']}] "
              f"cer={entry.get('cer', '-')} heard: {heard}")
    scored = [x["cer"] for x in lines if "cer" in x]
    write_json(RESULTS / "intelligibility.json", {
        "model": params["intelligibility"]["model"],
        "max_cer": max_cer,
        "lines": len(lines),
        "failed": failed,
        "mean_cer": round(sum(scored) / len(scored), 4),
        "detail": lines,
    })
    print(f"{len(lines) - failed}/{len(lines)} lines intelligible")
    return 1 if failed else 0


def cmd_run(args) -> int:
    from arena.runner import run_agent

    params = load_params()
    scenarios = load_scenarios(args.scenarios)
    run_agent(args.agent, scenarios, params, repeats=args.repeats)
    return 0


def cmd_score(args) -> int:
    from arena.runner import RUNS_DIR
    from arena.score import score_agent
    from arena.tracking import log_agent

    params = load_params()
    run_dir = RUNS_DIR / args.agent
    config = params["agents"][args.agent]
    transcriber = None
    if not config.get("tone_only"):
        from arena.transcribe import Transcriber

        transcriber = Transcriber(**params["metrics"]["transcriber"])
    score = score_agent(run_dir, load_scenarios(), params, transcriber)
    write_json(RESULTS / "scores" / f"{args.agent}.json", score)
    if not args.no_mlflow:
        log_agent(score, run_dir, params)
    print(json.dumps(score["summary"], indent=1))
    return 0


def cmd_check_metrics(args) -> int:
    from arena.validation import run_validation

    report = run_validation(load_params())
    write_json(RESULTS / "metric_validation.json", report)
    for row in report["rows"]:
        print(f"{'ok  ' if row['ok'] else 'FAIL'} {row['metric']}: expected {row['expected']}, "
              f"measured {row['measured']}")
    print(f"largest timing error: {report['max_timing_error_ms']} ms "
          f"(tolerance {report['tolerance_ms']} ms)")
    return 0 if report["all_ok"] else 1


def cmd_report(args) -> int:
    from arena.report import build_report

    build_report(load_params())
    return 0


def cmd_job(args) -> int:
    import os

    from arena.job import run_job

    text = os.environ.get("ARENA_JOB_SPEC") if args.spec is None else Path(args.spec).read_text(encoding="utf-8")
    if not text:
        print("give the job with --spec FILE or in the ARENA_JOB_SPEC environment variable")
        return 2
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as error:
        print(f"the job is not valid JSON: {error}")
        return 2
    status = run_job(spec, Path(args.out), load_params(), allow_test_agents=args.allow_test_agents)
    print(json.dumps(status, indent=1))
    return 0 if status["state"] == "done" else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="arena", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    sub.add_parser("noise").set_defaults(func=cmd_noise)
    sub.add_parser("render").set_defaults(func=cmd_render)
    sub.add_parser("check-audio").set_defaults(func=cmd_check_audio)
    run = sub.add_parser("run")
    run.add_argument("--agent", required=True)
    run.add_argument("--scenarios", nargs="*", help="scenario files or globs (default: all)")
    run.add_argument("--repeats", type=int, help="passes over the scenario set (default: from params.yaml)")
    run.set_defaults(func=cmd_run)
    score = sub.add_parser("score")
    score.add_argument("--agent", required=True)
    score.add_argument("--no-mlflow", action="store_true")
    score.set_defaults(func=cmd_score)
    sub.add_parser("check-metrics").set_defaults(func=cmd_check_metrics)
    sub.add_parser("report").set_defaults(func=cmd_report)
    job = sub.add_parser("job")
    job.add_argument("--spec", help="JSON file describing the job (default: the ARENA_JOB_SPEC variable)")
    job.add_argument("--out", required=True, help="folder to write the results into")
    job.add_argument("--allow-test-agents", action="store_true",
                     help="also accept the fake agent, for trying the worker without a platform account")
    job.set_defaults(func=cmd_job)
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
