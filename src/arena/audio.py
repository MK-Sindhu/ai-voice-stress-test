"""Audio helpers shared by the caller, the engine and the metrics.

Everything in the arena is 16 kHz mono 16-bit audio, moved in 20 ms frames
(320 samples). Loudness is measured in dBFS: 0 is the loudest a 16-bit sample
can be, -45 is very quiet.
"""

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SR = 16000
FRAME_MS = 20
FRAME = SR * FRAME_MS // 1000  # 320 samples
HOP_MS = 10  # loudness is measured every 10 ms
HOP = SR * HOP_MS // 1000
SILENT_FRAME = np.zeros(FRAME, dtype=np.int16)


def to_float(x: np.ndarray) -> np.ndarray:
    if x.dtype == np.int16:
        return x.astype(np.float32) / 32768.0
    return x.astype(np.float32)


def to_int16(x: np.ndarray) -> np.ndarray:
    if x.dtype == np.int16:
        return x
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)


def dbfs(x: np.ndarray) -> float:
    """Loudness (RMS) of a block of samples, in dBFS."""
    x = to_float(x)
    if len(x) == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(x * x)))
    return 20.0 * np.log10(max(rms, 1e-6))


def loudness_track(x: np.ndarray) -> np.ndarray:
    """Loudness of every 10 ms slice, in dBFS."""
    x = to_float(x)
    n = len(x) // HOP
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    blocks = x[: n * HOP].reshape(n, HOP)
    rms = np.sqrt(np.mean(blocks * blocks, axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-6))


def active_mask(x: np.ndarray, threshold_dbfs: float) -> np.ndarray:
    """True for every 10 ms slice that is louder than the threshold."""
    return loudness_track(x) > threshold_dbfs


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Runs of True in a boolean array as (start, end) index pairs, end exclusive."""
    if len(mask) == 0:
        return []
    padded = np.concatenate([[False], mask, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist()))


def speech_segments(
    x: np.ndarray, threshold_dbfs: float, min_speech_ms: float, merge_gap_ms: float
) -> list[tuple[float, float]]:
    """Stretches of sound as (start, end) in seconds.

    Sound separated by a gap shorter than merge_gap_ms counts as one stretch
    (speech has short gaps inside words and between sentences). A stretch with
    less than min_speech_ms of actual sound is dropped as a click.
    """
    mask = active_mask(x, threshold_dbfs)
    merged: list[list[int]] = []
    sound: list[int] = []
    for start, end in _runs(mask):
        if merged and (start - merged[-1][1]) * HOP_MS < merge_gap_ms:
            merged[-1][1] = end
            sound[-1] += end - start
        else:
            merged.append([start, end])
            sound.append(end - start)
    return [
        (s * HOP_MS / 1000, e * HOP_MS / 1000)
        for (s, e), n in zip(merged, sound)
        if n * HOP_MS >= min_speech_ms
    ]


def first_silence(
    x: np.ndarray, start_s: float, threshold_dbfs: float, min_silence_ms: float
) -> float | None:
    """The first moment at or after start_s from which the audio stays quiet
    for at least min_silence_ms. None if it never does."""
    mask = active_mask(x, threshold_dbfs)
    first = int(round(start_s * 1000 / HOP_MS))
    need = int(round(min_silence_ms / HOP_MS))
    quiet = ~mask[first:]
    for s, e in _runs(quiet):
        # Silence that runs to the end of the recording counts as long enough.
        if e - s >= need or first + e == len(mask):
            return (first + s) * HOP_MS / 1000
    return None


def trim_silence(x: np.ndarray, threshold_dbfs: float) -> np.ndarray:
    """Cut the quiet lead-in and tail, so a clip starts and ends on sound."""
    mask = active_mask(x, threshold_dbfs)
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return x[:0]
    return x[idx[0] * HOP : (idx[-1] + 1) * HOP]


def normalize_level(x: np.ndarray, target_dbfs: float, gate_dbfs: float = -50.0) -> np.ndarray:
    """Scale a clip so its speech (ignoring silences) sits at target_dbfs."""
    x = to_float(x)
    track = loudness_track(x)
    loud = track > gate_dbfs
    if not loud.any():
        return x
    n = len(track) * HOP
    blocks = x[:n].reshape(-1, HOP)[loud]
    level = 20.0 * np.log10(max(float(np.sqrt(np.mean(blocks * blocks))), 1e-6))
    gain = 10.0 ** ((target_dbfs - level) / 20.0)
    peak = float(np.max(np.abs(x))) * gain
    if peak > 0.98:  # never clip
        gain *= 0.98 / peak
    return x * gain


def resample(x: np.ndarray, sr_from: int, sr_to: int = SR) -> np.ndarray:
    if sr_from == sr_to:
        return x
    g = int(np.gcd(sr_from, sr_to))
    return resample_poly(to_float(x), sr_to // g, sr_from // g).astype(np.float32)


def write_stereo(path: Path, left: np.ndarray, right: np.ndarray) -> None:
    """Caller on the left channel, agent on the right."""
    n = max(len(left), len(right))
    out = np.zeros((n, 2), dtype=np.int16)
    out[: len(left), 0] = left
    out[: len(right), 1] = right
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, out, SR, subtype="PCM_16")


def read_stereo(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data, sr = sf.read(path, dtype="int16", always_2d=True)
    assert sr == SR, f"{path} is {sr} Hz, expected {SR}"
    return data[:, 0].copy(), data[:, 1].copy()


def write_mono(path: Path, x: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, to_int16(x), SR, subtype="PCM_16")


def read_mono(path: Path) -> np.ndarray:
    data, sr = sf.read(path, dtype="int16", always_2d=True)
    assert sr == SR, f"{path} is {sr} Hz, expected {SR}"
    return data[:, 0].copy()
