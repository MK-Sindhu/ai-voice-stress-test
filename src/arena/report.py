"""Build the leaderboard and the static website in docs/.

Reads the scored runs in results/scores/ and writes:

    results/leaderboard.json   the leaderboard numbers (also a DVC metrics file)
    docs/index.html            leaderboard, per-scenario results, every failure with audio
    docs/calibration.html      the same for the calibration agents (no audio)
    docs/audio/                one compressed recording per failed scenario
    README.md                  the leaderboard table between its two markers

Only agents with a scored run appear. Nothing is filled in for agents that
were not run.
"""

import html
import json
import shutil
import subprocess
from pathlib import Path

from arena.config import REPO_ROOT
from arena.scenario import load_scenarios

SCORES = REPO_ROOT / "results" / "scores"
RUNS = REPO_ROOT / "results" / "runs"
DOCS = REPO_ROOT / "docs"

FAMILY_NAMES = {
    "mid_thought_pause": "Mid-thought pause", "barge_in": "Barge-in", "backchannel": "Backchannel",
    "numbers_details": "Numbers and details", "background_noise": "Background noise",
    "change_of_mind": "Change of mind", "long_silence": "Long silence",
}
LANGUAGE_NAMES = {"en-IN": "Indian English", "hi": "Hindi", "hinglish": "Hinglish"}

# (key, column heading, what a better value looks like)
COLUMNS = [
    ("task_completion", "Scenarios passed", "higher"),
    ("response_delay_ms", "Response delay, median / p95", "lower"),
    ("false_interruptions", "Talked over a pause", "lower"),
    ("barge_in_stopped", "Stopped when interrupted", "higher"),
    ("barge_in_stop_ms", "Time to stop, median", "lower"),
    ("barge_in_recovery", "Dealt with the interruption", "higher"),
    ("backchannel_ignored", "Kept talking through 'hmm'", "higher"),
    ("detail_accuracy", "Details read back right", "higher"),
    ("language_match", "Replied in caller's language", "higher"),
    ("no_response", "Turns with no reply", "lower"),
]


def esc(text) -> str:
    return html.escape(str(text))


def fmt_ms(value) -> str:
    return "–" if value is None else f"{value:,.0f} ms"


def cell(summary: dict, key: str) -> str:
    value = summary[key]
    if key == "response_delay_ms":
        if value["median"] is None:
            return "–"
        return f"{fmt_ms(value['median'])} / {fmt_ms(value['p95'])} <small>{value['turns']} turns</small>"
    if key == "barge_in_stop_ms":
        return "–" if value["median"] is None else fmt_ms(value["median"])
    if not value["of"]:
        return "–"
    text = f"{value['count']}/{value['of']}"
    if key == "task_completion" and value.get("untestable"):
        text += f" <small>{value['untestable']} untestable</small>"
    return text


def spread(score: dict, key: str) -> str:
    """The same number for each pass on its own, to show how much it moves."""
    if len(score["reps"]) < 2:
        return ""
    parts = []
    for rep in score["reps"]:
        value = rep["summary"][key]
        if key == "response_delay_ms" or key == "barge_in_stop_ms":
            parts.append("–" if value["median"] is None else f"{value['median']:,.0f}")
        else:
            parts.append(f"{value['count']}/{value['of']}" if value["of"] else "–")
    return f"<div class='spread'>per pass: {', '.join(parts)}</div>"


def leaderboard_table(scores: list[dict], params: dict) -> str:
    if not scores:
        return "<p class='note'>No agent in this group has been run yet.</p>"
    head = "".join(f"<th>{esc(title)}</th>" for _, title, _ in COLUMNS)
    rows = []
    for score in scores:
        config = params["agents"].get(score["agent"], score["run"]["config"])
        cells = "".join(f"<td>{cell(score['summary'], key)}{spread(score, key)}</td>" for key, _, _ in COLUMNS)
        rows.append(
            f"<tr><th scope='row'>{esc(config.get('label', score['agent']))}"
            f"<div class='spread'>{esc(score['agent'])} · {len(score['reps'])} pass(es) · "
            f"{score['summary']['calls']} calls</div></th>{cells}</tr>"
        )
    return f"<div class='scroll'><table class='board'><thead><tr><th>Agent</th>{head}</tr></thead>" \
           f"<tbody>{''.join(rows)}</tbody></table></div>"


