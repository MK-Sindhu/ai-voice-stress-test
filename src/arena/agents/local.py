"""The local baseline agent: an ordinary voice pipeline built from open models.

    caller audio -> voice activity detection (Silero)
                 -> end-of-turn decision   (silence timeout, or the detector)
                 -> speech recognition     (faster-whisper)
                 -> language model         (Ollama)
                 -> text to speech         (Kokoro)
                 -> agent audio

It behaves the way a straightforward pipeline does:
  - it decides the caller has finished after a fixed length of silence;
  - if the caller speaks again before it has started answering, it drops the
    answer it was preparing and keeps listening;
  - if the caller speaks while it is talking, it stops (any speech, including
    a short "hmm", counts);
  - if nobody says anything for a while, it asks whether the caller is there.

Everything heavy runs in worker threads, so the engine's 20 ms clock is not
held up. The agent only ever sees the caller's audio.
"""

import json
import queue
import re
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from arena.agents.base import Agent
from arena.audio import FRAME, SR, to_float
from arena.config import REPO_ROOT
from arena.transcribe import pick_device
from arena.voices import KokoroVoice

VAD_WINDOW = 512  # samples per voice-activity decision (32 ms), fixed by Silero
VAD_MS = VAD_WINDOW * 1000 / SR
SENTENCE_END = re.compile(r"(?<=[.!?।])\s+|\n+")
CLAUSE_END = re.compile(r"(?<=[,;:])\s+")
LANGUAGE_RULE = {
    "en": "The caller is speaking English. Reply only in English.",
    "hi": "The caller is speaking Hindi or Hinglish. Reply only in Hindi, written in Devanagari script.",
}
LANGUAGE_NAMES = {"hi": "hinglish", "en": "en-IN"}  # recogniser language -> voice language


class Cancelled(Exception):
    pass


class SilenceEndpointer:
    """The caller has finished once they have been quiet for timeout_ms."""

    def __init__(self, timeout_ms: float):
        self.timeout_ms = timeout_ms

    def reset(self) -> None:
        pass

    def finished(self, silence_ms: float, utterance: np.ndarray) -> bool:
        return silence_ms >= self.timeout_ms


class DetectorEndpointer:
    """Ask the end-of-turn detector from the sibling project.

    After ask_after_ms of quiet the model hears the utterance so far and
    estimates whether the caller is finished. If it says yes, the agent
    answers at once; if not, the agent keeps waiting, up to fallback_ms.
    """

    def __init__(self, repo: str, threshold: float, ask_after_ms: float = 200,
                 fallback_ms: float = 1500, encoder: str = "openai/whisper-tiny",
                 max_seconds: float = 8.0):
        import sys

        import torch

        repo_path = (REPO_ROOT / repo).resolve()
        sys.path.insert(0, str(repo_path / "src"))
        from indic_eot.audio_model import AudioEOT, FeaturePrep

        self.torch = torch
        self.threshold = threshold
        self.ask_after_ms = ask_after_ms
        self.fallback_ms = fallback_ms
        self.prep = FeaturePrep(encoder, max_seconds, SR)
        self.model = AudioEOT(encoder, max_seconds, 0.0)
        self.model.load_state_dict(torch.load(repo_path / "models" / "audio" / "model.pt", map_location="cpu"))
        self.model.eval()
        self.asked = False
        self.verdict = False
        self.last_probability: float | None = None

    def reset(self) -> None:
        self.asked = False
        self.verdict = False

    def probability(self, utterance: np.ndarray) -> float:
        with self.torch.no_grad():
            mel, mask = self.prep([to_float(utterance)])
            return float(self.torch.sigmoid(self.model(mel, mask))[0])

    def finished(self, silence_ms: float, utterance: np.ndarray) -> bool:
        if silence_ms >= self.fallback_ms:
            return True
        if silence_ms >= self.ask_after_ms and not self.asked:
            self.asked = True
            self.last_probability = self.probability(utterance)
            self.verdict = self.last_probability >= self.threshold
        return self.verdict


