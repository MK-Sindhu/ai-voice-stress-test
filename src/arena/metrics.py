"""Timing measurements, computed from the recording and the timeline.

Nothing here trusts the agent. When the agent spoke is read off the agent's
channel of the recording; what the caller did and when is read from the
timeline the caller wrote.
"""

from arena.audio import SR, first_silence, speech_segments


def build_turns(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Group the caller's speech events into turns and backchannels.

    A turn is one or more spoken lines with only mid-thought pauses between
    them. It ends when the caller stops and waits for the agent.
    """
    turns: list[dict] = []
    backchannels: list[dict] = []
    current: dict | None = None
    for event in events:
        kind = event["type"]
        if kind == "speech_start" and event["kind"] == "backchannel":
            backchannels.append({"id": event["id"], "start": event["t"], "end": None,
                                 "text": event["text"]})
        elif kind == "speech_end" and event["kind"] == "backchannel":
            backchannels[-1]["end"] = event["t"]
        elif kind == "speech_start":
            if current is None:
                current = {
                    "kind": event["kind"], "ids": [], "texts": [], "start": event["t"],
                    "end": None, "pauses": [], "expects_reply": False, "last_end": None,
                }
            else:
                current["pauses"].append((current["last_end"], event["t"]))
            current["ids"].append(event["id"])
            current["texts"].append(event["text"])
        elif kind == "speech_end":
            current["last_end"] = event["t"]
            if event["turn_end"]:
                current["end"] = event["t"]
                current["expects_reply"] = event["expects_reply"]
                turns.append(current)
                current = None
    return turns, backchannels


def measure(agent_audio, timeline: dict, mp: dict) -> dict:
    """All timing measurements for one call.

    mp is the `metrics` block of params.yaml.
    """
    threshold = mp["vad"]["threshold_dbfs"]
    segments = speech_segments(
        agent_audio, threshold, mp["vad"]["min_speech_ms"], mp["vad"]["merge_gap_ms"]
    )
    duration = len(agent_audio) / SR
    events = timeline["events"]
    turns, backchannels = build_turns(events)

    def speaking_at(t: float) -> bool:
        return any(s <= t < e for s, e in segments)

    out: dict = {
        "agent_segments": [[round(s, 3), round(e, 3)] for s, e in segments],
        "turns": [], "pauses": [], "barge_ins": [], "backchannels": [], "windows": {},
    }

    for n, turn in enumerate(turns):
        end = turn["end"]
        window_end = turns[n + 1]["start"] if n + 1 < len(turns) else duration
        turn["reply_window"] = (end, window_end)

        # Mid-thought pauses: did the agent start talking before the caller finished?
        for p, (pause_start, pause_end) in enumerate(turn["pauses"]):
            until = turn["pauses"][p + 1][0] if p + 1 < len(turn["pauses"]) else end
            onsets = [s for s, _ in segments if pause_start <= s < until]
            out["pauses"].append({
                "turn": n, "start": pause_start, "end": pause_end,
                "interrupted": bool(onsets),
                "agent_onset": onsets[0] if onsets else None,
            })

        if turn["expects_reply"]:
            overlapped = speaking_at(end)
            onsets = [s for s, _ in segments if end <= s < window_end]
            responded = any(e > end + 0.05 and s < window_end for s, e in segments)
            delay = None
            if onsets and not overlapped:
                delay = round((onsets[0] - end) * 1000)
            out["turns"].append({
                "turn": n, "ids": turn["ids"], "kind": turn["kind"], "end": end,
                "responded": responded,
                # No delay is reported when the agent was already talking as
                # the caller finished: there is no clean start to time.
                "agent_talking_at_end": overlapped,
                "response_delay_ms": delay,
            })

        if turn["kind"] == "barge_in":
            start = turn["start"]
            entry = {"turn": n, "ids": turn["ids"], "start": start,
                     "agent_was_speaking": speaking_at(start), "stop_ms": None, "stopped": None}
            if entry["agent_was_speaking"]:
                quiet = first_silence(agent_audio, start, threshold, mp["barge_in"]["stop_silence_ms"])
                if quiet is not None:
                    entry["stop_ms"] = round((quiet - start) * 1000)
                entry["stopped"] = quiet is not None and entry["stop_ms"] <= mp["barge_in"]["max_stop_ms"]
            out["barge_ins"].append(entry)

    for bc in backchannels:
        entry = {"id": bc["id"], "start": bc["start"], "end": bc["end"],
                 "agent_was_speaking": speaking_at(bc["start"]), "agent_stopped": None}
        if entry["agent_was_speaking"]:
            quiet = first_silence(agent_audio, bc["start"], threshold, mp["backchannel"]["stop_silence_ms"])
            limit = bc["end"] + mp["backchannel"]["window_after_ms"] / 1000
            entry["agent_stopped"] = quiet is not None and quiet <= limit
            entry["agent_quiet_at"] = quiet
        out["backchannels"].append(entry)

    # Stretches where the caller is deliberately silent.
    starts = {e["id"]: e["t"] for e in events if e["type"] == "silence_start" and e.get("id")}
    ends = {e["id"]: e["t"] for e in events if e["type"] == "silence_end" and e.get("id")}
    for step_id, start in starts.items():
        end = ends.get(step_id, duration)
        onsets = [s for s, _ in segments if start <= s < end]
        out["windows"][step_id] = {
            "start": start, "end": end,
            "agent_onsets": [round(s, 3) for s in onsets],
            "agent_made_sound": any(e > start and s < end for s, e in segments),
        }

    out["reply_windows"] = {
        step_id: [round(turn["reply_window"][0], 3), round(turn["reply_window"][1], 3)]
        for turn in turns for step_id in turn["ids"] if step_id
    }
    return out
