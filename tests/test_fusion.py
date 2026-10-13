"""
tests/test_fusion.py
--------------------
Unit tests for the fusion engine.

Every scenario from the specification is tested, plus edge cases for
audio unavailability, stale evidence, and CV-only fallback.

Uses the new intent categories: FATIGUE, LOSS_OF_FOCUS, STRESS,
FRUSTRATION, DISTRESS, URGENT_STOP, NORMAL, UNKNOWN.

No external dependencies – uses synthetic CVEvidence and AudioEvidence.
"""

from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.intent_classifier import AudioEvidence
from fusion.alertness_state import AlertnessState
from fusion.cv_adapter import CVEvidence
from fusion.fusion_engine import FusionConfig, FusionEngine


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _cv(
    drowsy: bool = False,
    distracted: bool = False,
    yawning: bool = False,
    score: float | None = None,
    alerts: list | None = None,
) -> CVEvidence:
    if score is None:
        score = 0.0
        if yawning:
            score = max(score, 0.50)
        if distracted:
            score = max(score, 0.40)
        if drowsy:
            score = max(score, 0.80)
    return CVEvidence(
        timestamp=time.time(),
        face_found=True,
        drowsiness_detected=drowsy,
        distraction_detected=distracted,
        yawning_detected=yawning,
        drowsiness_score=score,
        active_alerts=alerts or [],
    )


def _audio(
    intent: str = "NORMAL",
    risk: float = 0.0,
    confidence: float = 0.9,
    transcript: str = "",
    age: float = 0.0,
) -> AudioEvidence:
    return AudioEvidence(
        timestamp=time.time() - age,
        transcript=transcript,
        intent=intent,
        confidence=confidence,
        risk_score=risk,
    )