class LocalAgent(Agent):
    def __init__(
        self,
        endpointing: dict,
        asr: dict,
        llm: dict,
        voice: dict,
        interrupt_min_ms: float = 250,
        idle_checkin_s: float | None = 6.0,
        checkin_text: dict | None = None,
        system_prompt: str = "prompts/agent_system.md",
    ):
        super().__init__()
        import httpx
        import torch
        from faster_whisper import WhisperModel
        from silero_vad import load_silero_vad

        self.torch = torch
        self.vad = load_silero_vad(onnx=True)
        self.asr_config = asr
        self.whisper = WhisperModel(asr["model"], device=pick_device(asr.get("device", "auto")),
                                    compute_type=asr.get("compute_type", "default"))
        self.llm = llm
        self.http = httpx.Client(timeout=60)
        voice = {k: v for k, v in voice.items() if k != "engine"}
        self.voice = KokoroVoice(**voice)
        self.system_prompt = Path(REPO_ROOT / system_prompt).read_text(encoding="utf-8")
        self.interrupt_min_ms = interrupt_min_ms
        self.idle_checkin_s = idle_checkin_s
        self.checkin_text = checkin_text or {"en-IN": "Hello, are you still there?",
                                             "hinglish": "हेलो, क्या आप लाइन पर हैं?"}
        endpointing = dict(endpointing)
        kind = endpointing.pop("type")
        self.endpointer = SilenceEndpointer(**endpointing) if kind == "silence" \
            else DetectorEndpointer(**endpointing)
        self.asr_start_ms = 200  # start recognising this soon after the caller goes quiet
        self._warm_up()

    def _warm_up(self) -> None:
        """Load every model into memory, so the first call is not slower than the rest."""
        self.whisper.transcribe(np.zeros(SR, dtype=np.float32), language="en")
        self.voice.speak("Hello.", "en-IN")
        self.voice.speak("नमस्ते।", "hi")
        self._chat([{"role": "user", "content": "Hello"}], threading.Event(), lambda s: None)
        if isinstance(self.endpointer, DetectorEndpointer):
            self.endpointer.probability(np.zeros(SR, dtype=np.int16))

    # -- call lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        self.vad.reset_states()
        self.endpointer.reset()
        self._in: queue.Queue = queue.Queue()
        self._out: deque = deque()
        self._out_lock = threading.Lock()
        self._jobs: queue.Queue = queue.Queue()
        self._closed = False
        self._audio = np.zeros(0, dtype=np.int16)  # everything heard so far
        self._pending = np.zeros(0, dtype=np.int16)  # samples not yet through the VAD
        self._history: list[dict] = []
        self._language: str | None = None  # fixed after the first utterance
        self._utt_start: int | None = None  # sample where the open utterance begins
        self._speech_run_ms = 0.0
        self._in_speech = False
        self._silence_ms = 0.0
        self._state = "idle"  # idle | thinking | speaking
        self._cancel = threading.Event()
        self._asr_job: dict | None = None
        self._last_activity = 0.0
        self._checkins = 0
        self._brain = threading.Thread(target=self._brain_loop, daemon=True)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._brain.start()
        self._worker.start()

    async def send_audio(self, frame: np.ndarray) -> None:
        self._in.put(frame)

    async def receive_audio(self) -> np.ndarray:
        with self._out_lock:
            if self._out:
                return self._out.popleft()
        return self.silence()

    async def close(self) -> None:
        self._closed = True
        self._cancel.set()
        self._in.put(None)
        self._jobs.put(None)
        self._brain.join(timeout=10)
        self._worker.join(timeout=30)

    # -- helpers -----------------------------------------------------------------

    def _now(self) -> float:
        return len(self._audio) / SR

    def _note(self, kind: str, **fields) -> None:
        self.events.append({"t": round(self._now(), 3), "type": kind, **fields})

    def _playing(self) -> bool:
        with self._out_lock:
            return bool(self._out)

    def _stop_everything(self) -> None:
        """Drop whatever is being prepared or spoken."""
        self._cancel.set()
        self._cancel = threading.Event()
        self._asr_job = None
        with self._out_lock:
            self._out.clear()

    # -- the brain: listens, and decides when to answer -----------------------------

    def _brain_loop(self) -> None:
        while not self._closed:
            frame = self._in.get()
            if frame is None:
                return
            self._audio = np.concatenate([self._audio, frame])
            self._pending = np.concatenate([self._pending, frame])
            while len(self._pending) >= VAD_WINDOW:
                window, self._pending = self._pending[:VAD_WINDOW], self._pending[VAD_WINDOW:]
                self._on_window(window)
            if self._state == "speaking" and not self._playing() and self._reply_done:
                self._state = "idle"
                self._last_activity = self._now()
            self._maybe_check_in()

    def _on_window(self, window: np.ndarray) -> None:
        prob = self.vad(self.torch.from_numpy(to_float(window)), SR).item()
        if prob >= 0.5:
            self._speech_run_ms += VAD_MS
            self._silence_ms = 0.0
        else:
            if prob < 0.35:
                self._silence_ms += VAD_MS
            if self._silence_ms >= 100:
                self._speech_run_ms = 0.0

        needed = self.interrupt_min_ms if self._state == "speaking" else 96
        if not self._in_speech and self._speech_run_ms >= needed:
            self._in_speech = True
            self._on_speech_start()
        elif self._in_speech:
            self._last_activity = self._now()
            if self._silence_ms >= self.asr_start_ms and self._asr_job is None \
                    and self._state == "idle":
                self._start_recognising()
            if self._state == "idle" and self._silence_ms >= 100 and self.endpointer.finished(
                self._silence_ms, self._audio[self._utt_start :]
            ):
                self._in_speech = False
                self._on_end_of_turn()

    def _on_speech_start(self) -> None:
        onset = max(0, len(self._audio) - int((self._speech_run_ms + 300) * SR / 1000))
        self.endpointer.reset()
        self._checkins = 0
        if self._state == "speaking":
            self._note("interrupted_by_caller")
            self._stop_everything()
            self._utt_start = onset
        elif self._state == "thinking":
            # The caller carried on before we said anything: keep listening.
            self._note("reply_abandoned_caller_resumed")
            self._stop_everything()
        else:
            self._asr_job = None
            if self._utt_start is None:
                self._utt_start = onset
        self._state = "idle"

    def _start_recognising(self) -> None:
        """Begin speech recognition early, while still waiting to be sure the
        caller has finished. If they carry on, the result is thrown away."""
        if self._utt_start is None:
            self._utt_start = max(0, len(self._audio) - 8 * SR)
        job = {"kind": "asr", "audio": self._audio[self._utt_start :].copy(),
               "cancel": self._cancel, "done": threading.Event(), "text": None}
        self._asr_job = job
        self._jobs.put(job)

    def _on_end_of_turn(self) -> None:
        note = {"silence_ms": round(self._silence_ms)}
        if isinstance(self.endpointer, DetectorEndpointer):
            note["detector_probability"] = round(self.endpointer.last_probability or 0.0, 3)
        self._note("end_of_turn_decided", **note)
        if self._asr_job is None:
            self._start_recognising()
        self._state = "thinking"
        self._reply_done = False
        self._jobs.put({"kind": "reply", "asr": self._asr_job, "cancel": self._cancel})

    def _maybe_check_in(self) -> None:
        if self.idle_checkin_s is None or self._state != "idle" or self._in_speech:
            return
        if not self._history or self._checkins >= 2:
            return
        if self._now() - self._last_activity >= self.idle_checkin_s:
            self._checkins += 1
            self._state = "thinking"
            self._reply_done = False
            self._jobs.put({"kind": "checkin", "cancel": self._cancel})

    # -- the worker: recognises, thinks, speaks -------------------------------------

    def _worker_loop(self) -> None:
        while not self._closed:
            job = self._jobs.get()
            if job is None:
                return
            try:
                if job["kind"] == "asr":
                    self._recognise(job)
                elif job["kind"] == "reply":
                    self._reply(job)
                elif job["kind"] == "checkin":
                    self._say(self.checkin_text[LANGUAGE_NAMES.get(self._language, "en-IN")], job["cancel"])
                    self._finish_reply(job["cancel"])
            except Cancelled:
                pass
            except Exception as error:  # keep the call alive; the failure shows up as silence
                self._note("error", message=repr(error)[:300])
                self._finish_reply(job["cancel"])

    def _recognise(self, job: dict) -> None:
        if job["cancel"].is_set():
            return
        t0 = time.perf_counter()
        audio = to_float(job["audio"])
        language = self._language
        if language is None:
            _, _, probs = self.whisper.detect_language(audio)
            scores = dict(probs)
            language = max(("hi", "en"), key=lambda lang: scores.get(lang, 0.0))
        segments, _ = self.whisper.transcribe(
            audio, language=language, beam_size=self.asr_config.get("beam_size", 1),
            condition_on_previous_text=False, without_timestamps=True, temperature=0.0,
        )
        job["text"] = " ".join(s.text.strip() for s in segments).strip()
        job["language"] = language
        job["ms"] = round((time.perf_counter() - t0) * 1000)
        job["done"].set()

    def _reply(self, job: dict) -> None:
        cancel, asr = job["cancel"], job["asr"]
        while not asr["done"].wait(timeout=0.02):
            if cancel.is_set():
                raise Cancelled
        if cancel.is_set():
            raise Cancelled
        text = asr["text"]
        self._note("heard", text=text, language=asr["language"], asr_ms=asr["ms"])
        if len(text) < 2:
            self._utt_start = None
            self._finish_reply(cancel)
            return
        if self._language is None:
            self._language = asr["language"]
        system = f"{self.system_prompt}\n{LANGUAGE_RULE[self._language]}"
        messages = [{"role": "system", "content": system}, *self._history,
                    {"role": "user", "content": text}]
        spoken: list[str] = []
        t0 = time.perf_counter()

        def on_sentence(sentence: str) -> None:
            first = not spoken
            if first:
                self._note("first_sentence_ready", llm_ms=round((time.perf_counter() - t0) * 1000))
            self._say(sentence, cancel)  # raises Cancelled if the caller spoke first
            if first:
                # Audio is now playing, so the caller's turn counts as answered:
                # remember the exchange and start a fresh utterance.
                self._history.append({"role": "user", "content": text})
                self._history.append({"role": "assistant", "content": ""})
                self._utt_start = None
                self._asr_job = None
            spoken.append(sentence)
            self._history[-1]["content"] = " ".join(spoken)

        try:
            self._chat(messages, cancel, on_sentence)
        finally:
            if spoken:
                self._note("said", text=" ".join(spoken), cut_short=cancel.is_set())
        self._finish_reply(cancel)

    def _finish_reply(self, cancel: threading.Event) -> None:
        if not cancel.is_set():
            self._reply_done = True
            if self._state == "thinking":  # nothing was said
                self._state = "idle"
                self._last_activity = self._now()

    def _chat(self, messages: list[dict], cancel: threading.Event, on_sentence) -> None:
        """Stream a reply from the language model, handing over whole sentences."""
        body = {
            "model": self.llm["model"], "messages": messages, "stream": True,
            "keep_alive": "30m",
            "options": {"temperature": self.llm.get("temperature", 0.0), "seed": 1,
                        "num_predict": self.llm.get("max_tokens", 160)},
        }
        url = self.llm.get("url", "http://localhost:11434") + "/api/chat"
        buffer = ""
        with self.http.stream("POST", url, json=body) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if cancel.is_set():
                    raise Cancelled
                if not line:
                    continue
                buffer += json.loads(line).get("message", {}).get("content", "")
                parts = SENTENCE_END.split(buffer)
                if len(parts) == 1 and len(buffer) > 60:
                    # A long sentence: start speaking at the first comma
                    # rather than waiting for the full stop.
                    parts = CLAUSE_END.split(buffer, maxsplit=1)
                for sentence in parts[:-1]:
                    if sentence.strip():
                        on_sentence(sentence.strip())
                buffer = parts[-1]
        if buffer.strip() and not cancel.is_set():
            on_sentence(buffer.strip())

    def _say(self, text: str, cancel: threading.Event) -> None:
        """Turn one sentence into audio and queue it for playing."""
        text = re.sub(r"[*_#`]+", "", text).strip()
        if not text:
            return
        language = "hinglish" if re.search(r"[ऀ-ॿ]", text) else "en-IN"
        audio = self.voice.speak(text, language)
        if cancel.is_set():
            raise Cancelled
        gap = np.zeros(int(0.15 * SR), dtype=np.int16)  # a breath between sentences
        audio = np.concatenate([audio, gap])
        pad = (-len(audio)) % FRAME
        audio = np.concatenate([audio, np.zeros(pad, dtype=np.int16)])
        with self._out_lock:
            if cancel.is_set():
                raise Cancelled
            self._out.extend(audio.reshape(-1, FRAME))
        if self._state == "thinking":
            self._state = "speaking"
            self._note("started_speaking")
