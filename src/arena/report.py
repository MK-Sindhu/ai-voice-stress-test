"""Build the leaderboard and the static website in docs/.

Reads the scored runs in results/scores/ and writes:

    results/leaderboard.json   the leaderboard numbers (also a DVC metrics file)
    docs/index.html            leaderboard, per-scenario results, every failure with audio
    docs/calibration.html      the same for the calibration agents (no audio)
    docs/audio/                one compressed recording per failed scenario
    docs/favicon.svg
    web/src/content/, web/public/audio/   the same results as data for the Next.js site (see webdata.py)
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

SITE = Path(__file__).parent / "site"   # style.css and site.js
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


def meter(value: dict, better: str) -> str:
    """A thin bar showing the share. Green when a high share is good, red when it is bad."""
    if not value.get("of"):
        return ""
    share = 100 * value["count"] / value["of"]
    return f"<span class='meter {'up' if better == 'higher' else 'down'}'><i style='width:{share:.0f}%'></i></span>"


def agent_label(score: dict, params: dict) -> str:
    return params["agents"].get(score["agent"], score["run"]["config"]).get("label", score["agent"])


def leaderboard_table(scores: list[dict], params: dict, ranked: bool = False) -> str:
    if not scores:
        return "<p class='note'>No agent in this group has been run yet.</p>"
    head = "".join(f"<th>{esc(title)}</th>" for _, title, _ in COLUMNS)
    rows = []
    for position, score in enumerate(scores, 1):
        cells = []
        for key, _, better in COLUMNS:
            value = score["summary"][key]
            lead = " class='lead'" if key == "task_completion" else ""
            cells.append(f"<td{lead}>{cell(score['summary'], key)}{meter(value, better)}{spread(score, key)}</td>")
        rank = f"<span class='rank'>{position}</span>" if ranked else ""
        rows.append(
            f"<tr><th scope='row'>{rank}{esc(agent_label(score, params))}"
            f"<span class='spread'>{esc(score['agent'])} · {len(score['reps'])} pass(es) · "
            f"{score['summary']['calls']} calls</span></th>{''.join(cells)}</tr>"
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
        in_family = [s for s in scenarios if s["family"] == family]
        if not in_family:
            continue
        rows.append(f"<tr class='family-row'><th colspan='{len(scores) + 2}'>{esc(family_name)}</th></tr>")
        for scenario in in_family:
            cells = []
            for score in scores:
                calls = [c for r in score["reps"] for c in r["calls"] if c["scenario"] == scenario["id"]]
                if not calls:
                    cells.append("<td class='na'>not run</td>")
                    continue
                passed = sum(c["status"] == "pass" for c in calls)
                untestable = sum(c["status"] == "untestable" for c in calls)
                kind = "pass" if passed == len(calls) else "fail" if passed == 0 and not untestable else "mixed"
                label = f"{passed}/{len(calls)}" + (" untestable" if untestable and not passed else "")
                link = f"#{score['agent']}--{scenario['id']}"
                cells.append(f"<td class='{kind}'><a href='{link}'>{label}</a></td>" if kind != "pass"
                             else f"<td class='pass'>{label}</td>")
            rows.append(
                f"<tr><th scope='row' title='{esc(scenario['description'])}'>{esc(scenario['title'])}"
                f"<span class='spread'>{esc(scenario['id'])}</span></th>"
                f"<td>{esc(LANGUAGE_NAMES[scenario['language']])}</td>{''.join(cells)}</tr>"
            )
    return f"<div class='scroll'><table class='matrix'><thead><tr><th>Scenario</th><th>Language</th>{head}</tr>" \
           f"</thead><tbody>{''.join(rows)}</tbody></table></div>"


# The drawing's geometry. site.js uses the same three numbers to place the playhead.
SVG_WIDTH, SVG_LEFT, SVG_RIGHT = 920, 62, 12


def call_geometry(call: dict, timeline: dict) -> tuple[list[tuple], list[tuple]]:
    """What to draw for one call.

    Returns the stretches of sound and silence as (start, end, lane, kind, title),
    lane 0 being the caller and lane 1 the agent, and the moments something went
    wrong as (time, label). Both the HTML pages and the Next.js site draw from this.
    """
    starts: dict[int, dict] = {}
    spans = []
    for event in sorted(timeline["events"], key=lambda e: e["t"]):
        kind = event["type"]
        if kind in ("speech_start", "pause_start", "silence_start"):
            starts[event["step"]] = event
        elif kind == "speech_end":
            begin = starts[event["step"]]
            spans.append((begin["t"], event["t"], 0, event["kind"], begin["text"]))
        elif kind == "pause_end":
            begin = starts[event["step"]]
            spans.append((begin["t"], event["t"], 0, "gap", f"caller pauses {begin['seconds']} s mid-thought"))
        elif kind == "silence_end":
            begin = starts[event["step"]]
            spans.append((begin["t"], event["t"], 0, "gap", f"caller silent for {begin['seconds']} s"))
    spans += [(start, end, 1, "agent", f"agent speaks {start:.2f}–{end:.2f} s")
              for start, end in call["measures"]["agent_segments"]]
    marks = [(p["agent_onset"], "talks over the pause") for p in call["measures"]["pauses"] if p["interrupted"]]
    marks += [(b["start"], "did not stop") for b in call["measures"]["barge_ins"]
              if b["agent_was_speaking"] and not b["stopped"]]
    marks += [(b.get("agent_quiet_at"), "stops for a filler word") for b in call["measures"]["backchannels"]
              if b["agent_stopped"]]
    marks += [(t["end"], "no reply") for t in call["measures"]["turns"] if not t["responded"]]
    return sorted(spans), sorted((t, label) for t, label in marks if t is not None)


def timeline_svg(call: dict, timeline: dict) -> str:
    """Draw one call: what the caller did on top, when the agent made sound below."""
    duration = max(timeline["duration_s"], 1.0)
    width, left, right = SVG_WIDTH, SVG_LEFT, SVG_RIGHT
    scale = (width - left - right) / duration

    def x(t: float) -> float:
        return left + t * scale

    lane = width - left - right
    parts = [
        "<text class='lab' x='0' y='37'>CALLER</text><text class='lab' x='0' y='71'>AGENT</text>",
        f"<rect class='track' x='{left}' y='22' width='{lane}' height='22' rx='5'/>",
        f"<rect class='track' x='{left}' y='56' width='{lane}' height='22' rx='5'/>",
    ]
    step = 5 if duration <= 60 else 10
    for t in range(0, int(duration) + 1, step):
        parts.append(f"<line class='axis' x1='{x(t):.1f}' y1='86' x2='{x(t):.1f}' y2='91'/>"
                     f"<text class='tick' x='{x(t):.1f}' y='104'>{t} s</text>")
    spans, marks = call_geometry(call, timeline)
    for index, (start, end, row, kind, title) in enumerate(spans, 1):
        cls = kind if kind in ("gap", "agent") else f"caller {kind}"
        w = max((end - start) * scale, 2)
        parts.append(f"<rect class='{cls}' style='--i:{index}' x='{x(start):.1f}' y='{22 if row == 0 else 56}' "
                     f"width='{w:.1f}' height='22' rx='5'><title>{esc(title)}</title></rect>")
    labelled: list[tuple[float, str]] = []
    for t, label in marks:
        if any(label == other and x(t) - at < 200 for at, other in labelled):
            # The same thing again close by: draw the line, not a second label on top of the first.
            parts.append(f"<line class='mark' x1='{x(t):.1f}' y1='18' x2='{x(t):.1f}' y2='84'/>")
            continue
        labelled.append((x(t), label))
        anchor = "end" if x(t) > width - 190 else "start"
        dx = -6 if anchor == "end" else 6
        parts.append(f"<line class='mark' x1='{x(t):.1f}' y1='4' x2='{x(t):.1f}' y2='84'/>"
                     f"<text class='marktext' x='{x(t) + dx:.1f}' y='13' text-anchor='{anchor}'>{esc(label)}</text>")
    parts.append(f"<line class='playhead' x1='{left}' y1='18' x2='{left}' y2='82'/>")
    return f"<svg viewBox='0 0 {width} 108' role='img' aria-label='Timeline of the call'>{''.join(parts)}</svg>"


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


PLAY_BUTTON = (
    "<button class='play' type='button' aria-label='Play recording'>"
    "<svg class='i-play' viewBox='0 0 16 16' aria-hidden='true'><path d='M4 2.5v11l9-5.5z'/></svg>"
    "<svg class='i-pause' viewBox='0 0 16 16' aria-hidden='true'><path d='M3.5 2.5h3v11h-3zM9.5 2.5h3v11h-3z'/></svg>"
    "</button>"
)


def call_player(call: dict, timeline: dict, audio: str | None) -> str:
    """The drawing of a call and, when there is a recording, a button that plays it."""
    drawing = f"<div class='lanes'>{timeline_svg(call, timeline)}</div>"
    if not audio:
        return f"<div class='call'>{drawing}</div>"
    seconds = timeline["duration_s"]
    return (
        f"<div class='call' data-src='audio/{esc(audio)}' data-duration='{seconds}'>{drawing}"
        f"<div class='transport'>{PLAY_BUTTON}<span class='time'>0:00 / {int(seconds // 60)}:{int(seconds % 60):02d}"
        "</span><span class='hint'>Stereo recording: caller in the left ear, agent in the right. "
        "Click the timeline to jump.</span></div>"
        f"<noscript><audio controls preload='none' src='audio/{esc(audio)}'></audio></noscript></div>"
    )


def first_failures(score: dict) -> list[tuple[dict, dict]]:
    """Each scenario the agent did not pass, with the first pass that shows it: (rep, call)."""
    found, shown = [], set()
    for rep in score["reps"]:
        for call in rep["calls"]:
            if call["status"] != "pass" and call["scenario"] not in shown:
                shown.add(call["scenario"])
                found.append((rep, call))
    return found


def failure_cards(score: dict, by_id: dict, with_audio: bool, *, run_dir: Path | None = None,
                  audio_dir: Path | None = None, audio_files: dict | None = None) -> str:
    """One card per scenario the agent did not pass, from the first pass that shows it.

    `run_dir` and `audio_dir` default to the repository's own results and docs
    folders; a single job (see job.py) passes its own. `audio_files`, if given,
    is filled with the name of each recording written, keyed by (agent, scenario).
    """
    run_dir = run_dir or RUNS / score["agent"]
    audio_dir = audio_dir or DOCS / "audio"
    cards = []
    for rep, call in first_failures(score):
        scenario = by_id[call["scenario"]]
        call_dir = run_dir / f"rep{rep['rep']}" / call["scenario"]
        timeline = json.loads((call_dir / "timeline.json").read_text(encoding="utf-8"))
        audio = None
        if with_audio:
            audio = compress(call_dir / "recording.wav", audio_dir / f"{score['agent']}--{call['scenario']}.mp3")
            if audio_files is not None:
                audio_files[(score["agent"], call["scenario"])] = audio
        said = ""
        if call["replies"]:
            unique = list(dict.fromkeys(f"<li>{esc(r['text'])}</li>" for r in call["replies"].values() if r["text"]))
            if unique:
                said = f"<p class='k'>What the agent said, as transcribed</p><ol>{''.join(unique)}</ol>"
        caller_lines = "".join(
            f"<li>{esc(e['text'])}" + (f" <em>({e['kind'].replace('_', ' ')})</em>" if e["kind"] != "turn" else "")
            + "</li>" for e in timeline["events"] if e["type"] == "speech_start")
        badge = "untestable" if call["status"] == "untestable" else "failed"
        other = sum(c["scenario"] == call["scenario"] and c["status"] != "pass"
                    for r in score["reps"] for c in r["calls"])
        repeats = f" · pass {rep['rep']} shown · not passed in {other} of {len(score['reps'])} passes" \
            if len(score["reps"]) > 1 else ""
        cards.append(
            f"<article class='card' id='{score['agent']}--{call['scenario']}' data-agent='{esc(score['agent'])}' "
            f"data-family='{scenario['family']}'>"
            f"<h4>{esc(scenario['title'])} <span class='badge {badge}'>{badge}</span></h4>"
            f"<p class='meta'>{esc(FAMILY_NAMES[scenario['family']])} · {esc(LANGUAGE_NAMES[scenario['language']])}"
            f"{repeats}</p>"
            f"<p>{esc(scenario['description'])}</p>"
            f"<p class='why'><strong>What went wrong:</strong> {esc('; '.join(call['reasons']))}</p>"
            f"{call_player(call, timeline, audio)}"
            f"<details><summary>Transcript</summary><p class='k'>What the caller said</p><ol>{caller_lines}</ol>"
            f"{said}</details></article>"
        )
    return "".join(cards)


LEGEND = (
    "<ul class='legend'><li><i style='background:var(--caller)'></i>caller speaks</li>"
    "<li><i style='background:var(--caller);outline:1.5px solid var(--fail)'></i>caller interrupts or says a "
    "filler word</li>"
    "<li><i class='l-gap'></i>caller pauses or stays silent</li>"
    "<li><i style='background:var(--agent)'></i>agent makes sound</li>"
    "<li><i class='l-mark' style='background:var(--fail)'></i>where it went wrong</li></ul>"
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

# What the caller does in each family, and a small drawing of it in the same
# two lanes as the call timelines: caller on top, agent below.
_LANES = "<rect class='g-track' x='0' y='4' width='200' height='14' rx='4'/>" \
         "<rect class='g-track' x='0' y='26' width='200' height='14' rx='4'/>"


def _r(cls: str, x: float, w: float, lane: int) -> str:
    return f"<rect class='{cls}' x='{x}' y='{4 if lane == 0 else 26}' width='{w}' height='14' rx='4'/>"


FAMILIES = {
    "mid_thought_pause": (
        "Stops for up to three seconds in the middle of a sentence, then finishes it.",
        "An agent that answers the half sentence and talks over the caller.",
        _r("g-caller", 0, 62, 0) + _r("g-gap", 66, 50, 0) + _r("g-caller", 120, 50, 0) + _r("g-agent", 92, 108, 1)
        + "<line class='g-mark' x1='92' y1='0' x2='92' y2='44'/>"),
    "barge_in": (
        "Cuts into the agent's answer after one, two or four seconds with a new request.",
        "An agent that keeps talking, or carries on with the old answer.",
        _r("g-caller", 0, 44, 0) + _r("g-agent", 54, 146, 1) + _r("g-caller", 104, 70, 0)
        + "<line class='g-mark' x1='104' y1='0' x2='104' y2='44'/>"),
    "backchannel": (
        "Says “mm-hmm”, “हाँ” or “अच्छा” while the agent is explaining.",
        "An agent that takes a listening noise for an interruption and stops.",
        _r("g-caller", 0, 44, 0) + _r("g-agent", 54, 62, 1) + _r("g-caller", 100, 12, 0)
        + "<line class='g-mark' x1='116' y1='0' x2='116' y2='44'/>"),
    "numbers_details": (
        "Gives an order number with “double nine”, a phone number in Hindi, a PIN code, a date, a spelled-out email.",
        "Details misheard, or read back wrong.",
        "".join(_r("g-caller", x, 13, 0) for x in range(0, 96, 16)) + _r("g-agent", 108, 92, 1)),
    "background_noise": (
        "Speaks over street, crowd or television noise, after four seconds of noise alone.",
        "An agent that answers the noise, or cannot hear the caller through it.",
        "".join(f"<line class='g-noise' x1='{x}' y1='{7 + (x * 7) % 5}' x2='{x}' y2='{15 - (x * 3) % 4}'/>"
                for x in range(3, 200, 5))
        + _r("g-caller", 64, 78, 0) + _r("g-agent", 152, 48, 1)),
    "change_of_mind": (
        "“Friday… no, actually, Saturday.”",
        "An agent that acts on the first version.",
        _r("g-old", 0, 52, 0) + _r("g-caller", 58, 58, 0) + _r("g-agent", 126, 74, 1)),
    "long_silence": (
        "Says nothing for 12 to 15 seconds, then comes back.",
        "An agent that never checks in, or is gone when the caller returns.",
        _r("g-caller", 0, 30, 0) + _r("g-agent", 36, 26, 1) + _r("g-gap", 34, 122, 0) + _r("g-agent", 104, 14, 1)
        + _r("g-caller", 160, 40, 0)),
}

FAMILIES_TEXT = {key: (does, catches) for key, (does, catches, _) in FAMILIES.items()}

FONTS = ("https://fonts.googleapis.com/css2?family=Anek+Devanagari:wdth,wght@75..125,300..800"
         "&family=Anek+Latin:wdth,wght@75..125,300..800&family=Martian+Mono:wght@400;600&display=swap")

LOGO = ("<svg viewBox='0 0 26 20' aria-hidden='true'><rect x='0' y='1' width='15' height='7' rx='3.5' fill='#4b3bff'/>"
        "<rect x='9' y='12' width='17' height='7' rx='3.5' fill='#f2a007'/></svg>")
FAVICON = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' "
           "fill='#15132d'/><rect x='5' y='8' width='15' height='6' rx='3' fill='#8b80ff'/>"
           "<rect x='11' y='18' width='16' height='6' rx='3' fill='#f2a007'/></svg>")


def site_settings(params: dict) -> dict:
    return {"name": "Arena", "url": "", "repo_url": "", "contact_email": "", **(params.get("site") or {})}


def page(title: str, body: str, params: dict | None = None, nav: list[tuple[str, str]] | None = None,
         footer: list[str] | None = None, home: str = "index.html", description: str = "") -> str:
    """Wrap a page body in the site's header, footer, styles and script."""
    site = site_settings(params or {})
    links = "".join(f"<a href='{esc(href)}'>{esc(text)}</a>" for href, text in nav or [])
    source = f"<a class='btn ghost small' href='{esc(site['repo_url'])}'>Source</a>" if site["repo_url"] else ""
    foot = "".join(f"<span>{esc(item)}</span>" for item in [site["name"], *(footer or [])])
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{esc(title)}</title><meta name='description' content='{esc(description or title)}'>"
        "<link rel='icon' type='image/svg+xml' href='favicon.svg'>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        f"<link rel='stylesheet' href='{FONTS}'>"
        f"<style>{(SITE / 'style.css').read_text(encoding='utf-8')}</style></head><body>"
        f"<header class='top'><div class='wrap'><a class='brand' href='{esc(home)}'>{LOGO}{esc(site['name'])}</a>"
        f"<nav aria-label='Sections'>{links}</nav>{source}</div></header>"
        f"<main>{body}</main><footer><div class='wrap'>{foot}</div></footer>"
        f"<script>{(SITE / 'site.js').read_text(encoding='utf-8')}</script></body></html>"
    )


