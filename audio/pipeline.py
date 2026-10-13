"""
audio/pipeline.py
-----------------
End-to-end asynchronous audio pipeline.

Architecture
    Microphone  →  VAD  →  Buffer  →  Whisper STT  →  Intent Classifier
                                                             ↓
                                                     AudioEvidence (queue)

Runs entirely in background threads.  The CV main loop pulls the latest
``AudioEvidence`` from ``self.latest_evidence`` (thread-safe) whenever it
needs to feed the fusion engine.

Key design choices for responsiveness
    • Small chunks (0.2 s) for fast VAD reaction.
    • Pre-roll buffer so the first syllables of speech are never lost.
    • Transcription runs in its own thread so capture is never blocked.
    • Whisper "tiny" model by default – fast enough for short phrases.

Resilience guarantees
    • If pyaudio / microphone are unavailable → pipeline logs the error and
      ``latest_evidence`` stays None; the fusion engine runs on CV alone.
    • If faster-whisper is not installed → same graceful fallback.
    • Whisper model loading is lazy; the camera loop is never blocked.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Optional

import numpy as np

from audio.intent_classifier import AudioEvidence, IntentClassifier
from audio.microphone import MicrophoneStream
from audio.speech_to_text import WhisperTranscriber
from audio.vad import EnergyVAD

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
DEFAULT_CHUNK_DURATION = 0.2      # seconds – small for fast VAD reaction
DEFAULT_UTTERANCE_TIMEOUT = 1.5   # seconds of silence to end an utterance
DEFAULT_MAX_UTTERANCE = 8.0       # hard cap on utterance length (seconds)
PRE_ROLL_CHUNKS = 5               # keep last N non-speech chunks (~1 s)
                                  # to capture the onset of speech


class AudioPipeline:
    """
    Self-contained audio subsystem.

    Start with ``start()``; read the latest evidence from
    ``self.latest_evidence`` at any time (or None if nothing yet).
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16_000,
        chunk_duration: float = DEFAULT_CHUNK_DURATION,
        device_index: int | None = None,
        whisper_model: str = "tiny",
        whisper_device: str = "cpu",
        whisper_compute_type: str = "int8",
        whisper_language: str | None = "en",
        vad_threshold: float = 0.008,
        utterance_timeout: float = DEFAULT_UTTERANCE_TIMEOUT,
        max_utterance: float = DEFAULT_MAX_UTTERANCE,
    ):
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration

        self._mic = MicrophoneStream(
            sample_rate=sample_rate,
            chunk_duration=chunk_duration,
            device_index=device_index,
        )
        self._vad = EnergyVAD(
            energy_threshold=vad_threshold,
            min_speech_chunks=2,        # 2 × 0.2 s = 0.4 s confirmation
        )
        self._stt = WhisperTranscriber(
            model_size=whisper_model,
            device=whisper_device,
            compute_type=whisper_compute_type,
            language=whisper_language,
        )
        self._classifier = IntentClassifier()

        self._utterance_timeout = utterance_timeout
        self._max_utterance = max_utterance

        # Thread-safe latest evidence for the fusion engine to read.
        self._evidence_lock = threading.Lock()
        self._latest_evidence: Optional[AudioEvidence] = None

        # Transcription runs in its own thread so capture never blocks.
        self._transcription_lock = threading.Lock()

        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def latest_evidence(self) -> Optional[AudioEvidence]:
        with self._evidence_lock:
            return self._latest_evidence

    def start(self) -> None:
        """Begin capturing and processing audio in the background."""
        if self._running:
            return
        self._running = True
        self._mic.start()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        logger.info("Audio pipeline started")

    def stop(self) -> None:
        """Cleanly shut down."""
        self._running = False
        self._mic.stop()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Audio pipeline stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ #
    # Internal processing loop
    # ------------------------------------------------------------------ #
    def _process_loop(self) -> None:
        """
        Pulls chunks from the mic queue, runs VAD, accumulates speech
        into utterance buffers, and dispatches transcription.

        Key improvements over the naive approach:
          • A **pre-roll ring buffer** keeps the last N non-speech chunks
            so the onset of speech (before VAD confirms) is not lost.
          • Transcription is dispatched to a separate thread so this loop
            keeps pulling audio without pause.
        """
        # Pre-roll ring buffer for speech onset capture
        pre_roll: collections.deque[np.ndarray] = collections.deque(
            maxlen=PRE_ROLL_CHUNKS
        )
        utterance_chunks: list[np.ndarray] = []
        last_speech_time = 0.0
        utterance_start = 0.0
        in_utterance = False

        while self._running:
            try:
                chunk = self._mic.audio_queue.get(timeout=0.15)
            except Exception:
                # Timeout or queue empty – check if an in-progress
                # utterance should be flushed due to silence.
                if in_utterance and utterance_chunks:
                    silence = time.time() - last_speech_time
                    duration = time.time() - utterance_start
                    if silence >= self._utterance_timeout or duration >= self._max_utterance:
                        self._dispatch_transcription(utterance_chunks)
                        utterance_chunks = []
                        in_utterance = False
                        pre_roll.clear()
                        self._vad.reset()
                continue

            is_speech = self._vad.is_speech(chunk)

            if is_speech:
                if not in_utterance:
                    # Speech just started – prepend the pre-roll buffer
                    # so we capture the first syllables.
                    in_utterance = True
                    utterance_start = time.time()
                    utterance_chunks = list(pre_roll)
                    pre_roll.clear()
                    logger.debug("Speech started (pre-roll: %d chunks)", len(utterance_chunks))

                utterance_chunks.append(chunk)
                last_speech_time = time.time()

            else:
                if in_utterance:
                    # Still in an utterance but this chunk is silence.
                    # Append it (captures natural pauses within speech).
                    utterance_chunks.append(chunk)

                    silence = time.time() - last_speech_time
                    duration = time.time() - utterance_start

                    if silence >= self._utterance_timeout or duration >= self._max_utterance:
                        # Utterance complete → dispatch transcription
                        self._dispatch_transcription(utterance_chunks)
                        utterance_chunks = []
                        in_utterance = False
                        pre_roll.clear()
                        self._vad.reset()
                else:
                    # Not in utterance – push to pre-roll ring buffer
                    pre_roll.append(chunk)

        # Flush any remaining utterance on shutdown
        if utterance_chunks:
            self._dispatch_transcription(utterance_chunks)

    # ------------------------------------------------------------------ #
    def _dispatch_transcription(self, chunks: list[np.ndarray]) -> None:
        """
        Send chunks to Whisper in a separate thread so the capture loop
        is never blocked.
        """
        audio = np.concatenate(chunks)
        duration = len(audio) / self.sample_rate
        logger.info(
            "Utterance captured: %.1f s (%d samples) – sending to Whisper",
            duration, len(audio),
        )

        # Fire-and-forget transcription thread.  Only one transcription
        # runs at a time (the lock prevents overlap).
        threading.Thread(
            target=self._transcribe_and_classify,
            args=(audio,),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------ #
    def _transcribe_and_classify(self, audio: np.ndarray) -> None:
        """Run STT + intent classification and publish evidence."""
        # Prevent overlapping transcriptions (drop if one is in progress).
        if not self._transcription_lock.acquire(blocking=False):
            logger.debug("Transcription already in progress – skipping")
            return

        try:
            t0 = time.time()
            result = self._stt.transcribe(audio)
            if result is None or not result.text.strip():
                logger.debug("Empty transcription (%.1f s)", time.time() - t0)
                return

            evidence = self._classifier.classify(
                transcript=result.text,
                stt_confidence=result.confidence,
            )

            with self._evidence_lock:
                self._latest_evidence = evidence

            logger.info(
                "Voice [%.1fs]: \"%s\" -> %s (risk=%.2f, conf=%.2f)",
                time.time() - t0,
                evidence.transcript,
                evidence.intent,
                evidence.risk_score,
                evidence.confidence,
            )
        except Exception:
            logger.exception("Transcription/classification failed")
        finally:
            self._transcription_lock.release()

    # ------------------------------------------------------------------ #
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
