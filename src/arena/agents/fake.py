"""Fake agents with known behaviour.

These exist to prove the metrics measure correctly. A fake agent that replies
exactly 500 ms after the caller stops must be measured at 500 ms; one that
never stops when interrupted must be reported as never stopping.

FakeAgent   hears only the caller's audio, like a real agent, and reacts with
            exact, configured timings. Its "speech" is a tone.
OracleAgent is told the caller's script and speaks a prepared reply to every
            turn. It checks the content metrics (was the right order number
            read back?) and proves every scenario can be passed.
"""

import numpy as np

from arena.agents.base import Agent
from arena.audio import FRAME, FRAME_MS, SR, dbfs
from arena.scenario import REPLY_STEPS, step_type


def tone(ms: float, hz: float = 440.0, level_dbfs: float = -20.0) -> np.ndarray:
    n = int(SR * ms / 1000)
    amp = 10 ** (level_dbfs / 20) * np.sqrt(2)
    return (np.sin(2 * np.pi * hz * np.arange(n) / SR) * amp * 32767).astype(np.int16)


class FakeAgent(Agent):
    """Reacts to the caller's audio with exact timings.

    response_delay_ms   replies this long after the caller goes quiet
    reply_ms            how long each reply lasts
    stop_after_ms       when the caller talks over it, goes silent this long
                        after the caller started; None means it never stops
    min_interrupt_ms    ignores caller speech shorter than this while talking
                        (so a short "hmm" does not stop it)
    checkin_after_ms    speaks again if nobody has said anything for this long
    silent              never says anything at all
    """

    frame_synchronous = True
    GAP_FRAMES = 5  # 100 ms without caller sound ends a short sound

    def __init__(
        self,
        response_delay_ms: float = 500,
        reply_ms: float = 3000,
        stop_after_ms: float | None = 200,
        min_interrupt_ms: float = 0,
        checkin_after_ms: float | None = None,
        silent: bool = False,
        threshold_dbfs: float = -45.0,
    ):
        super().__init__()
        self.delay_frames = round(response_delay_ms / FRAME_MS)
        self.reply = tone(reply_ms)
        self.stop_frames = None if stop_after_ms is None else round(stop_after_ms / FRAME_MS)
        self.min_interrupt_frames = round(min_interrupt_ms / FRAME_MS)
        self.checkin_frames = None if checkin_after_ms is None else round(checkin_after_ms / FRAME_MS)
        self.silent = silent
        self.threshold_dbfs = threshold_dbfs

    async def connect(self) -> None:
        self._i = 0
        self._last_heard: int | None = None  # last frame with caller sound
        self._owes_reply = False  # the caller has said something we have not answered
        self._playing: np.ndarray | None = None
        self._pos = 0
        self._overlap_start: int | None = None  # when the caller started talking over us
        self._last_spoke: int | None = None

    def _start(self, audio: np.ndarray) -> None:
        self._playing, self._pos = audio, 0
        self._owes_reply = False
        self._overlap_start = None

    async def send_audio(self, frame: np.ndarray) -> None:
        i = self._i
        talking = self._playing is not None
        if dbfs(frame) > self.threshold_dbfs:
            self._last_heard = i
            if not talking:
                self._owes_reply = True
            elif self._overlap_start is None:
                self._overlap_start = i
        quiet_for = 10**9 if self._last_heard is None else i - self._last_heard - 1

        if talking and self._overlap_start is not None:
            overlap = self._last_heard - self._overlap_start + 1  # frames of caller speech so far
            long_enough = overlap >= self.min_interrupt_frames
            if long_enough:
                self._owes_reply = True
            elif quiet_for >= self.GAP_FRAMES:
                self._overlap_start = None  # a short sound, not an interruption
            if long_enough and self.stop_frames is not None \
                    and i - self._overlap_start >= self.stop_frames:
                self._playing = None
        elif not talking and not self.silent:
            if self._owes_reply and quiet_for >= self.delay_frames:
                self._start(self.reply)
            elif self.checkin_frames is not None and self._last_spoke is not None \
                    and min(quiet_for, i - self._last_spoke - 1) == self.checkin_frames:
                self._start(self.reply)

    async def receive_audio(self) -> np.ndarray:
        out = self.silence()
        if self._playing is not None:
            chunk = self._playing[self._pos : self._pos + FRAME]
            out[: len(chunk)] = chunk
            self._pos += FRAME
            self._last_spoke = self._i
            if self._pos >= len(self._playing):
                self._playing = None
        self._i += 1
        return out


