"""Background noise for the noisy-line scenarios.

The three noises are generated, not downloaded, so the project needs no
outside data and stays reproducible:

  street   low rumble of traffic with passing vehicles and the odd horn
  crowd    many voices talking at once (the caller-voice model reading
           unrelated lines, a dozen of them layered)
  tv       one clear voice talking continuously in the background, with a
           music-like bed: the hardest case, since it is real speech
"""

import numpy as np
from scipy.signal import butter, lfilter

from arena.audio import SR, dbfs, to_float, to_int16

# Unrelated sentences for the background voices. None of them is about orders,
# bookings or phone numbers, so they cannot answer a scenario by accident.
BACKGROUND_LINES = [
    ("en-IN", "The monsoon reached the coast earlier than expected this year, and farmers are hopeful."),
    ("hi", "आज शाम को शहर के कई इलाकों में तेज़ बारिश होने की संभावना है।"),
    ("en-IN", "The home team needs forty runs from the last five overs to win the match."),
    ("hi", "सब्ज़ियों के दाम इस हफ़्ते फिर से बढ़ गए हैं और लोग परेशान हैं।"),
    ("en-IN", "Traffic on the ring road is moving slowly because of the metro construction work."),
    ("hi", "नई फ़िल्म ने पहले ही दिन सिनेमाघरों में अच्छी शुरुआत की है।"),
    ("en-IN", "Schools in the district will remain closed tomorrow on account of the festival."),
    ("hi", "दिल्ली से मुंबई जाने वाली ट्रेन आज दो घंटे की देरी से चल रही है।"),
]
BACKGROUND_VOICES = ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"]


def _lowpass(x: np.ndarray, hz: float, order: int = 2) -> np.ndarray:
    b, a = butter(order, hz / (SR / 2), btype="low")
    return lfilter(b, a, x)


def _bandpass(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    b, a = butter(2, [lo / (SR / 2), hi / (SR / 2)], btype="band")
    return lfilter(b, a, x)


def street(seconds: float, rng: np.random.Generator) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    rumble = _lowpass(rng.standard_normal(n), 250, order=3) * 4.0
    hiss = _bandpass(rng.standard_normal(n), 400, 3000) * 0.25
    out = rumble + hiss
    # Vehicles passing: slow swells of band-limited noise.
    for _ in range(int(seconds / 5)):
        centre, width = rng.uniform(0, seconds), rng.uniform(1.0, 2.5)
        swell = np.exp(-0.5 * ((t - centre) / width) ** 2)
        out += _bandpass(rng.standard_normal(n), 150, 1500) * swell * 1.2
    # Horns: short two-tone beeps.
    for _ in range(int(seconds / 7)):
        start, length = rng.uniform(0, seconds - 1), rng.uniform(0.25, 0.6)
        idx = (t >= start) & (t < start + length)
        f = rng.choice([420.0, 480.0, 520.0])
        out[idx] += 0.9 * (np.sin(2 * np.pi * f * t[idx]) + 0.6 * np.sin(2 * np.pi * f * 1.25 * t[idx]))
    return out.astype(np.float32)


def _voices(voice_factory, picks: list[tuple[int, int]]) -> list[np.ndarray]:
    clips = []
    for line, voice in picks:
        language, text = BACKGROUND_LINES[line % len(BACKGROUND_LINES)]
        speaker = voice_factory(BACKGROUND_VOICES[voice % len(BACKGROUND_VOICES)])
        clips.append(to_float(speaker.speak(text, language)))
    return clips


def _loop_to(clips: list[np.ndarray], n: int, gap: int, offset: int) -> np.ndarray:
    """Lay clips end to end with a gap, repeating until n samples are filled."""
    out = np.zeros(n + offset, dtype=np.float32)
    pos, k = 0, 0
    while pos < len(out):
        clip = clips[k % len(clips)]
        end = min(pos + len(clip), len(out))
        out[pos:end] = clip[: end - pos]
        pos = end + gap
        k += 1
    return out[offset:]


def crowd(seconds: float, rng: np.random.Generator, voice_factory) -> np.ndarray:
    n = int(seconds * SR)
    out = np.zeros(n, dtype=np.float32)
    for talker in range(12):
        picks = [(talker + j * 3, talker + j) for j in range(4)]
        track = _loop_to(_voices(voice_factory, picks), n, gap=int(0.3 * SR),
                         offset=int(rng.uniform(0, 5) * SR))
        out += track * rng.uniform(0.5, 1.0)
    out = _lowpass(out, 3500) + _lowpass(rng.standard_normal(n), 400) * 0.02
    return out.astype(np.float32)


def tv(seconds: float, rng: np.random.Generator, voice_factory) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    picks = [(j, j % 2) for j in range(len(BACKGROUND_LINES))]
    speech = _loop_to(_voices(voice_factory, picks), n, gap=int(0.5 * SR), offset=0)
    # A quiet chord drifting under the voice, like a programme's music bed.
    bed = sum(np.sin(2 * np.pi * f * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.2 * t + i))
              for i, f in enumerate([220.0, 277.2, 329.6]))
    out = _bandpass(speech, 200, 3800) + 0.02 * bed
    return out.astype(np.float32)


def build(kind: str, seconds: float, seed: int, voice_factory=None) -> np.ndarray:
    """Generate one noise file, normalised to -20 dBFS overall."""
    rng = np.random.default_rng(seed)
    if kind == "street":
        x = street(seconds, rng)
    elif kind == "crowd":
        x = crowd(seconds, rng, voice_factory)
    elif kind == "tv":
        x = tv(seconds, rng, voice_factory)
    else:
        raise ValueError(f"unknown noise {kind!r}")
    x = x * 10 ** ((-20.0 - dbfs(x)) / 20.0)
    return to_int16(x)


def at_level(noise: np.ndarray, level_dbfs: float) -> np.ndarray:
    """Scale a noise file to the given overall loudness."""
    return to_int16(to_float(noise) * 10 ** ((level_dbfs - dbfs(noise)) / 20.0))
