"""
speech_to_text.py
-----------------
Local, offline speech-to-text using *faster-whisper*.

The transcriber loads a small Whisper model once on first call,
then exposes a simple ``transcribe(audio)`` method that returns the
transcript string and a confidence score.

The model runs entirely on the CPU by default, keeping the GPU free for
MediaPipe / OpenCV.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    """Output of a single transcription pass."""
    text: str                 # raw transcript string
    confidence: float         # average log-probability mapped to [0, 1]
    language: str             # detected language code (e.g. "en")
    duration_sec: float       # wall-clock time the transcription took


class WhisperTranscriber:
    """
    Wraps faster-whisper for single-shot audio buffer transcription.

    Parameters
    ----------
    model_size : model name understood by faster-whisper
                 ("tiny", "base", "small", etc.)
    device     : "cpu" or "cuda".
    compute_type : quantisation level ("int8", "float16", "float32").
    language   : if set, forces the Whisper language; if None, auto-detect.
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = "en",
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language

        self._model = None          # lazy init
        self._loading = False

    # ------------------------------------------------------------------ #
    # Lazy model loading
    # ------------------------------------------------------------------ #
    def _ensure_model(self) -> bool:
        """Load the model once.  Returns True on success."""
        if self._model is not None:
            return True
        if self._loading:
            return False                 # another thread is already loading

        self._loading = True
        try:
            from faster_whisper import WhisperModel  # deferred import

            logger.info(
                "Loading faster-whisper model '%s' on %s (%s) …",
                self.model_size, self.device, self.compute_type,
            )
            t0 = time.time()
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            logger.info("Model loaded in %.1f s", time.time() - t0)
            return True

        except ImportError:
            logger.error(
                "faster-whisper is not installed. "
                "Install with:  pip install faster-whisper"
            )
            return False
        except Exception:
            logger.exception("Failed to load Whisper model")
            return False
        finally:
            self._loading = False

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def transcribe(self, audio: np.ndarray) -> TranscriptionResult | None:
        """
        Transcribe a float32 mono audio buffer (16 kHz).

        Returns a ``TranscriptionResult`` or *None* if the model is
        not available or the audio is too short.
        """
        if audio is None or len(audio) < 1600:         # < 0.1 s
            return None

        if not self._ensure_model():
            return None

        t0 = time.time()
        try:
            segments, info = self._model.transcribe(
                audio,
                beam_size=1,             # fast, greedy decoding
                language=self.language,
                vad_filter=True,         # built-in Silero VAD inside faster-whisper
                vad_parameters=dict(min_silence_duration_ms=300),
            )

            texts = []
            total_prob = 0.0
            n_tokens = 0
            for seg in segments:
                texts.append(seg.text.strip())
                # avg_logprob is negative; map to (0, 1)
                prob = min(max(2.0 ** seg.avg_logprob, 0.0), 1.0)
                n_tokens += 1
                total_prob += prob

            transcript = " ".join(texts).strip()
            confidence = (total_prob / n_tokens) if n_tokens else 0.0

            return TranscriptionResult(
                text=transcript,
                confidence=round(confidence, 3),
                language=info.language if info else (self.language or "en"),
                duration_sec=round(time.time() - t0, 3),
            )

        except Exception:
            logger.exception("Transcription failed")
            return None

    # ------------------------------------------------------------------ #
    @property
    def is_ready(self) -> bool:
        return self._model is not None
