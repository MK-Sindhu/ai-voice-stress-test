"""Write the data the Next.js website (web/) is built from.

The site in web/ contains no numbers of its own. Everything it shows comes
from one file written here by `arena report`:

    web/src/content/arena.json    leaderboard, scenarios, every failure with its timeline
    web/public/audio/             the failure recordings (copied from docs/audio)

So the website can only ever show results of calls that were actually placed.
"""

import json
import shutil
from pathlib import Path

from arena.config import REPO_ROOT
from arena.report import (
    COLUMNS,
    DEFINITIONS,
    DOCS,
    FAMILIES_TEXT,
    FAMILY_NAMES,
    LANGUAGE_NAMES,
    RUNS,
    agent_label,
    call_geometry,
    cell,
    first_failures,
    site_settings,
)

WEB = REPO_ROOT / "web"
CONTENT = WEB / "src" / "content" / "arena.json"
AUDIO = WEB / "public" / "audio"


def plain(text: str) -> tuple[str, str]:
    """Split a table cell such as '29/60 <small>1 untestable</small>' into value and footnote."""
    if "<small>" in text:
        value, rest = text.split("<small>", 1)
        return value.strip(), rest.replace("</small>", "").strip()
    return text, ""


def per_pass(score: dict, key: str) -> list[str]:
    if len(score["reps"]) < 2:
        return []
    values = []
    for rep in score["reps"]:
        value = rep["summary"][key]
        if key in ("response_delay_ms", "barge_in_stop_ms"):
            values.append("–" if value["median"] is None else f"{value['median']:,.0f} ms")
        else:
            values.append(f"{value['count']}/{value['of']}" if value["of"] else "–")
    return values


def agent_entry(score: dict, params: dict) -> dict:
    metrics = {}
    for key, _, _ in COLUMNS:
        value, footnote = plain(cell(score["summary"], key))
        raw = score["summary"][key]
        share = raw["count"] / raw["of"] if raw.get("of") else None
        metrics[key] = {"value": value, "footnote": footnote, "share": share, "perPass": per_pass(score, key)}
    return {"id": score["agent"], "label": agent_label(score, params), "calls": score["summary"]["calls"],
            "passes": len(score["reps"]), "metrics": metrics}


def matrix_entry(score: dict) -> dict:
    cells = {}
    for rep in score["reps"]:
        for call in rep["calls"]:
            entry = cells.setdefault(call["scenario"], {"passed": 0, "total": 0, "untestable": 0})
            entry["total"] += 1
            entry["passed"] += call["status"] == "pass"
            entry["untestable"] += call["status"] == "untestable"
    for entry in cells.values():
        entry["kind"] = ("pass" if entry["passed"] == entry["total"]
                         else "fail" if entry["passed"] == 0 and not entry["untestable"] else "mixed")
    return cells


def failure_entries(score: dict, by_id: dict, audio_files: dict | None) -> list[dict]:
    entries = []
    for rep, call in first_failures(score):
        scenario = by_id[call["scenario"]]
        timeline = json.loads(
            (RUNS / score["agent"] / f"rep{rep['rep']}" / call["scenario"] / "timeline.json")
            .read_text(encoding="utf-8"))
        spans, marks = call_geometry(call, timeline)
        said = list(dict.fromkeys(r["text"] for r in (call["replies"] or {}).values() if r["text"]))
        entries.append({
            "id": f"{score['agent']}--{call['scenario']}",
            "agent": score["agent"],
            "scenario": call["scenario"],
            "title": scenario["title"],
            "description": scenario["description"],
            "family": scenario["family"],
            "language": LANGUAGE_NAMES[scenario["language"]],
            "status": call["status"],
            "reasons": call["reasons"],
            "passShown": rep["rep"],
            "passes": len(score["reps"]),
            "notPassed": sum(c["scenario"] == call["scenario"] and c["status"] != "pass"
                             for r in score["reps"] for c in r["calls"]),
            "audio": (audio_files or {}).get((score["agent"], call["scenario"])),
            "duration": timeline["duration_s"],
            "spans": [{"start": round(s, 2), "end": round(e, 2), "lane": lane, "kind": kind, "title": title}
                      for s, e, lane, kind, title in spans],
            "marks": [{"t": round(t, 2), "label": label} for t, label in marks],
            "callerLines": [{"text": e["text"], "kind": e["kind"]} for e in timeline["events"]
                            if e["type"] == "speech_start"],
            "agentLines": said,
        })
    return entries


def group(scores: list[dict], by_id: dict, params: dict, audio_files: dict | None) -> dict:
    return {
        "agents": [agent_entry(s, params) for s in scores],
        "matrix": {s["agent"]: matrix_entry(s) for s in scores},
        "failures": [f for s in scores for f in failure_entries(s, by_id, audio_files)],
    }


def export_site_data(real: list[dict], calibration: list[dict], scenarios: list[dict], params: dict,
                     audio_files: dict, proof: list[dict], hero: str | None, stamp: dict) -> Path:
    """Write arena.json and copy the recordings. `real` must already be in leaderboard order."""
    by_id = {s["id"]: s for s in scenarios}
    families = []
    for key, name in FAMILY_NAMES.items():
        ids = {s["id"] for s in scenarios if s["family"] == key}
        calls = [c for score in real for r in score["reps"] for c in r["calls"] if c["scenario"] in ids]
        does, catches = FAMILIES_TEXT[key]
        families.append({"key": key, "name": name, "does": does, "catches": catches, "scenarios": len(ids),
                         "calls": len(calls), "passed": sum(c["status"] == "pass" for c in calls)})
    board = group(real, by_id, params, audio_files)
    data = {
        "site": site_settings(params),
        "stamp": stamp,
        "facts": {"scenarios": len(scenarios), "languages": len({s["language"] for s in scenarios}),
                  "calls": sum(s["summary"]["calls"] for s in real), "failures": len(board["failures"])},
        "columns": [{"key": key, "title": title, "better": better} for key, title, better in COLUMNS],
        "definitions": [{"term": term, "meaning": meaning} for term, meaning in DEFINITIONS],
        "families": families,
        "scenarios": [{"id": s["id"], "title": s["title"], "description": s["description"], "family": s["family"],
                       "language": LANGUAGE_NAMES[s["language"]]} for s in scenarios],
        "hero": hero,
        "proof": proof,
        **board,
        "calibration": group(calibration, by_id, params, None),
    }
    CONTENT.parent.mkdir(parents=True, exist_ok=True)
    CONTENT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if AUDIO.exists():
        shutil.rmtree(AUDIO)
    if (DOCS / "audio").exists():
        shutil.copytree(DOCS / "audio", AUDIO)
    return CONTENT
