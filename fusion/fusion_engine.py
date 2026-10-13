"""
fusion_engine.py
----------------
Deterministic, rule-based evidence fusion engine.

Combines:
    CVEvidence   (from the existing detector, via ``CVAdapter``)
    AudioEvidence (from the voice subsystem)

into:
    AlertnessResult (final fused state)

Design constraints
------------------
1. Deterministic and explainable – every output carries a ``reason`` string.
2. Audio never triggers the highest alert by itself.
3. Audio evidence has temporal confirmation: it is only counted if its
   timestamp is within ``audio_evidence_ttl`` seconds of the fusion call.
4. A single noisy transcription does NOT immediately escalate to ALERT.

Fusion Rules (configurable)
---------------------------
    CV NORMAL   + Audio NORMAL              → NORMAL
    CV NORMAL   + Audio DROWSINESS/FATIGUE  → ATTENTION_DEGRADED
    CV DROWSY   + Audio NORMAL              → DROWSY
    CV DROWSY   + Audio DROWSINESS/FATIGUE  → HIGH_RISK
    CV DISTRACTED + Audio NORMAL            → DISTRACTED
    CV DISTRACTED + Audio DROWSINESS        → HIGH_RISK
    CV HIGH_RISK + Audio DROWSINESS         → ALERT
    Audio alone (CV normal)                 → capped at ATTENTION_DEGRADED
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from audio.intent_classifier import AudioEvidence
from fusion.alertness_state import AlertnessResult, AlertnessState
from fusion.cv_adapter import CVEvidence

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass
class FusionConfig:
    """Tunable parameters for the fusion engine."""

    # How long (seconds) a piece of audio evidence stays valid.
    audio_evidence_ttl: float = 10.0

    # Weight given to audio evidence when computing the fused score.
    # Must be in (0, 1).  The CV weight is (1 - audio_weight).
    audio_weight: float = 0.30

    # Minimum combined score to reach each state.
    threshold_attention_degraded: float = 0.20
    threshold_drowsy: float = 0.45
    threshold_distracted: float = 0.35
    threshold_high_risk: float = 0.70
    threshold_alert: float = 0.90


# --------------------------------------------------------------------------- #
# Intent sets (for rule matching)
# --------------------------------------------------------------------------- #
_RISK_INTENTS = frozenset({
    "FATIGUE",
    "LOSS_OF_FOCUS",
    "STRESS",
    "DISTRESS",
    "URGENT_STOP",
})


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class FusionEngine:
    """
    Stateless (per-call) fusion of CV and audio evidence.

    Call ``fuse()`` once per CV frame cycle.
    """

    def __init__(self, config: FusionConfig | None = None):
        self.cfg = config or FusionConfig()

    # ------------------------------------------------------------------ #
    def fuse(
        self,
        cv: CVEvidence,
        audio: Optional[AudioEvidence] = None,
    ) -> AlertnessResult:
        """
        Produce a single ``AlertnessResult`` from the latest evidence.

        Parameters
        ----------
        cv    : current CV evidence snapshot (always required).
        audio : latest audio evidence, or None if unavailable / stale.
        """
        cfg = self.cfg
        now = time.time()

        # ---- Audio validity check (temporal confirmation) ----
        audio_valid = False
        audio_score = 0.0
        audio_intent = "NONE"

        if audio is not None:
            age = now - audio.timestamp
            if age <= cfg.audio_evidence_ttl:
                audio_valid = True
                audio_score = audio.risk_score
                audio_intent = audio.intent

        cv_score = cv.drowsiness_score

        # ---- Weighted score ----
        if audio_valid and audio_score > 0:
            combined = (
                (1.0 - cfg.audio_weight) * cv_score
                + cfg.audio_weight * audio_score
            )
        else:
            combined = cv_score

        combined = round(min(max(combined, 0.0), 1.0), 3)

        # ---- Rule-based state determination ----
        state, reason = self._apply_rules(cv, audio_intent, audio_valid,
                                          cv_score, audio_score, combined)

        return AlertnessResult(
            score=combined,
            state=state,
            reason=reason,
            cv_score=cv_score,
            audio_score=audio_score if audio_valid else 0.0,
            active_alerts=list(cv.active_alerts),
        )

    # ------------------------------------------------------------------ #
    def _apply_rules(
        self,
        cv: CVEvidence,
        audio_intent: str,
        audio_valid: bool,
        cv_score: float,
        audio_score: float,
        combined: float,
    ) -> tuple[AlertnessState, str]:
        """
        Deterministic rule table.  Returns (state, reason).

        The rules are evaluated top-to-bottom; the first match wins.
        """
        cfg = self.cfg
        audio_risky = audio_valid and audio_intent in _RISK_INTENTS

        # --- ALERT: CV already at explicit alert level + risky audio ---
        # Requires an actual alert string in the CV output (e.g. "DROWSINESS ALERT!")
        # A high normalised score alone is not enough — this prevents CV DROWSY +
        # audio risky from jumping straight past HIGH_RISK.
        cv_has_alert = any("ALERT" in a.upper() for a in cv.active_alerts)
        if cv_has_alert and audio_risky:
            return (
                AlertnessState.ALERT,
                f"CV alert active + {audio_intent} voice statement",
            )

        # --- HIGH_RISK: CV drowsy/distracted + risky audio ---
        if cv.drowsiness_detected and audio_risky:
            return (
                AlertnessState.HIGH_RISK,
                f"CV drowsiness + {audio_intent} voice statement",
            )

        if cv.distraction_detected and audio_risky:
            return (
                AlertnessState.HIGH_RISK,
                f"CV distraction + {audio_intent} voice statement",
            )

        # --- CV-only states ---
        if cv.drowsiness_detected:
            return (
                AlertnessState.DROWSY,
                f"CV drowsiness detected (score={cv_score:.2f})",
            )

        if cv.distraction_detected:
            return (
                AlertnessState.DISTRACTED,
                f"CV distraction detected (score={cv_score:.2f})",
            )

        # --- ATTENTION_DEGRADED: CV normal but audio is risky ---
        if audio_risky:
            return (
                AlertnessState.ATTENTION_DEGRADED,
                f"Driver voice indicates {audio_intent} (audio_risk={audio_score:.2f})",
            )

        # --- Yawning without full drowsiness ---
        if cv.yawning_detected:
            return (
                AlertnessState.ATTENTION_DEGRADED,
                f"Yawning detected (score={cv_score:.2f})",
            )

        # --- Fallback: threshold-based from combined score ---
        if combined >= cfg.threshold_alert:
            return AlertnessState.ALERT, f"Combined score {combined:.2f} ≥ alert"
        if combined >= cfg.threshold_high_risk:
            return AlertnessState.HIGH_RISK, f"Combined score {combined:.2f} ≥ high-risk"
        if combined >= cfg.threshold_drowsy:
            return AlertnessState.DROWSY, f"Combined score {combined:.2f} ≥ drowsy"
        if combined >= cfg.threshold_distracted:
            return AlertnessState.DISTRACTED, f"Combined score {combined:.2f} ≥ distracted"
        if combined >= cfg.threshold_attention_degraded:
            return (
                AlertnessState.ATTENTION_DEGRADED,
                f"Combined score {combined:.2f} ≥ attention-degraded",
            )

        return AlertnessState.NORMAL, "All indicators normal"