class OracleAgent(Agent):
    """An agent that is handed the script. Not a real agent: a measuring stick.

    It replies response_delay_ms after each caller turn truly ends, stops
    stop_after_ms after a barge-in begins, ignores backchannels and noise, and
    checks in during long silences. What it says comes from the scenario file:
    the `oracle` text of each reply step (variant "good") or the `wrong` text
    (variant "wrong", which states an incorrect detail on purpose).
    """

    frame_synchronous = True

    def __init__(
        self,
        variant: str = "good",
        response_delay_ms: float = 600,
        stop_after_ms: float = 200,
        checkin_after_ms: float = 4000,
        filler_ms: float = 8000,
    ):
        super().__init__()
        assert variant in ("good", "wrong")
        self.variant = variant
        self.delay_s = response_delay_ms / 1000
        self.stop_s = stop_after_ms / 1000
        self.checkin_s = checkin_after_ms / 1000
        self.filler = tone(filler_ms)
        self.replies: dict[int, np.ndarray] = {}  # reply step index -> audio
        self.checkin: np.ndarray = tone(1500)

    def prepare(self, scenario: dict, context: dict) -> None:
        """Render what to say at each reply step. Steps with no text get a tone."""
        voice = context["agent_voice"]
        language = scenario["language"]
        self.replies = {}
        for index, step in enumerate(scenario["steps"]):
            if step_type(step) not in REPLY_STEPS:
                continue
            slot = step[step_type(step)]
            text = slot.get("oracle")
            spoken = slot.get("oracle_spoken")
            if self.variant == "wrong" and "wrong" in slot:
                text, spoken = slot["wrong"], slot.get("wrong_spoken")
            self.replies[index] = voice.speak(text, language, spoken) if text else self.filler
        self.checkin = voice.speak(context["checkin_text"][language], language)

    async def connect(self) -> None:
        self._i = 0
        self._plan: list[tuple[float, str, int]] = []  # (time, action, reply step)
        self._playing: np.ndarray | None = None
        self._pos = 0

    def observe(self, event: dict) -> None:
        t, kind = event["t"], event["type"]
        if kind == "speech_end" and event["expects_reply"]:
            self._plan.append((t + self.delay_s, "reply", event["step"] + 1))
        elif kind == "speech_start" and event["kind"] == "barge_in":
            self._plan.append((t + self.stop_s, "stop", -1))
        elif kind == "silence_start" and event["seconds"] > self.checkin_s + 2:
            self._plan.append((t + self.checkin_s, "checkin", -1))

    async def send_audio(self, frame: np.ndarray) -> None:
        now = self._i * FRAME_MS / 1000
        due = [p for p in self._plan if p[0] <= now + 1e-9]
        self._plan = [p for p in self._plan if p[0] > now + 1e-9]
        for _, action, step in due:
            if action == "stop":
                self._playing = None
            elif action == "checkin" and self._playing is None:
                self._playing, self._pos = self.checkin, 0
            elif action == "reply":
                self._playing, self._pos = self.replies.get(step, self.filler), 0

    async def receive_audio(self) -> np.ndarray:
        out = self.silence()
        if self._playing is not None:
            chunk = self._playing[self._pos : self._pos + FRAME]
            out[: len(chunk)] = chunk
            self._pos += FRAME
            if self._pos >= len(self._playing):
                self._playing = None
        self._i += 1
        return out
