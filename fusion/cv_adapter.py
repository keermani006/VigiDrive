"""
cv_adapter.py
-------------
Thin, read-only adapter that extracts structured ``CVEvidence`` from the
existing detector's per-frame output (``FrameResult``) and live state
(``DrowsinessDetector``) **without modifying either class**.

The adapter never writes back to the detector.  It treats the existing CV
system as a *black-box sensor*.

The ``cv_score`` is a simple normalised number derived from which alerts
are currently active.  The mapping is fully configurable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List


# --------------------------------------------------------------------------- #
# Default score mappings – configurable at construction time
# --------------------------------------------------------------------------- #
DEFAULT_STATE_SCORES: Dict[str, float] = {
    "NORMAL":       0.00,
    "DISTRACTED":   0.40,
    "YAWNING":      0.50,
    "DROWSY":       0.80,
    "ALERT":        1.00,
}


# --------------------------------------------------------------------------- #
# Data structure
# --------------------------------------------------------------------------- #
@dataclass
class CVEvidence:
    """Structured snapshot of the CV detector's current output."""
    timestamp: float                    # time.time()
    face_found: bool = False
    drowsiness_detected: bool = False
    distraction_detected: bool = False
    yawning_detected: bool = False
    drowsiness_score: float = 0.0       # normalised [0, 1]
    active_alerts: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #
class CVAdapter:
    """
    Extracts ``CVEvidence`` from the existing detector without changing it.

    Parameters
    ----------
    state_scores : dict mapping state names to normalised scores.
                   Falls back to ``DEFAULT_STATE_SCORES`` for any missing key.
    """

    def __init__(self, state_scores: Dict[str, float] | None = None):
        self.state_scores = dict(DEFAULT_STATE_SCORES)
        if state_scores:
            self.state_scores.update(state_scores)

    # ------------------------------------------------------------------ #
    def extract(self, detector, frame_result) -> CVEvidence:
        """
        Build a ``CVEvidence`` from the detector's live state and the
        most recent ``FrameResult``.

        Parameters
        ----------
        detector     : ``DrowsinessDetector`` instance (read-only access).
        frame_result : ``FrameResult`` returned by ``detector.process_frame()``.
        """
        ev = CVEvidence(timestamp=time.time())
        ev.face_found = frame_result.face_found
        ev.active_alerts = list(frame_result.alerts)

        # Map boolean states from the detector's latched flags
        ev.drowsiness_detected = detector.drowsy_active
        ev.distraction_detected = detector.distracted_active
        ev.yawning_detected = detector.yawn_active

        # Derive a single normalised score from whatever is active.
        # Use the *highest* applicable score.
        score = self.state_scores.get("NORMAL", 0.0)

        if ev.yawning_detected:
            score = max(score, self.state_scores.get("YAWNING", 0.5))
        if ev.distraction_detected:
            score = max(score, self.state_scores.get("DISTRACTED", 0.4))
        if ev.drowsiness_detected:
            score = max(score, self.state_scores.get("DROWSY", 0.8))

        # If any alert string contains "ALERT" escalate further
        if any("ALERT" in a.upper() for a in ev.active_alerts):
            score = max(score, self.state_scores.get("ALERT", 1.0))

        ev.drowsiness_score = round(score, 3)
        return ev
