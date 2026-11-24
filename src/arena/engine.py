"""The real-time audio engine.

One conversation is a loop that ticks every 20 ms. On each tick the caller
produces a frame, the frame is handed to the agent, and the agent's frame for
the same tick is collected. Both sides can therefore talk at once. Both frames
are recorded side by side, so the recording is exactly what each side heard.

clock="real" paces the loop on a real clock, which every real agent needs.
clock="virtual" runs the same loop without waiting. It is only valid for the
fake agents, whose behaviour depends on frame counts and not on wall time.
"""

import asyncio
import time
from datetime import UTC, datetime

import numpy as np

from arena.agents.base import Agent
from arena.audio import FRAME, FRAME_MS, SR
from arena.caller import Caller

FRAME_S = FRAME_MS / 1000


async def run_conversation(
    agent: Agent, caller: Caller, *, clock: str = "real", max_seconds: float = 180.0
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Run one call. Returns (caller audio, agent audio, timeline)."""
    if clock not in ("real", "virtual"):
        raise ValueError(f"unknown clock {clock!r}")
    if clock == "virtual" and not agent.frame_synchronous:
        raise ValueError(f"{type(agent).__name__} needs a real clock")

    caller_frames: list[np.ndarray] = []
    agent_frames: list[np.ndarray] = []
    lateness: list[float] = []
    started_at = datetime.now(UTC).isoformat(timespec="seconds")

    await agent.connect()
    try:
        agent_frame = np.zeros(FRAME, dtype=np.int16)
        t0 = time.perf_counter()
        i = 0
        while not caller.done and i * FRAME_S < max_seconds:
            if clock == "real":
                wait = t0 + i * FRAME_S - time.perf_counter()
                if wait > 0:
                    await asyncio.sleep(wait)
                lateness.append(time.perf_counter() - (t0 + i * FRAME_S))
            caller_frame = caller.next_frame(i, agent_frame)
            for event in caller.new_events:
                agent.observe(event)
            await agent.send_audio(caller_frame)
            agent_frame = np.asarray(await agent.receive_audio(), dtype=np.int16)
            if len(agent_frame) != FRAME:
                raise ValueError(f"agent returned {len(agent_frame)} samples, expected {FRAME}")
            caller_frames.append(caller_frame)
            agent_frames.append(agent_frame)
            i += 1
    finally:
        await agent.close()

    late = np.array(lateness) * 1000 if lateness else np.zeros(1)
    timeline = {
        "scenario": caller.scenario["id"],
        "started_at": started_at,
        "sample_rate": SR,
        "frame_ms": FRAME_MS,
        "clock": clock,
        "duration_s": round(i * FRAME_S, 3),
        "completed": caller.done,
        "events": caller.events,
        "agent_events": agent.events,
        # How far behind the real clock the loop ran. Large values would mean
        # the machine was too busy and the timings in this run are suspect.
        "clock_lateness_ms": {
            "median": round(float(np.median(late)), 2),
            "p99": round(float(np.percentile(late, 99)), 2),
            "max": round(float(late.max()), 2),
        },
    }
    return np.concatenate(caller_frames), np.concatenate(agent_frames), timeline
