"""
microphone.py
-------------
Continuous microphone capture running in a dedicated daemon thread.

Reads raw PCM audio in small chunks and feeds them through a callback.
Designed to never block the CV main loop.  If the audio device is
unavailable or disconnects, the thread logs the failure and exits
gracefully—the rest of the system continues on CV evidence alone.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults – match faster-whisper expectations
# ---------------------------------------------------------------------------
DEFAULT_SAMPLE_RATE = 16_000      # 16 kHz mono (Whisper native)
DEFAULT_CHUNK_DURATION = 0.5      # seconds per chunk
DEFAULT_CHANNELS = 1


class MicrophoneStream:
    """
    Non-blocking microphone capture.

    Parameters
    ----------
    sample_rate   : sampling rate in Hz (default 16 000).
    chunk_duration: seconds of audio per buffer push.
    device_index  : PortAudio device index, or None for the default mic.
    on_audio      : callable(np.ndarray) invoked on each chunk from the
                    capture thread. If None, chunks are placed in
                    ``self.audio_queue`` instead.
    """

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        chunk_duration: float = DEFAULT_CHUNK_DURATION,
        device_index: int | None = None,
        on_audio: Callable[[np.ndarray], None] | None = None,
    ):
        self.sample_rate = sample_rate
        self.chunk_samples = int(sample_rate * chunk_duration)
        self.device_index = device_index
        self._on_audio = on_audio

        # Public queue – consumers can pull from here if no callback was set.
        self.audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)

        self._running = False
        self._thread: threading.Thread | None = None
        self._stream = None               # PyAudio stream handle
        self._pa = None                    # PyAudio instance

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Open the microphone and begin capturing in the background."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the capture loop to stop and wait for it to finish."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _capture_loop(self) -> None:
        try:
            import pyaudio  # deferred import – optional dependency
        except ImportError:
            logger.error(
                "pyaudio is not installed.  Voice subsystem disabled.  "
                "Install with:  pip install pyaudio"
            )
            self._running = False
            return

        try:
            self._pa = pyaudio.PyAudio()
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=DEFAULT_CHANNELS,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk_samples,
            )
            logger.info(
                "Microphone opened  (rate=%d, chunk=%d samples)",
                self.sample_rate,
                self.chunk_samples,
            )

            while self._running:
                try:
                    raw = self._stream.read(
                        self.chunk_samples, exception_on_overflow=False
                    )
                except OSError as exc:
                    logger.warning("Mic read error (device disconnected?): %s", exc)
                    break

                # Convert raw int16 bytes → float32 in [-1, 1]
                samples = (
                    np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                )

                if self._on_audio is not None:
                    try:
                        self._on_audio(samples)
                    except Exception:
                        logger.exception("on_audio callback error")
                else:
                    try:
                        self.audio_queue.put_nowait(samples)
                    except queue.Full:
                        pass  # drop oldest silently

        except Exception:
            logger.exception("Microphone capture failed to start")
        finally:
            self._cleanup()
            self._running = False

    def _cleanup(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    # ------------------------------------------------------------------ #
    @property
    def is_running(self) -> bool:
        return self._running

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
