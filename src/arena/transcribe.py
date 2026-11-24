"""Speech recognition, used offline to read back what was said.

It serves two jobs: checking that the caller's rendered lines are
intelligible, and reading the agent's replies so their content can be scored.
The model is faster-whisper, running locally.
"""

import numpy as np

from arena.audio import to_float

LANGUAGES = ("hi", "en")  # the arena only deals with Hindi and English


class Transcriber:
    def __init__(self, model: str = "large-v3-turbo", device: str = "auto", compute_type: str = "default"):
        from faster_whisper import WhisperModel

        self.model_name = model
        self.model = WhisperModel(model, device=device, compute_type=compute_type)

    def detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        """Hindi or English, whichever the model finds more likely."""
        _, _, probs = self.model.detect_language(to_float(audio))
        scores = {lang: p for lang, p in probs if lang in LANGUAGES}
        best = max(LANGUAGES, key=lambda lang: scores.get(lang, 0.0))
        total = sum(scores.get(lang, 0.0) for lang in LANGUAGES) or 1.0
        return best, scores.get(best, 0.0) / total

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> dict:
        audio = to_float(audio)
        if len(audio) < 1600:  # under 100 ms: nothing to read
            return {"text": "", "language": language, "language_confidence": 0.0}
        confidence = 1.0
        if language is None:
            language, confidence = self.detect_language(audio)
        segments, _ = self.model.transcribe(
            audio, language=language, beam_size=5, condition_on_previous_text=False,
            vad_filter=True, temperature=0.0,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"text": text, "language": language, "language_confidence": round(confidence, 3)}