def matrix(scores: list[dict], scenarios: list[dict]) -> str:
    """One row per scenario, one column per agent: passes out of passes run."""
    if not scores:
        return ""
    head = "".join(f"<th>{esc(s['agent'])}</th>" for s in scores)
    rows = []
    for family, family_name in FAMILY_NAMES.items():
        rows.append(f"<tr class='family'><th colspan='{len(scores) + 2}'>{esc(family_name)}</th></tr>")
        for scenario in [s for s in scenarios if s["family"] == family]:
            cells = []
            for score in scores:
                calls = [c for r in score["reps"] for c in r["calls"] if c["scenario"] == scenario["id"]]
                if not calls:
                    cells.append("<td class='na'>not run</td>")
                    continue
                passed = sum(c["status"] == "pass" for c in calls)
                untestable = sum(c["status"] == "untestable" for c in calls)
                kind = "pass" if passed == len(calls) else "fail" if passed == 0 and not untestable else "mixed"
                label = f"{passed}/{len(calls)}" + (f" <small>{untestable} untestable</small>" if untestable else "")
                link = f"#{score['agent']}--{scenario['id']}"
                cells.append(f"<td class='{kind}'><a href='{link}'>{label}</a></td>" if kind != "pass"
                             else f"<td class='pass'>{label}</td>")
            rows.append(
                f"<tr><th scope='row' title='{esc(scenario['description'])}'>{esc(scenario['title'])}"
                f"<div class='spread'>{esc(scenario['id'])}</div></th>"
                f"<td>{esc(LANGUAGE_NAMES[scenario['language']])}</td>{''.join(cells)}</tr>"
            )
    return f"<div class='scroll'><table class='matrix'><thead><tr><th>Scenario</th><th>Language</th>{head}</tr>" \
           f"</thead><tbody>{''.join(rows)}</tbody></table></div>"


def timeline_svg(call: dict, timeline: dict) -> str:
    """Draw one call: what the caller did on top, when the agent made sound below."""
    duration = max(timeline["duration_s"], 1.0)
    width, left, right = 920, 62, 12
    scale = (width - left - right) / duration

    def x(t: float) -> float:
        return left + t * scale

    def bar(start, end, y, cls, title=""):
        w = max((end - start) * scale, 1.5)
        return f"<rect class='{cls}' x='{x(start):.1f}' y='{y}' width='{w:.1f}' height='18' rx='2'>" \
               f"<title>{esc(title)}</title></rect>"

    parts = [
        "<text class='lab' x='0' y='31'>Caller</text><text class='lab' x='0' y='63'>Agent</text>",
        f"<line class='axis' x1='{left}' y1='84' x2='{width - right}' y2='84'/>",
    ]
    step = 5 if duration <= 60 else 10
    for t in range(0, int(duration) + 1, step):
        parts.append(f"<line class='axis' x1='{x(t):.1f}' y1='84' x2='{x(t):.1f}' y2='88'/>"
                     f"<text class='tick' x='{x(t):.1f}' y='100'>{t} s</text>")
    starts: dict[int, dict] = {}
    for event in timeline["events"]:
        kind = event["type"]
        if kind in ("speech_start", "pause_start", "silence_start"):
            starts[event["step"]] = event
        elif kind == "speech_end":
            begin = starts[event["step"]]
            parts.append(bar(begin["t"], event["t"], 18, f"caller {event['kind']}", begin["text"]))
        elif kind == "pause_end":
            begin = starts[event["step"]]
            parts.append(bar(begin["t"], event["t"], 18, "gap", f"caller pauses {begin['seconds']} s mid-thought"))
        elif kind == "silence_end":
            begin = starts[event["step"]]
            parts.append(bar(begin["t"], event["t"], 18, "gap", f"caller silent for {begin['seconds']} s"))
    for start, end in call["measures"]["agent_segments"]:
        parts.append(bar(start, end, 50, "agent", f"agent speaks {start:.2f}–{end:.2f} s"))
    # Mark the moment something went wrong.
    marks = [(p["agent_onset"], "talks over the pause") for p in call["measures"]["pauses"] if p["interrupted"]]
    marks += [(b["start"], "did not stop") for b in call["measures"]["barge_ins"]
              if b["agent_was_speaking"] and not b["stopped"]]
    marks += [(b.get("agent_quiet_at"), "stops for a filler word") for b in call["measures"]["backchannels"]
              if b["agent_stopped"]]
    marks += [(t["end"], "no reply") for t in call["measures"]["turns"] if not t["responded"]]
    for t, label in marks:
        if t is None:
            continue
        anchor = "end" if x(t) > width - 160 else "start"
        dx = -5 if anchor == "end" else 5
        parts.append(f"<line class='mark' x1='{x(t):.1f}' y1='12' x2='{x(t):.1f}' y2='74'/>"
                     f"<text class='marktext' x='{x(t) + dx:.1f}' y='10' text-anchor='{anchor}'>{esc(label)}</text>")
    return f"<svg viewBox='0 0 {width} 104' role='img' aria-label='Timeline of the call'>{''.join(parts)}</svg>"


