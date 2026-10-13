"""
tests/test_audio_intent.py
--------------------------
Unit tests for the TF-IDF + Logistic Regression intent classifier.

Tests every required intent category, confidence behaviour,
risk score mapping, and the AudioEvidence structure.

Requires the model to be trained first:
    venv312/bin/python3 audio/train_intent_model.py
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.intent_classifier import AudioEvidence, IntentClassifier


def main():
    passed = failed = 0
    clf = IntentClassifier()

    if not clf.is_ready:
        print("\n  ERROR: Model not trained yet!")
        print("  Run:  venv312/bin/python3 audio/train_intent_model.py\n")
        return 1

    def check(name: str, condition: bool, extra: str = ""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  PASS  {name} {extra}")
        else:
            failed += 1
            print(f"  FAIL  {name} {extra}")

    print("\nTF-IDF Intent Classifier – unit tests")
    print("-" * 60)

    # ---- FATIGUE ----
    for text in [
        "I'm feeling sleepy",
        "I'm so tired right now",
        "I can barely keep my eyes open",
        "I'm completely exhausted",
        "I'm struggling to stay awake",
        "I need to sleep really badly",
        "I'm drowsy and need to rest",
    ]:
        ev = clf.classify(text, stt_confidence=0.95)
        check(
            f"FATIGUE: \"{text}\"",
            ev.intent == "FATIGUE",
            f"(got {ev.intent}, risk={ev.risk_score}, conf={ev.confidence:.2f})",
        )

    # ---- LOSS_OF_FOCUS ----
    for text in [
        "I keep losing focus on the road",
        "my mind keeps wandering off",
        "I can't concentrate on driving",
        "I'm completely zoning out",
        "I almost missed that turn just now",
    ]:
        ev = clf.classify(text, stt_confidence=0.90)
        check(
            f"LOSS_OF_FOCUS: \"{text}\"",
            ev.intent == "LOSS_OF_FOCUS",
            f"(got {ev.intent}, risk={ev.risk_score}, conf={ev.confidence:.2f})",
        )

    # ---- STRESS ----
    for text in [
        "I'm feeling really stressed right now",
        "I feel so tense and anxious",
        "my heart is racing from the stress",
        "I'm so anxious I can barely breathe",
    ]:
        ev = clf.classify(text, stt_confidence=0.90)
        check(
            f"STRESS: \"{text}\"",
            ev.intent == "STRESS",
            f"(got {ev.intent}, risk={ev.risk_score}, conf={ev.confidence:.2f})",
        )

    # ---- FRUSTRATION ----
    for text in [
        "this traffic is driving me crazy",
        "I'm so frustrated with this drive",
        "another red light are you kidding me",
    ]:
        ev = clf.classify(text, stt_confidence=0.90)
        check(
            f"FRUSTRATION: \"{text}\"",
            ev.intent == "FRUSTRATION",
            f"(got {ev.intent}, risk={ev.risk_score}, conf={ev.confidence:.2f})",
        )

    # ---- DISTRESS ----
    for text in [
        "I'm feeling really dizzy",
        "my vision is getting blurry",
        "I think I'm going to throw up",
        "I feel like I might pass out",
    ]:
        ev = clf.classify(text, stt_confidence=0.85)
        check(
            f"DISTRESS: \"{text}\"",
            ev.intent == "DISTRESS",
            f"(got {ev.intent}, risk={ev.risk_score}, conf={ev.confidence:.2f})",
        )

    # ---- URGENT_STOP ----
    for text in [
        "stop the car right now",
        "pull over immediately",
        "this is an emergency stop now",
    ]:
        ev = clf.classify(text, stt_confidence=0.90)
        check(
            f"URGENT_STOP: \"{text}\"",
            ev.intent == "URGENT_STOP",
            f"(got {ev.intent}, risk={ev.risk_score}, conf={ev.confidence:.2f})",
        )

    # ---- NORMAL ----
    for text in [
        "call my brother",
        "play some music",
        "navigate to the airport",
        "what time is it",
        "hello there",
    ]:
        ev = clf.classify(text, stt_confidence=0.90)
        check(
            f"NORMAL: \"{text}\"",
            ev.intent == "NORMAL",
            f"(got {ev.intent}, risk={ev.risk_score}, conf={ev.confidence:.2f})",
        )
        check(
            f"  risk == 0.0 for \"{text}\"",
            ev.risk_score == 0.0,
            f"(got {ev.risk_score})",
        )

    # ---- UNKNOWN (empty input) ----
    ev = clf.classify("", stt_confidence=0.5)
    check("empty string → UNKNOWN", ev.intent == "UNKNOWN")
    check("empty string → risk 0.0", ev.risk_score == 0.0)

    # ---- Risk score ordering ----
    fat = clf.classify("I'm so tired", stt_confidence=1.0)
    dis = clf.classify("I'm feeling dizzy", stt_confidence=1.0)
    urg = clf.classify("stop the car right now", stt_confidence=1.0)
    check(
        "risk: URGENT_STOP ≥ FATIGUE ≥ DISTRESS",
        urg.risk_score >= fat.risk_score >= dis.risk_score,
        f"({urg.risk_score}, {fat.risk_score}, {dis.risk_score})",
    )

    # ---- Confidence combines classifier × STT confidence ----
    ev_high = clf.classify("I'm feeling sleepy", stt_confidence=1.0)
    ev_low = clf.classify("I'm feeling sleepy", stt_confidence=0.5)
    check(
        "higher STT conf → higher combined conf",
        ev_high.confidence >= ev_low.confidence,
        f"({ev_high.confidence:.3f} >= {ev_low.confidence:.3f})",
    )

    # ---- AudioEvidence structure ----
    ev = clf.classify("I need to pull over", stt_confidence=0.92)
    check("has timestamp", ev.timestamp > 0)
    check("has transcript", len(ev.transcript) > 0)
    check("has intent", isinstance(ev.intent, str) and len(ev.intent) > 0)
    check("has confidence", 0.0 <= ev.confidence <= 1.0)
    check("has risk_score", 0.0 <= ev.risk_score <= 1.0)

    # ---- Unseen / paraphrased phrases (generalisation) ----
    print("\n  -- Generalisation (unseen phrases) --")
    unseen = [
        ("I'm completely drained and wiped out", "FATIGUE"),
        ("my eyelids are getting so heavy", "FATIGUE"),
        ("I wasn't even watching the road just now", "LOSS_OF_FOCUS"),
        ("all this pressure is killing me", "STRESS"),
        ("these drivers are making me insane", "FRUSTRATION"),
        ("I think something is wrong with my heart", "DISTRESS"),
        ("we have to stop this car immediately", "URGENT_STOP"),
        ("let's grab some food at the next exit", "NORMAL"),
    ]
    for text, expected in unseen:
        ev = clf.classify(text, stt_confidence=0.90)
        check(
            f"unseen → {expected}: \"{text}\"",
            ev.intent == expected,
            f"(got {ev.intent}, conf={ev.confidence:.2f})",
        )

    print("-" * 60)
    print(f"  {passed} passed, {failed} failed\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