# --------------------------------------------------------------------------- #
# Main test
# --------------------------------------------------------------------------- #
def main():
    passed = failed = 0
    engine = FusionEngine(FusionConfig())

    def check(name: str, condition: bool, extra: str = ""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  PASS  {name} {extra}")
        else:
            failed += 1
            print(f"  FAIL  {name} {extra}")

    print("\nFusion Engine – unit tests")
    print("-" * 60)

    # ---- CV NORMAL + Audio NORMAL → NORMAL ----
    r = engine.fuse(
        _cv(),
        _audio(intent="NORMAL", risk=0.0),
    )
    check(
        "CV NORMAL + Audio NORMAL → NORMAL",
        r.state == AlertnessState.NORMAL,
        f"(got {r.state_name}, score={r.score})",
    )

    # ---- CV NORMAL + Audio FATIGUE → ATTENTION_DEGRADED ----
    r = engine.fuse(
        _cv(),
        _audio(intent="FATIGUE", risk=0.85, transcript="I'm tired"),
    )
    check(
        "CV NORMAL + Audio FATIGUE → ATTENTION_DEGRADED",
        r.state == AlertnessState.ATTENTION_DEGRADED,
        f"(got {r.state_name}, score={r.score})",
    )

    # ---- CV DROWSY + Audio NORMAL → DROWSY ----
    r = engine.fuse(
        _cv(drowsy=True),
        _audio(intent="NORMAL", risk=0.0),
    )
    check(
        "CV DROWSY + Audio NORMAL → DROWSY",
        r.state == AlertnessState.DROWSY,
        f"(got {r.state_name}, score={r.score})",
    )

    # ---- CV DROWSY + Audio FATIGUE → HIGH_RISK ----
    r = engine.fuse(
        _cv(drowsy=True),
        _audio(intent="FATIGUE", risk=0.85, transcript="I'm exhausted"),
    )
    check(
        "CV DROWSY + Audio FATIGUE → HIGH_RISK",
        r.state == AlertnessState.HIGH_RISK,
        f"(got {r.state_name}, score={r.score})",
    )

    # ---- CV DISTRACTED + Audio NORMAL → DISTRACTED ----
    r = engine.fuse(
        _cv(distracted=True),
        _audio(intent="NORMAL", risk=0.0),
    )
    check(
        "CV DISTRACTED + Audio NORMAL → DISTRACTED",
        r.state == AlertnessState.DISTRACTED,
        f"(got {r.state_name}, score={r.score})",
    )

    # ---- CV HIGH_RISK (alert active) + Audio FATIGUE → ALERT ----
    r = engine.fuse(
        _cv(drowsy=True, score=0.95, alerts=["DROWSINESS ALERT!"]),
        _audio(intent="FATIGUE", risk=0.85, transcript="I'm exhausted"),
    )
    check(
        "CV ALERT + Audio FATIGUE → ALERT",
        r.state == AlertnessState.ALERT,
        f"(got {r.state_name}, score={r.score})",
    )

    # ---- Audio unavailable + CV working → CV-only ----
    r = engine.fuse(_cv(drowsy=True), audio=None)
    check(
        "Audio unavailable + CV DROWSY → DROWSY",
        r.state == AlertnessState.DROWSY,
        f"(got {r.state_name})",
    )
    r = engine.fuse(_cv(), audio=None)
    check(
        "Audio unavailable + CV NORMAL → NORMAL",
        r.state == AlertnessState.NORMAL,
        f"(got {r.state_name})",
    )

    # ---- CV NORMAL + Audio risk → capped at ATTENTION_DEGRADED ----
    r = engine.fuse(
        _cv(score=0.0),
        _audio(intent="FATIGUE", risk=0.85),
    )
    check(
        "CV normal + Audio FATIGUE → capped at ATTENTION_DEGRADED",
        r.state <= AlertnessState.ATTENTION_DEGRADED,
        f"(got {r.state_name})",
    )

    # ---- Stale audio evidence → ignored ----
    r = engine.fuse(
        _cv(),
        _audio(intent="FATIGUE", risk=0.85, age=15.0),
    )
    check(
        "Stale audio (>TTL) ignored → NORMAL",
        r.state == AlertnessState.NORMAL,
        f"(got {r.state_name}, reason={r.reason})",
    )

    # ---- LOSS_OF_FOCUS + CV DROWSY → HIGH_RISK ----
    r = engine.fuse(
        _cv(drowsy=True),
        _audio(intent="LOSS_OF_FOCUS", risk=0.65, transcript="I can't focus"),
    )
    check(
        "CV DROWSY + Audio LOSS_OF_FOCUS → HIGH_RISK",
        r.state == AlertnessState.HIGH_RISK,
        f"(got {r.state_name})",
    )

    # ---- DISTRESS + CV NORMAL → ATTENTION_DEGRADED ----
    r = engine.fuse(
        _cv(),
        _audio(intent="DISTRESS", risk=0.75, transcript="I'm dizzy"),
    )
    check(
        "CV NORMAL + Audio DISTRESS → ATTENTION_DEGRADED",
        r.state == AlertnessState.ATTENTION_DEGRADED,
        f"(got {r.state_name})",
    )

    # ---- CV DISTRACTED + Audio FATIGUE → HIGH_RISK ----
    r = engine.fuse(
        _cv(distracted=True),
        _audio(intent="FATIGUE", risk=0.85),
    )
    check(
        "CV DISTRACTED + Audio FATIGUE → HIGH_RISK",
        r.state == AlertnessState.HIGH_RISK,
        f"(got {r.state_name})",
    )

    # ---- YAWNING only → ATTENTION_DEGRADED ----
    r = engine.fuse(
        _cv(yawning=True),
        _audio(intent="NORMAL", risk=0.0),
    )
    check(
        "CV YAWNING + Audio NORMAL → ATTENTION_DEGRADED",
        r.state == AlertnessState.ATTENTION_DEGRADED,
        f"(got {r.state_name})",
    )

    # ---- URGENT_STOP + CV NORMAL → ATTENTION_DEGRADED (audio alone can't ALERT) ----
    r = engine.fuse(
        _cv(),
        _audio(intent="URGENT_STOP", risk=1.0, transcript="stop the car"),
    )
    check(
        "CV NORMAL + Audio URGENT_STOP → ATTENTION_DEGRADED (capped)",
        r.state == AlertnessState.ATTENTION_DEGRADED,
        f"(got {r.state_name})",
    )

    # ---- URGENT_STOP + CV ALERT → ALERT ----
    r = engine.fuse(
        _cv(drowsy=True, score=0.95, alerts=["DROWSINESS ALERT!"]),
        _audio(intent="URGENT_STOP", risk=1.0),
    )
    check(
        "CV ALERT + Audio URGENT_STOP → ALERT",
        r.state == AlertnessState.ALERT,
        f"(got {r.state_name})",
    )

    # ---- FRUSTRATION + CV NORMAL → NORMAL (low risk, not in RISK_INTENTS... wait) ----
    # FRUSTRATION IS NOT in _RISK_INTENTS — it has risk 0.40 but is below thresholds
    # Actually, let me check: FRUSTRATION is not in _RISK_INTENTS, but its risk_score
    # would still contribute via the weighted score. With audio_weight=0.3 and risk=0.40,
    # combined = 0.3 * 0.40 = 0.12 which is < threshold_attention_degraded (0.20) → NORMAL
    r = engine.fuse(
        _cv(),
        _audio(intent="FRUSTRATION", risk=0.40),
    )
    check(
        "CV NORMAL + Audio FRUSTRATION → NORMAL (not a risk intent)",
        r.state == AlertnessState.NORMAL,
        f"(got {r.state_name}, score={r.score})",
    )

    # ---- AlertnessResult structure ----
    r = engine.fuse(
        _cv(drowsy=True, score=0.80),
        _audio(intent="FATIGUE", risk=0.85),
    )
    check("result has score", 0.0 <= r.score <= 1.0, f"({r.score})")
    check("result has state", isinstance(r.state, AlertnessState))
    check("result has reason", len(r.reason) > 0)
    check("result has cv_score", r.cv_score == 0.80)
    check("result has audio_score", r.audio_score == 0.85)
    check("result has state_name", r.state_name in {s.name for s in AlertnessState})

    print("-" * 60)
    print(f"  {passed} passed, {failed} failed\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
