"""
utils.py
--------
Small helper utilities for the Driver Drowsiness & Distraction Detection System:

  * landmark helpers   -> convert MediaPipe normalised landmarks to pixel points
  * geometry helpers   -> euclidean distance, EAR / MAR ratio math
  * drawing helpers    -> status panel + alert banners drawn on the video frame
  * AlarmPlayer        -> non-blocking audio alert with graceful fallbacks
  * EventLogger        -> timestamped CSV log of every detected event
"""

from __future__ import annotations

import csv
import os
import platform
import subprocess
import threading
import time
from datetime import datetime

import cv2
import numpy as np

# --------------------------------------------------------------------------- #
# Colours (BGR, because OpenCV)
# --------------------------------------------------------------------------- #
GREEN = (0, 200, 0)
RED = (0, 0, 255)
ORANGE = (0, 140, 255)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREY = (160, 160, 160)


# --------------------------------------------------------------------------- #
# Landmark / geometry helpers
# --------------------------------------------------------------------------- #
def landmarks_to_points(landmarks, width: int, height: int) -> np.ndarray:
    """Convert MediaPipe's normalised landmarks (0..1) into an (N, 2) pixel array."""
    return np.array(
        [(lm.x * width, lm.y * height) for lm in landmarks],
        dtype=np.float64,
    )


def euclidean(p1: np.ndarray, p2: np.ndarray) -> float:
    """Distance between two 2D points."""
    return float(np.linalg.norm(np.asarray(p1) - np.asarray(p2)))


def aspect_ratio(points: np.ndarray, indices) -> float:
    """
    Generic 6-point aspect ratio used for both EAR and MAR.

    indices order = (p1, p2, p3, p4, p5, p6) going around the shape, where
    p1 and p4 are the horizontal (left/right) corners.

        ratio = ( |p2-p6| + |p3-p5| ) / ( 2 * |p1-p4| )
    """
    p1, p2, p3, p4, p5, p6 = (points[i] for i in indices)
    vertical = euclidean(p2, p6) + euclidean(p3, p5)
    horizontal = euclidean(p1, p4)
    if horizontal < 1e-6:                      # guard against divide-by-zero
        return 0.0
    return vertical / (2.0 * horizontal)


# --------------------------------------------------------------------------- #
# Drawing helpers
# --------------------------------------------------------------------------- #
def draw_points(frame, points: np.ndarray, indices, color=GREEN, radius=1):
    """Draw a few landmark points (used to visualise eyes / mouth / pose points)."""
    for i in indices:
        x, y = points[i]
        cv2.circle(frame, (int(x), int(y)), radius, color, -1)


def draw_status_panel(frame, lines, origin=(10, 10), width=250):
    """Semi-transparent panel in the top-left corner holding the live metrics."""
    x, y = origin
    line_h = 22
    height = line_h * len(lines) + 14

    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + width, y + height), BLACK, -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    for i, (text, color) in enumerate(lines):
        cv2.putText(
            frame,
            text,
            (x + 10, y + 22 + i * line_h),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            1,
            cv2.LINE_AA,
        )


def draw_alerts(frame, alerts):
    """Big red banners, stacked, for whatever alerts are currently active."""
    if not alerts:
        return
    h, w = frame.shape[:2]

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), RED, 8)          # red border
    cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)

    for i, text in enumerate(alerts):
        y = int(h * 0.38) + i * 55          # below the status panel, never overlapping
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.1, 3)
        x = max((w - tw) // 2, 10)
        cv2.rectangle(frame, (x - 12, y - th - 12), (x + tw + 12, y + 12), BLACK, -1)
        cv2.putText(
            frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 1.1, RED, 3, cv2.LINE_AA
        )


def draw_no_face(frame):
    h, w = frame.shape[:2]
    cv2.putText(
        frame,
        "NO FACE DETECTED",
        (int(w * 0.28), h - 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        ORANGE,
        2,
        cv2.LINE_AA,
    )


# --------------------------------------------------------------------------- #
# Alarm
# --------------------------------------------------------------------------- #
class AlarmPlayer:
    """
    Plays an alert sound without blocking the video loop.

    Tries, in order: winsound (Windows) -> playsound -> aplay/afplay ->
    terminal bell. Never raises: audio must never crash the detector.
    """

    def __init__(self, sound_path: str | None = None, cooldown: float = 2.0,
                 enabled: bool = True):
        self.sound_path = sound_path if sound_path and os.path.exists(sound_path) else None
        self.cooldown = cooldown
        self.enabled = enabled
        self._last_played = 0.0
        self._lock = threading.Lock()

    def play(self):
        if not self.enabled:
            return
        now = time.time()
        with self._lock:
            if now - self._last_played < self.cooldown:
                return
            self._last_played = now
        threading.Thread(target=self._play_blocking, daemon=True).start()

    def _play_blocking(self):
        try:
            if platform.system() == "Windows":
                import winsound
                if self.sound_path:
                    winsound.PlaySound(self.sound_path, winsound.SND_FILENAME)
                else:
                    winsound.Beep(1000, 600)
                return

            if self.sound_path:
                try:
                    from playsound import playsound  # optional dependency
                    playsound(self.sound_path)
                    return
                except Exception:
                    pass

                player = "afplay" if platform.system() == "Darwin" else "aplay"
                try:
                    subprocess.run(
                        [player, self.sound_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True,
                    )
                    return
                except Exception:
                    pass

            print("\a", end="", flush=True)      # last-resort terminal bell
        except Exception:
            pass                                  # audio is never fatal


# --------------------------------------------------------------------------- #
# CSV event logging
# --------------------------------------------------------------------------- #
class EventLogger:
    """Appends one row per detected event: wall-clock time, video time, type, detail."""

    HEADER = ["timestamp", "video_time_sec", "frame", "event", "details"]

    def __init__(self, path: str | None):
        self.path = path
        self.count = 0
        self._file = None
        self._writer = None
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            self._file = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file)
            self._writer.writerow(self.HEADER)

    def log(self, event: str, frame_idx: int, video_time: float, details: str = ""):
        self.count += 1
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            f"{video_time:.2f}",
            frame_idx,
            event,
            details,
        ]
        print(f"[EVENT] {row[0]}  t={row[1]}s  frame={frame_idx}  {event}  {details}")
        if self._writer:
            self._writer.writerow(row)
            self._file.flush()

    def close(self):
        if self._file:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
