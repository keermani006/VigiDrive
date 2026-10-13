"""
vad.py
------
Simple energy-based Voice Activity Detection (VAD).

Classifies each audio chunk as speech / silence based on its RMS energy
relative to a configurable threshold.  This is intentionally lightweight:
a deterministic energy gate that prevents silence or background noise from
being forwarded to the (heavier) speech-to-text model.

No neural networks are used here.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


class EnergyVAD:
    """
    Stateless voice-activity detector.

    Parameters
    ----------
    energy_threshold : RMS energy threshold; chunks below this are silence.
    min_speech_chunks: number of consecutive speech-chunks before we declare
                       the utterance "real" (filters momentary bursts).
    """

    def __init__(
        self,
        energy_threshold: float = 0.015,
        min_speech_chunks: int = 2,
    ):
        self.energy_threshold = energy_threshold
        self.min_speech_chunks = min_speech_chunks
        self._consecutive_speech = 0

    # ------------------------------------------------------------------ #
    def is_speech(self, audio: np.ndarray) -> bool:
        """
        Return True if *audio* (float32 samples in [-1, 1]) is speech.

        Also maintains a small state for consecutive-speech filtering.
        """
        rms = float(np.sqrt(np.mean(audio ** 2)))

        if rms >= self.energy_threshold:
            self._consecutive_speech += 1
        else:
            self._consecutive_speech = 0

        return self._consecutive_speech >= self.min_speech_chunks

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """Clear the consecutive-speech counter."""
        self._consecutive_speech = 0

    @staticmethod
    def rms_energy(audio: np.ndarray) -> float:
        """Utility: compute RMS energy of an audio buffer."""
        return float(np.sqrt(np.mean(audio ** 2)))