def write_favicon(folder: Path) -> None:
    (folder / "favicon.svg").write_text(FAVICON, encoding="utf-8")


def chips(name: str, label: str, options: list[tuple[str, str]]) -> str:
    """A row of filter buttons. site.js shows the cards that match the pressed ones."""
    buttons = "".join(f"<button class='chip' type='button' data-filter='{name}' data-value='{esc(value)}' "
                      f"aria-pressed='false'>{esc(text)}</button>" for value, text in options)
    return (f"<div class='filters' role='group' aria-label='{esc(label)}'><span class='k'>{esc(label)}</span>"
            f"{buttons}</div>")


def family_chips(scores: list[dict], by_id: dict) -> str:
    failed = {by_id[call["scenario"]]["family"] for score in scores for _, call in first_failures(score)}
    options = [("all", "All kinds")] + [(key, name) for key, name in FAMILY_NAMES.items() if key in failed]
    return chips("family", "Scenario", options)


def definitions_list() -> str:
    return "<dl class='defs'>" + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in DEFINITIONS) + "</dl>"


def build_result_page(score: dict, scenarios: list[dict], params: dict, run_dir: Path, out_dir: Path,
                      note: str = "") -> Path:
    """Write a results page for one agent's run: out_dir/index.html and out_dir/audio/.

    This is the page a single job produces. It has the same table, scenario
    grid and failure cards as the leaderboard site, for one agent only.
    """
    by_id = {s["id"]: s for s in scenarios}
    run = score["run"]
    label = run["config"].get("label", score["agent"])
    out_dir.mkdir(parents=True, exist_ok=True)
    cards = failure_cards(score, by_id, with_audio=True, run_dir=run_dir, audio_dir=out_dir / "audio")
    done = score["summary"]["task_completion"]
    body = (
        "<div class='wrap'><div class='hero'>"
        f"<p class='eyebrow'><b>Test result</b> · finished {esc(run['finished_at'][:16].replace('T', ' '))} UTC</p>"
        f"<h1>{esc(label)}</h1>"
        f"<p class='lede'>Passed {done['count']} of {done['of']} scenarios. A scripted caller held real-time spoken "
        "calls with this agent in Hindi, Hinglish and Indian English. Every number below comes from those recorded "
        "calls, and every failure can be played.</p>"
        + (f"<p class='note notice'>{esc(note)}</p>" if note else "")
        + "</div>"
        "<section id='summary' style='padding-top:20px'><h2>Summary</h2>"
        "<p class='sub'>Counts are out of the number of times each situation came up. These are small samples: "
        "read them as counts, not percentages.</p>"
        f"{leaderboard_table([score], params)}{definitions_list()}</section>"
        "<section id='scenarios'><h2>Results by scenario</h2>"
        f"<p class='sub'>Follow a red or amber cell to hear that call.</p>{matrix([score], scenarios)}</section>"
        "<section id='failures'><h2>Every failure, with audio</h2>"
        + (f"{family_chips([score], by_id)}{LEGEND}<p class='showing' aria-live='polite'></p>{cards}" if cards
           else "<p class='sub'>This agent passed every scenario.</p>")
        + "</section></div>"
    )
    nav = [("#summary", "Summary"), ("#scenarios", "Scenarios"), ("#failures", "Failures")]
    footer = [f"{len(scenarios)} scenarios", f"scenario set {run['scenario_set_version']}", f"code {run['git_commit']}",
              "the caller is a synthetic voice"]
    target = out_dir / "index.html"
    target.write_text(page(f"Test result: {label}", body, params, nav, footer), encoding="utf-8")
    write_favicon(out_dir)
    return target


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
        cells = []
        for key in keys:
            text = cell(score["summary"], key)
            text = text.replace("<small>", "(").replace("</small>", ")")
            cells.append(text)
        lines.append(f"| {agent_label(score, params)} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def update_readme(table: str, note: str) -> None:
    path = REPO_ROOT / "README.md"
    start, end = "<!-- leaderboard:start -->", "<!-- leaderboard:end -->"
    text = path.read_text(encoding="utf-8")
    if start in text and end in text:
        head, rest = text.split(start, 1)
        _, tail = rest.split(end, 1)
        path.write_text(f"{head}{start}\n{table}\n\n{note}\n{end}{tail}", encoding="utf-8")


def pick_hero(scores: list[dict]) -> tuple[dict, dict, dict] | None:
    """The call shown at the top of the site: (score, rep, call).

    Preferably one where the agent talks over a mid-thought pause, because
    that failure is the easiest to see and hear.
    """
    fallback = None
    for score in reversed(scores):
        for rep, call in first_failures(score):
            if any(p["interrupted"] for p in call["measures"]["pauses"]):
                return score, rep, call
            fallback = fallback or (score, rep, call)
    return fallback


def hero_panel(scores: list[dict], by_id: dict, params: dict, audio_files: dict) -> str:
    picked = pick_hero(scores)
    if not picked:
        return ""
    score, rep, call = picked
    scenario = by_id[call["scenario"]]
    timeline = json.loads(
        (RUNS / score["agent"] / f"rep{rep['rep']}" / call["scenario"] / "timeline.json").read_text(encoding="utf-8"))
    return (
        "<div class='panel' id='listen'>"
        f"<p class='eyebrow'><b>A real call from this run</b> · {esc(agent_label(score, params))} · "
        f"{esc(LANGUAGE_NAMES[scenario['language']])}</p>"
        f"<h2>{esc(scenario['description'])}</h2>"
        f"<p class='why'><strong>What went wrong:</strong> {esc('; '.join(call['reasons']))}.</p>"
        f"{call_player(call, timeline, audio_files.get((score['agent'], call['scenario'])))}</div>"
    )


def family_cards(scores: list[dict], scenarios: list[dict]) -> str:
    cards = []
    for key, name in FAMILY_NAMES.items():
        does, catches, drawing = FAMILIES[key]
        ids = {s["id"] for s in scenarios if s["family"] == key}
        calls = [c for score in scores for r in score["reps"] for c in r["calls"] if c["scenario"] in ids]
        passed = sum(c["status"] == "pass" for c in calls)
        result = f" · <b>{passed} of {len(calls)}</b> calls passed" if calls else ""
        cards.append(
            f"<article class='family'><svg viewBox='0 0 200 44' aria-hidden='true'>{_LANES}{drawing}</svg>"
            f"<h3>{esc(name)}</h3><p>{esc(does)} Catches: {esc(catches[0].lower() + catches[1:])}</p>"
            f"<p class='count'>{len(ids)} scenarios{result}</p></article>")
    return f"<div class='families'>{''.join(cards)}</div>"


def proof_items(calibration: list[dict]) -> list[dict]:
    """How the measurements were checked, using the calibration agents' own results."""
    items = []
    path = REPO_ROOT / "results" / "metric_validation.json"
    if path.exists():
        check = json.loads(path.read_text(encoding="utf-8"))
        items.append({
            "figure": f"{check['max_timing_error_ms']} ms", "title": "Largest timing error",
            "text": "Fake agents with exactly known delays were run through the same engine. All "
                    f"{check['timing_checks']} timings were measured to within {check['tolerance_ms']} ms, and all "
                    f"{check['outcome_checks']} yes-or-no outcomes came out right."})
    by_name = {s["agent"]: s["summary"] for s in calibration}
    if "oracle" in by_name:
        done, detail = by_name["oracle"]["task_completion"], by_name["oracle"]["detail_accuracy"]
        items.append({
            "figure": f"{done['count']}/{done['of']}", "title": "Correct answers accepted",
            "text": "An agent that is handed the script and says the right reply passed this many scenarios, with "
                    f"{detail['count']} of {detail['of']} details read correctly. A correct agent is not marked "
                    "down."})
    if "oracle-wrong" in by_name:
        detail = by_name["oracle-wrong"]["detail_accuracy"]
        items.append({
            "figure": f"{detail['of'] - detail['count']}/{detail['of']}", "title": "Wrong details caught",
            "text": "The same agent, made to change one detail in each reply, was caught this many times. "
                    "A wrong number does not slip through."})
    return items


def proof_cards(calibration: list[dict]) -> str:
    cards = "".join(f"<div><p class='fig'>{esc(i['figure'])}</p><h3>{esc(i['title'])}</h3><p>{esc(i['text'])}</p></div>"
                    for i in proof_items(calibration))
    return f"<div class='proof'>{cards}</div>" if cards else ""


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
    write_favicon(DOCS)
    site = site_settings(params)
    versions = sorted({s["run"]["scenario_set_version"] for s in scores})
    commits = sorted({s["run"]["git_commit"] for s in real})
    finished = max((s["run"]["finished_at"] for s in real), default="")[:10]
    calls = sum(s["summary"]["calls"] for s in real)
    languages = sorted({s["language"] for s in scenarios})
    audio_files: dict = {}
    failures = "".join(failure_cards(s, by_id, with_audio=True, audio_files=audio_files) for s in real)
    agent_options = [(s["agent"], agent_label(s, params)) for s in real]

    contact = ""
    if site["contact_email"]:
        contact = f"<a class='btn' href='mailto:{esc(site['contact_email'])}'>Ask about testing your agent</a>"
    elif site["repo_url"]:
        contact = f"<a class='btn' href='{esc(site['repo_url'])}'>Read the source</a>"

    body = (
        "<div class='wrap'><div class='hero'>"
        "<p class='eyebrow'><b>Voice agent benchmark</b> · Hindi · Hinglish · Indian English</p>"
        "<h1>A caller built to <em>break</em> voice agents.</h1>"
        "<p class='lede'>It phones the agent and behaves like a difficult customer: pauses mid-sentence, interrupts, "
        "mumbles “hmm”, reads out numbers over street noise, changes its mind. Every call is recorded, so "
        "you can hear exactly where the agent slipped.</p>"
        "<div class='actions'><a class='btn' href='#leaderboard'>See the leaderboard</a>"
        "<a class='btn ghost' href='#failures'>Listen to the failures</a></div>"
        f"<p class='facts'><span><b>{len(scenarios)}</b> scripted scenarios</span>"
        f"<span><b>{len(languages)}</b> languages</span><span><b>{calls}</b> recorded calls</span>"
        f"<span><b>{len(audio_files)}</b> failures you can play</span></p>"
        f"</div>{hero_panel(real, by_id, params, audio_files)}"

        "<section id='caller'><h2>Seven ways the caller makes trouble</h2>"
        "<p class='sub'>Each drawing shows the caller on the top line and the agent below, the same way every "
        "recorded call is drawn further down. The calls are scripted, so every agent gets exactly the same caller.</p>"
        f"{family_cards(real, scenarios)}</section>"

        "<section id='leaderboard'><h2>Leaderboard</h2>"
        "<p class='sub'>Counts are out of the number of times each situation came up, added over all passes. "
        f"With {len(scenarios)} scenarios these are small samples: read them as counts, not percentages.</p>"
        f"{leaderboard_table(real, params, ranked=True)}"
        "<p class='note notice'>Every entry so far is a baseline agent built from open models and run on one laptop. "
        "No commercial platform has been tested yet: the connections for ElevenLabs, Vapi, Retell and smallest.ai "
        "are written but have never been run.</p></section>"

        "<section id='scenarios'><h2>Results by scenario</h2>"
        "<p class='sub'>Passes out of passes run. Follow a red or amber cell to hear that call.</p>"
        f"{matrix(real, scenarios)}</section>"

        "<section id='failures'><h2>Every failure, with audio</h2>"
        "<p class='sub'>Pick an agent, then press play. The line moving across the drawing is where you are in "
        "the call.</p>"
        + (f"{chips('agent', 'Agent', agent_options)}{family_chips(real, by_id)}{LEGEND}"
           f"<p class='showing' aria-live='polite'></p>{failures}" if failures
           else "<p class='note'>Nothing to show yet.</p>")
        + "</section>"

        "<section id='method'><h2>Why the numbers can be trusted</h2>"
        "<p class='sub'>Nothing is taken from an agent's own account of itself. When it spoke is read off the "
        "recording; what it said is transcribed from the recording. The measuring was then tested on agents whose "
        "behaviour is known in advance.</p>"
        f"{proof_cards(calibration)}"
        "<p class='note' style='margin-top:18px'><a href='calibration.html'>See the calibration agents' full "
        "results</a></p>"
        f"<h3 style='margin-top:44px'>What each column means</h3>{definitions_list()}"
        "<h3 style='margin-top:44px'>Read this before quoting a number</h3><ul class='plain'>"
        "<li>The caller is a synthetic voice, not a person. Real callers vary far more.</li>"
        "<li>The background noise is generated, not recorded.</li>"
        "<li>Content checks rely on a speech recogniser reading the agent's voice, and it makes mistakes.</li>"
        "<li>The baseline agents are slow, so an agent that decides too early often drops its reply before the "
        "caller hears it. “Talked over a pause” counts only what a caller would hear.</li></ul></section>"

        "<div class='closing'><h2>Testing your own agent</h2>"
        "<p class='sub' style='margin-bottom:22px'>Not open yet. The same caller will be able to phone an agent on "
        "ElevenLabs, Vapi, Retell or smallest.ai and produce a page like this one, with a recording of every "
        f"failure.</p>{contact}</div></div>"
    )
    nav = [("#caller", "The caller"), ("#leaderboard", "Leaderboard"), ("#failures", "Failures"),
           ("#method", "Method")]
    footer = [f"scenario set {', '.join(versions) or '–'}", f"code {', '.join(commits) or '–'}",
              f"calls placed {finished}" if finished else "no calls yet", "the caller is a synthetic voice"]
    description = ("A scripted caller stress-tests voice agents in Hindi, Hinglish and Indian English and publishes "
                   "a leaderboard with a recording of every failure.")
    (DOCS / "index.html").write_text(
        page(f"{site['name']}: a caller built to break voice agents", body, params, nav, footer,
             description=description), encoding="utf-8")

    cal_failures = "".join(failure_cards(s, by_id, with_audio=False) for s in calibration)
    cal_options = [(s["agent"], s["run"]["config"].get("label", s["agent"])) for s in calibration]
    cal_body = (
        "<div class='wrap'><div class='hero'><p class='eyebrow'><b>Method</b> · checking the measurements</p>"
        "<h1>Calibration agents</h1>"
        "<p class='lede'>These are not real agents. Their behaviour is known in advance, so they show whether the "
        "arena measures correctly. A fake agent set to reply after 500 ms must be measured at 500 ms; the oracle, "
        "which is handed the script, must pass everything; the oracle that states wrong details must be caught.</p>"
        "<div class='actions'><a class='btn ghost' href='index.html'>Back to the leaderboard</a></div></div>"
        "<section id='results' style='padding-top:20px'><h2>Results</h2>"
        f"{leaderboard_table(calibration, params)}</section>"
        f"<section id='scenarios'><h2>Results by scenario</h2>{matrix(calibration, scenarios)}</section>"
        "<section id='flagged'><h2>What was flagged</h2>"
        "<p class='sub'>The fake agents reply with a tone, so they fail every check on what was said. That is "
        "expected; their job is to test the timing.</p>"
        + (f"{chips('agent', 'Agent', cal_options)}{LEGEND}<p class='showing' aria-live='polite'></p>{cal_failures}"
           if cal_failures else "")
        + "</section></div>"
    )
    cal_nav = [("index.html", "Leaderboard"), ("#results", "Results"), ("#flagged", "Flagged")]
    (DOCS / "calibration.html").write_text(
        page(f"{site['name']}: calibration agents", cal_body, params, cal_nav, footer), encoding="utf-8")

    note = (f"Counts are out of the number of times each situation came up, over all passes. "
            f"Scenario set `{', '.join(versions)}`. Full results with audio: [docs/index.html](docs/index.html).")
    update_readme(readme_table(real, params), note)

    from arena.webdata import export_site_data

    picked = pick_hero(real)
    hero = f"{picked[0]['agent']}--{picked[2]['scenario']}" if picked else None
    stamp = {"scenarioSet": ", ".join(versions), "code": ", ".join(commits), "callsPlaced": finished}
    export_site_data(real, calibration, scenarios, params, audio_files, proof_items(calibration), hero, stamp)
    log(f"leaderboard: {len(real)} agent(s), {len(calibration)} calibration agent(s) -> docs/index.html")
