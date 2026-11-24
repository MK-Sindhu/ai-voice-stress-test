"""Voices: turning text into audio for the caller (and for the local agents).

Every voice has one method, speak(text, language, spoken=None), and returns
16 kHz int16 audio that starts and ends on sound (no silent lead-in or tail)
at a fixed loudness. `spoken` is an optional pronunciation override: Hinglish
lines are written the way people type them ("Friday ko table book karni hai")
and carry a Devanagari `spoken` form for the Hindi voice to read.

SyntheticVoice   bursts of noise, one per line. Used by the tests: fast, exact
                 and needs no model.
KokoroVoice      the open Kokoro text-to-speech model, running locally.
CachedVoice      wraps another voice and keeps every rendered line on disk.
"""

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from arena.audio import (
    FRAME,
    SR,
    normalize_level,
    read_mono,
    resample,
    to_int16,
    trim_silence,
    write_mono,
)

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")


def finish(audio: np.ndarray, level_dbfs: float, trim_dbfs: float) -> np.ndarray:
    """Set the loudness, cut silent ends and soften the edges of a clip."""
    audio = normalize_level(audio, level_dbfs)
    audio = trim_silence(audio, trim_dbfs).copy()
    ramp = min(80, len(audio) // 2)  # 5 ms fade so the clip does not click
    if ramp:
        audio[:ramp] *= np.linspace(0, 1, ramp, dtype=np.float32)
        audio[-ramp:] *= np.linspace(1, 0, ramp, dtype=np.float32)
    return to_int16(audio)


class SyntheticVoice:
    """A stand-in voice: steady noise whose length depends on the text."""

    name = "synthetic"

    def __init__(self, level_dbfs: float = -20.0, ms_per_char: float = 60.0):
        self.level_dbfs = level_dbfs
        self.ms_per_char = ms_per_char

    def fingerprint(self) -> dict:
        return {"engine": "synthetic", "level_dbfs": self.level_dbfs}

    def speak(self, text: str, language: str, spoken: str | None = None) -> np.ndarray:
        ms = min(max(len(text) * self.ms_per_char, 300), 6000)
        frames = round(ms / 20)
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
        noise = np.random.default_rng(seed).uniform(-1, 1, frames * FRAME)
        amp = 10 ** (self.level_dbfs / 20) * np.sqrt(3)  # uniform noise: rms = amp / sqrt(3)
        return to_int16((noise * amp).astype(np.float32))


class KokoroVoice:
    """Kokoro-82M, an open text-to-speech model (Apache 2.0)."""

    name = "kokoro"

    def __init__(
        self,
        voice: str = "hf_alpha",
        english_accent: str = "b",
        speed: float = 1.0,
        level_dbfs: float = -20.0,
        trim_dbfs: float = -45.0,
    ):
        self.voice = voice
        self.english_accent = english_accent  # "a" American or "b" British phoneme set
        self.speed = speed
        self.level_dbfs = level_dbfs
        self.trim_dbfs = trim_dbfs
        self._pipelines: dict = {}

    def fingerprint(self) -> dict:
        return {
            "engine": "kokoro", "voice": self.voice, "english_accent": self.english_accent,
            "speed": self.speed, "level_dbfs": self.level_dbfs, "trim_dbfs": self.trim_dbfs,
        }

    def _pipeline(self, lang_code: str):
        if lang_code not in self._pipelines:
            from kokoro import KPipeline

            self._pipelines[lang_code] = KPipeline(lang_code=lang_code, repo_id="hexgrad/Kokoro-82M")
        return self._pipelines[lang_code]

    def _render(self, text: str, lang_code: str) -> np.ndarray:
        parts = [
            np.asarray(result.audio, dtype=np.float32)
            for result in self._pipeline(lang_code)(text, voice=self.voice, speed=self.speed)
            if result.audio is not None
        ]
        if not parts:
            return np.zeros(0, dtype=np.float32)
        return resample(np.concatenate(parts), 24000, SR)

    def speak(self, text: str, language: str, spoken: str | None = None) -> np.ndarray:
        text = spoken or text
        pieces = []
        for chunk, is_hindi in split_by_script(text):
            pieces.append(self._render(chunk, "h" if is_hindi else self.english_accent))
        audio = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)
        return finish(audio, self.level_dbfs, self.trim_dbfs)


def split_by_script(text: str) -> list[tuple[str, bool]]:
    """Split text into runs to be read by the Hindi or the English voice.

    Text with any Devanagari goes to the Hindi voice whole, unless it also has
    Latin-script words, in which case each run goes to its own voice. Digits
    and punctuation stay with the run they are in.
    """
    has_hindi, has_latin = bool(DEVANAGARI.search(text)), bool(LATIN.search(text))
    if not has_hindi:
        return [(text, False)]
    if not has_latin:
        return [(text, True)]
    runs: list[tuple[str, bool]] = []
    current, current_hindi = [], None
    for word in text.split():
        if DEVANAGARI.search(word):
            is_hindi = True
        elif LATIN.search(word):
            is_hindi = False
        else:  # digits, punctuation: keep with the current run
            is_hindi = current_hindi if current_hindi is not None else True
        if current and is_hindi != current_hindi:
            runs.append((" ".join(current), current_hindi))
            current = []
        current.append(word)
        current_hindi = is_hindi
    if current:
        runs.append((" ".join(current), current_hindi))
    return runs


class CachedVoice:
    """Keeps every rendered line on disk, named by a hash of the text and the
    voice settings. Changing one scenario line re-renders only that line."""

    def __init__(self, voice, cache_dir: Path):
        self.voice = voice
        self.cache_dir = Path(cache_dir)
        self.name = voice.name

    def fingerprint(self) -> dict:
        return self.voice.fingerprint()

    def path_for(self, text: str, language: str, spoken: str | None = None) -> Path:
        key = json.dumps(
            [self.voice.fingerprint(), text, language, spoken], sort_keys=True, ensure_ascii=False
        )
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:20] + ".wav")

    def speak(self, text: str, language: str, spoken: str | None = None) -> np.ndarray:
        path = self.path_for(text, language, spoken)
        if path.exists():
            return read_mono(path)
        audio = self.voice.speak(text, language, spoken)
        write_mono(path, audio)
        return audio


def build_voice(config: dict, cache_dir: Path | None = None):
    """Create a voice from a params.yaml block such as {engine: kokoro, voice: hf_alpha}."""
    config = dict(config)
    engine = config.pop("engine")
    if engine == "synthetic":
        voice = SyntheticVoice(level_dbfs=config.get("level_dbfs", -20.0))
    elif engine == "kokoro":
        voice = KokoroVoice(**config)
    else:
        raise ValueError(f"unknown voice engine {engine!r}")
    return CachedVoice(voice, cache_dir) if cache_dir else voice
