"""The scripted caller.

The caller walks through a scenario's steps one 20 ms frame at a time. It is
handed the agent's previous frame on every tick, so it can react to the agent
(wait for it to finish, cut in after it has talked for two seconds) while
staying fully scripted: the same agent behaviour always gets the same caller.

Every action is written to the event list with its exact time. The metrics
are computed from these events and the recording.
"""

import numpy as np

from arena.audio import FRAME, FRAME_MS, SR, dbfs
from arena.scenario import say_kind, step_type

FRAME_S = FRAME_MS / 1000


class Caller:
    def __init__(
        self,
        scenario: dict,
        clips: dict[int, np.ndarray],
        *,
        noise: np.ndarray | None = None,
        agent_threshold_dbfs: float = -45.0,
        agent_hangover_ms: float = 500.0,
        end_silence_ms: float = 1200.0,
        listen_timeout_s: float = 10.0,
        listen_max_s: float = 45.0,
        trigger_timeout_s: float = 20.0,
        tail_s: float = 1.0,
    ):
        self.scenario = scenario
        self.steps = scenario["steps"]
        self.clips = clips  # step index -> int16 audio for every say step
        self.noise = noise
        self.agent_threshold_dbfs = agent_threshold_dbfs
        self.hangover_frames = int(agent_hangover_ms / FRAME_MS)
        self.end_silence_frames = int(end_silence_ms / FRAME_MS)
        self.listen_timeout_s = listen_timeout_s
        self.listen_max_s = listen_max_s
        self.trigger_timeout_s = trigger_timeout_s
        self.tail_frames = int(tail_s / FRAME_S)

        self.events: list[dict] = []
        self.new_events: list[dict] = []  # events emitted on the current tick
        self.done = False
        self._k = 0  # index of the current step
        self._started: int | None = None  # frame at which the current step began
        self._pos = 0  # samples of the current clip already played
        self._agent_started = False  # has the agent spoken during this listen step
        self._finished_at: int | None = None

        # What the caller has heard of the agent so far.
        self._agent_last_active: int | None = None
        self._agent_run_start: int | None = None

    # -- hearing the agent ---------------------------------------------------

    def _hear(self, i: int, agent_frame: np.ndarray) -> None:
        """Update the caller's view of the agent with the frame from tick i-1."""
        if dbfs(agent_frame) > self.agent_threshold_dbfs:
            j = i - 1
            if self._agent_last_active is None or j - self._agent_last_active > self.hangover_frames:
                self._agent_run_start = j
            self._agent_last_active = j

    def _agent_speaking(self, i: int) -> bool:
        last = self._agent_last_active
        return last is not None and i - 1 - last <= self.hangover_frames

    def _agent_quiet_frames(self, i: int) -> int:
        last = self._agent_last_active
        return 10**9 if last is None else i - 1 - last

    # -- emitting events -----------------------------------------------------

    def _emit(self, event_type: str, t: float, **fields) -> None:
        event = {"t": round(t, 4), "type": event_type, "step": self._k, **fields}
        self.events.append(event)
        self.new_events.append(event)

    def _next_type(self) -> str | None:
        return step_type(self.steps[self._k + 1]) if self._k + 1 < len(self.steps) else None

    def _advance(self) -> None:
        self._k += 1
        self._started = None
        self._pos = 0
        self._agent_started = False

    # -- one tick --------------------------------------------------------------

    def next_frame(self, i: int, agent_frame: np.ndarray) -> np.ndarray:
        """Return the caller's audio for tick i."""
        self.new_events = []
        self._hear(i, agent_frame)
        out = self._step(i)
        if self.noise is not None:
            start = (i * FRAME) % (len(self.noise) - FRAME)
            mixed = out.astype(np.int32) + self.noise[start : start + FRAME]
            out = np.clip(mixed, -32768, 32767).astype(np.int16)
        return out

    def _step(self, i: int) -> np.ndarray:
        silent = np.zeros(FRAME, dtype=np.int16)
        now = i * FRAME_S
        while True:
            if self._k >= len(self.steps):
                if self._finished_at is None:
                    self._finished_at = i
                    self._emit("script_end", now)
                if i - self._finished_at >= self.tail_frames:
                    self.done = True
                return silent

            step = self.steps[self._k]
            kind = step_type(step)
            first = self._started is None
            if first:
                self._started = i
            elapsed = (i - self._started) * FRAME_S

            if kind == "say":
                clip = self.clips[self._k]
                if first:
                    self._emit(
                        "speech_start", now, kind=say_kind(step), id=step.get("id"),
                        text=step["say"], agent_speaking=self._agent_speaking(i),
                    )
                chunk = clip[self._pos : self._pos + FRAME]
                self._pos += FRAME
                if self._pos >= len(clip):
                    end = self._started * FRAME_S + len(clip) / SR
                    self._emit(
                        "speech_end", end, kind=say_kind(step), id=step.get("id"),
                        turn_end=self._next_type() != "pause",
                        expects_reply=self._next_type() in ("listen", "wait_agent_speech")
                        and say_kind(step) != "backchannel",
                    )
                    self._advance()
                    out = silent.copy()
                    out[: len(chunk)] = chunk
                    return out
                return chunk

            if kind == "pause":
                if first:
                    self._emit("pause_start", now, seconds=step["pause"])
                if elapsed >= step["pause"]:
                    self._emit("pause_end", now)
                    self._advance()
                    continue
                return silent

            if kind == "silence":
                if first:
                    self._emit("silence_start", now, id=step.get("id"), seconds=step["silence"])
                if elapsed >= step["silence"]:
                    self._emit("silence_end", now, id=step.get("id"))
                    self._advance()
                    continue
                return silent

            if kind == "listen":
                timeout = step["listen"].get("timeout", self.listen_timeout_s)
                if first:
                    self._emit("listen_start", now)
                    self._agent_started = self._agent_speaking(i)
                elif self._agent_last_active is not None and self._agent_last_active >= self._started:
                    self._agent_started = True
                if self._agent_started and self._agent_quiet_frames(i) >= self.end_silence_frames:
                    self._emit("listen_end", now, reason="agent_finished")
                elif not self._agent_started and elapsed >= timeout:
                    self._emit("listen_end", now, reason="no_response")
                elif elapsed >= self.listen_max_s:
                    self._emit("listen_end", now, reason="agent_still_talking")
                else:
                    return silent
                self._advance()
                continue

            if kind == "wait_agent_speech":
                spec = step["wait_agent_speech"]
                if first:
                    self._emit("wait_start", now, seconds=spec["for"])
                # Count only speech heard since this step began, so an agent that
                # was already talking over the caller does not trigger it early.
                run = self._agent_run_start
                talking_for = (i - 1 - max(run, self._started)) * FRAME_S if run is not None else 0.0
                if self._agent_speaking(i) and talking_for >= spec["for"]:
                    self._emit("wait_end", now, reason="triggered")
                    self._advance()
                    continue
                if elapsed >= spec.get("timeout", self.trigger_timeout_s):
                    # The agent never talked for long enough to cut into. The
                    # rest of the script depends on that, so the call ends here.
                    self._emit("wait_end", now, reason="agent_never_spoke_long_enough")
                    self._k = len(self.steps)
                    self._started = None
                    continue
                return silent

            raise ValueError(f"unknown step type in {step}")