def compress(recording: Path, target: Path) -> str | None:
    """Write a small MP3 of the recording (caller left, agent right)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        done = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(recording), "-codec:a", "libmp3lame",
             "-b:a", "40k", str(target)], capture_output=True)
        if done.returncode == 0:
            return target.name
    wav = target.with_suffix(".wav")
    shutil.copyfile(recording, wav)
    return wav.name


def failure_cards(score: dict, by_id: dict, with_audio: bool) -> str:
    """One card per scenario the agent did not pass, from the first pass that shows it."""
    cards = []
    shown: set[str] = set()
    for rep in score["reps"]:
        for call in rep["calls"]:
            if call["status"] == "pass" or call["scenario"] in shown:
                continue
            shown.add(call["scenario"])
            scenario = by_id[call["scenario"]]
            call_dir = RUNS / score["agent"] / f"rep{rep['rep']}" / call["scenario"]
            timeline = json.loads((call_dir / "timeline.json").read_text(encoding="utf-8"))
            audio = ""
            if with_audio:
                name = compress(call_dir / "recording.wav",
                                DOCS / "audio" / f"{score['agent']}--{call['scenario']}.mp3")
                audio = f"<audio controls preload='none' src='audio/{name}'></audio>" \
                        "<div class='spread'>Stereo: caller in the left ear, agent in the right.</div>"
            said = ""
            if call["replies"]:
                seen, items = set(), []
                for reply in call["replies"].values():
                    if id(reply) not in seen and reply["text"]:
                        seen.add(id(reply))
                        items.append(f"<li>{esc(reply['text'])}</li>")
                unique = list(dict.fromkeys(items))
                if unique:
                    said = f"<p class='k'>What the agent said, as transcribed</p><ol>{''.join(unique)}</ol>"
            caller_lines = "".join(
                f"<li>{esc(e['text'])}" + (f" <em>({e['kind'].replace('_', ' ')})</em>" if e["kind"] != "turn" else "")
                + "</li>" for e in timeline["events"] if e["type"] == "speech_start")
            badge = "untestable" if call["status"] == "untestable" else "failed"
            other = sum(c["scenario"] == call["scenario"] and c["status"] != "pass"
                        for r in score["reps"] for c in r["calls"])
            cards.append(
                f"<article class='card' id='{score['agent']}--{call['scenario']}'>"
                f"<h4>{esc(scenario['title'])} <span class='badge {badge}'>{badge}</span></h4>"
                f"<p class='meta'>{esc(FAMILY_NAMES[scenario['family']])} · {esc(LANGUAGE_NAMES[scenario['language']])}"
                f" · pass {rep['rep']} shown · not passed in {other} of {len(score['reps'])} pass(es)</p>"
                f"<p>{esc(scenario['description'])}</p>"
                f"<p class='why'><strong>What went wrong:</strong> {esc('; '.join(call['reasons']))}</p>"
                f"{timeline_svg(call, timeline)}{audio}"
                f"<details><summary>Transcript</summary><p class='k'>What the caller said</p><ol>{caller_lines}</ol>"
                f"{said}</details></article>"
            )
    return "".join(cards)


CSS = """
:root{--bg:#fbfaf7;--ink:#1d2330;--mute:#5d6676;--line:#dcd8cf;--card:#fff;--caller:#2f6fb5;--agent:#c96a1b;
--bad:#b3261e;--good:#1f7a4d;--goodbg:#e4f3ea;--badbg:#fbe6e3;--mixbg:#fdf1d6;--accent:#7a3e9d}
@media (prefers-color-scheme:dark){:root{--bg:#14171d;--ink:#e8e6e1;--mute:#a0a7b4;--line:#333946;--card:#1c2029;
--caller:#6aa6e8;--agent:#f0975a;--bad:#ff8a80;--good:#6fd39b;--goodbg:#173326;--badbg:#3d1f1c;--mixbg:#3a3118;--accent:#c79be3}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:40px 20px 80px}
h1{font-size:2.1rem;line-height:1.15;margin:0 0 10px;letter-spacing:-.02em}
h2{font-size:1.35rem;margin:56px 0 8px;padding-top:18px;border-top:2px solid var(--ink)}
h3{font-size:1.1rem;margin:36px 0 10px}h4{margin:0 0 4px;font-size:1.05rem}
p{max-width:72ch}.lede{font-size:1.1rem;color:var(--mute)}a{color:var(--accent)}
.note,.meta,.spread,small{color:var(--mute);font-size:.8rem;font-weight:400}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
thead th{font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);background:var(--bg)}
tbody tr:last-child>*{border-bottom:0}th[scope=row]{font-weight:600;min-width:220px}
.matrix td.pass{background:var(--goodbg);color:var(--good)}.matrix td.fail{background:var(--badbg)}
.matrix td.mixed{background:var(--mixbg)}.matrix td.na{color:var(--mute)}
.matrix td a{color:var(--bad);font-weight:600}.family th{background:var(--bg);font-size:.75rem;
text-transform:uppercase;letter-spacing:.05em;color:var(--mute)}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:18px 20px;margin:14px 0}
.badge{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;padding:2px 7px;border-radius:99px;
vertical-align:middle;background:var(--badbg);color:var(--bad)}.badge.untestable{background:var(--mixbg);color:var(--ink)}
.why{border-left:3px solid var(--bad);padding-left:12px}.k{font-weight:600;margin:10px 0 2px;font-size:.85rem}
svg{width:100%;height:auto;margin:6px 0;display:block}audio{width:100%;margin-top:6px}
.lab,.tick,.marktext{font:11px ui-sans-serif,system-ui,sans-serif;fill:var(--mute)}.tick{text-anchor:middle}
.axis{stroke:var(--line)}.caller{fill:var(--caller)}.caller.barge_in{fill:var(--accent)}
.caller.backchannel{fill:var(--accent);opacity:.6}.agent{fill:var(--agent)}
.gap{fill:none;stroke:var(--caller);stroke-dasharray:3 3}.mark{stroke:var(--bad);stroke-width:1.5}
.marktext{fill:var(--bad);font-weight:600}
.legend span{display:inline-block;margin-right:16px;font-size:.8rem;color:var(--mute)}
.legend i{display:inline-block;width:14px;height:10px;border-radius:2px;margin-right:5px;vertical-align:baseline}
details{margin-top:8px}summary{cursor:pointer;color:var(--mute);font-size:.85rem}ol{margin:4px 0;padding-left:22px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;max-width:90ch}
dt{font-weight:600}dd{margin:0;color:var(--mute)}
"""

LEGEND = (
    "<p class='legend'><span><i style='background:var(--caller)'></i>caller speaks</span>"
    "<span><i style='background:var(--accent)'></i>caller interrupts or says a filler word</span>"
    "<span><i style='border:1px dashed var(--caller)'></i>caller pauses or stays silent</span>"
    "<span><i style='background:var(--agent)'></i>agent makes sound</span>"
    "<span><i style='background:var(--bad);width:2px;height:12px'></i>where it went wrong</span></p>"
)

DEFINITIONS = [
    ("Scenarios passed", "A scenario passes when all of its checks pass and the agent replied to every caller turn. "
     "'Untestable' means a check could not be applied, for example the agent never talked long enough to be "
     "interrupted."),
    ("Response delay", "From the caller's last sound in a turn to the agent's first sound. Turns where the agent "
     "was already talking are left out."),
    ("Talked over a pause", "Mid-thought pauses in which the agent started speaking before the caller had finished."),
    ("Stopped when interrupted", "Interruptions after which the agent went quiet within the allowed time."),
    ("Time to stop", "From the start of the caller's interruption to the agent going quiet."),
    ("Dealt with the interruption", "The reply after an interruption mentions what the caller interrupted about."),
    ("Kept talking through 'hmm'", "Filler words during the agent's speech that did not make it stop."),
    ("Details read back right",
     "Numbers, dates and similar details found correctly in a transcript of the reply."),
    ("Replied in caller's language", "Calls where the reply was in the caller's language. A Hinglish caller should "
     "get Hindi or Hinglish, not pure English."),
    ("Turns with no reply", "Caller turns the agent never answered within the time allowed."),
]


def page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{esc(title)}</title>"
            f"<style>{CSS}</style></head><body><main>{body}</main></body></html>")


def flat_metrics(score: dict) -> dict:
    s = score["summary"]
    out = {"calls": s["calls"], "passes": len(score["reps"]),
           "response_delay_median_ms": s["response_delay_ms"]["median"],
           "response_delay_p95_ms": s["response_delay_ms"]["p95"],
           "barge_in_stop_median_ms": s["barge_in_stop_ms"]["median"]}
    for key in ("task_completion", "false_interruptions", "barge_in_stopped", "barge_in_recovery",
                "backchannel_ignored", "detail_accuracy", "language_match", "no_response"):
        out[f"{key}_count"] = s[key]["count"]
        out[f"{key}_of"] = s[key]["of"]
        out[f"{key}_rate"] = s[key]["rate"]
    return out


def readme_table(scores: list[dict], params: dict) -> str:
    if not scores:
        return "_No agent has been run yet._"
    keys = ["task_completion", "response_delay_ms", "false_interruptions", "barge_in_stopped",
            "barge_in_stop_ms", "backchannel_ignored", "detail_accuracy", "language_match"]
    titles = {k: t for k, t, _ in COLUMNS}
    lines = ["| Agent | " + " | ".join(titles[k] for k in keys) + " |", "|---|" + "---|" * len(keys)]
    for score in scores:
        label = params["agents"].get(score["agent"], score["run"]["config"]).get("label", score["agent"])
        cells = []
        for key in keys:
            text = cell(score["summary"], key)
            text = text.replace("<small>", "(").replace("</small>", ")")
            cells.append(text)
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def update_readme(table: str, note: str) -> None:
    path = REPO_ROOT / "README.md"
    start, end = "<!-- leaderboard:start -->", "<!-- leaderboard:end -->"
    text = path.read_text(encoding="utf-8")
    if start in text and end in text:
        head, rest = text.split(start, 1)
        _, tail = rest.split(end, 1)
        path.write_text(f"{head}{start}\n{table}\n\n{note}\n{end}{tail}", encoding="utf-8")


def build_report(params: dict, log=print) -> None:
    scenarios = load_scenarios()
    by_id = {s["id"]: s for s in scenarios}
    scores = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SCORES.glob("*.json"))]

    def is_calibration(score: dict) -> bool:
        return bool(score["run"]["config"].get("calibration"))

    real = [s for s in scores if not is_calibration(s)]
    real.sort(key=lambda s: -(s["summary"]["task_completion"]["rate"] or 0))
    calibration = [s for s in scores if is_calibration(s)]

    board = {s["agent"]: flat_metrics(s) for s in scores}
    out = REPO_ROOT / "results" / "leaderboard.json"
    out.write_text(json.dumps(board, indent=1) + "\n", encoding="utf-8")

    if (DOCS / "audio").exists():
        shutil.rmtree(DOCS / "audio")
    DOCS.mkdir(exist_ok=True)
    (DOCS / ".nojekyll").write_text("")
    versions = sorted({s["run"]["scenario_set_version"] for s in scores})
    commits = sorted({s["run"]["git_commit"] for s in real})
    definitions = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in DEFINITIONS)
    failures = "".join(
        f"<h3>{esc(params['agents'].get(s['agent'], {}).get('label', s['agent']))}</h3>"
        + (failure_cards(s, by_id, with_audio=True) or "<p class='note'>Passed every scenario in every pass.</p>")
        for s in real)
    body = (
        "<h1>Voice agent stress-test arena</h1>"
        "<p class='lede'>A scripted caller holds real-time spoken calls with a voice agent in Hindi, Hinglish and "
        "Indian English, sets off the situations voice agents are known to get wrong, and scores what the agent did. "
        "Every number below comes from recorded calls; every failure can be played.</p>"
        f"<p class='note'>{len(scenarios)} scenarios · scenario set {esc(', '.join(versions) or '–')} · "
        f"code {esc(', '.join(commits) or '–')} · the caller is a synthetic voice · "
        "<a href='calibration.html'>calibration agents and metric checks</a></p>"
        "<h2>Leaderboard</h2>"
        "<p>Counts are given out of the number of times the situation came up, added over all passes. "
        "With about 30 scenarios these are small samples: read them as counts, not percentages.</p>"
        f"{leaderboard_table(real, params)}"
        "<p class='note'>All entries so far are local baselines built from open models on one laptop. "
        "No commercial platform has been run: their adapters are written but untested.</p>"
        f"<h3>What the columns mean</h3><dl>{definitions}</dl>"
        "<h2>Results by scenario</h2><p>Passes out of passes run. Follow a red or amber cell to hear that failure.</p>"
        f"{matrix(real, scenarios)}"
        f"<h2>Every failure, with audio</h2>{LEGEND}{failures or '<p class=note>Nothing to show yet.</p>'}"
    )
    (DOCS / "index.html").write_text(page("Voice agent stress-test arena", body), encoding="utf-8")

    cal_failures = "".join(
        f"<h3>{esc(s['run']['config'].get('label', s['agent']))}</h3>" + failure_cards(s, by_id, with_audio=False)
        for s in calibration)
    cal_body = (
        "<p><a href='index.html'>← Leaderboard</a></p><h1>Calibration agents</h1>"
        "<p class='lede'>These are not real agents. Their behaviour is known in advance, so they show whether the "
        "arena measures correctly. A fake agent set to reply after 500 ms must be measured at 500 ms; the oracle, "
        "which is handed the script, must pass everything; the oracle that states wrong details must be caught.</p>"
        f"{leaderboard_table(calibration, params)}"
        "<h2>Results by scenario</h2>"
        f"{matrix(calibration, scenarios)}<h2>What was flagged</h2>{LEGEND}{cal_failures}"
    )
    (DOCS / "calibration.html").write_text(page("Calibration agents", cal_body), encoding="utf-8")

    note = (f"Counts are out of the number of times each situation came up, over all passes. "
            f"Scenario set `{', '.join(versions)}`. Full results with audio: [docs/index.html](docs/index.html).")
    update_readme(readme_table(real, params), note)
    log(f"leaderboard: {len(real)} agent(s), {len(calibration)} calibration agent(s) -> docs/index.html")
