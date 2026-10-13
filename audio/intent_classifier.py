"""
intent_classifier.py
--------------------
TF-IDF + Logistic Regression intent classifier for driver speech.

Replaces the previous regex-based classifier with a statistical ML model
that generalises to unseen phrasings.  The model is trained offline via
``train_intent_model.py`` and loaded at runtime from joblib files.

Interface is kept **modular**: the same ``classify()`` → ``AudioEvidence``
contract is maintained so the pipeline and fusion engine are decoupled
from the classifier implementation.  Swapping in a Transformer later
requires only replacing this file.

Intent Categories
-----------------
NORMAL          – everyday speech with no safety relevance.
FATIGUE         – tiredness, sleepiness, exhaustion.
LOSS_OF_FOCUS   – inability to concentrate, zoning out.
STRESS          – tension, anxiety, feeling overwhelmed.
FRUSTRATION     – irritation, anger at traffic / conditions.
DISTRESS        – medical symptoms: dizziness, pain, nausea.
URGENT_STOP     – explicit request to stop the vehicle immediately.
UNKNOWN         – low-confidence prediction or empty input.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(_SCRIPT_DIR, "models")
_VECTORIZER_PATH = os.path.join(_MODEL_DIR, "tfidf_vectorizer.joblib")
_CLASSIFIER_PATH = os.path.join(_MODEL_DIR, "intent_classifier.joblib")
_ENCODER_PATH = os.path.join(_MODEL_DIR, "label_encoder.joblib")


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #

@dataclass
class AudioEvidence:
    """Structured output of the voice subsystem for a single utterance."""
    timestamp: float               # time.time() when this evidence was produced
    transcript: str                # raw text from STT
    intent: str                    # one of the intent category names
    confidence: float              # classifier probability × STT confidence
    risk_score: float              # safety-relevant risk in [0, 1]


# --------------------------------------------------------------------------- #
# Default risk score mapping – configurable
# --------------------------------------------------------------------------- #
DEFAULT_RISK_SCORES: Dict[str, float] = {
    "NORMAL":         0.00,
    "FATIGUE":        0.85,
    "LOSS_OF_FOCUS":  0.65,
    "STRESS":         0.55,
    "FRUSTRATION":    0.40,
    "DISTRESS":       0.75,
    "URGENT_STOP":    1.00,
    "UNKNOWN":        0.00,
}

# Minimum classifier confidence to accept a prediction.
# Below this, the intent is forced to UNKNOWN.
DEFAULT_CONFIDENCE_THRESHOLD = 0.20


# --------------------------------------------------------------------------- #
# Classifier
# --------------------------------------------------------------------------- #

class IntentClassifier:
    """
    TF-IDF + Logistic Regression intent classifier.

    Loads the trained vectorizer, classifier, and label encoder from
    joblib files.  Falls back to an UNKNOWN-only mode if the model
    files are missing (e.g. first run before training).

    Parameters
    ----------
    model_dir            : directory containing the joblib artefacts.
    risk_scores          : dict mapping intent names to [0, 1] risk.
    confidence_threshold : minimum probability to accept a prediction.
    """

    def __init__(
        self,
        model_dir: str | None = None,
        risk_scores: Dict[str, float] | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ):
        self.risk_scores = dict(DEFAULT_RISK_SCORES)
        if risk_scores:
            self.risk_scores.update(risk_scores)
        self.confidence_threshold = confidence_threshold

        self._vectorizer = None
        self._classifier = None
        self._label_encoder = None
        self._ready = False

        model_dir = model_dir or _MODEL_DIR
        self._load_model(model_dir)

    # ------------------------------------------------------------------ #
    def _load_model(self, model_dir: str) -> None:
        """Load the TF-IDF vectorizer, classifier, and label encoder."""
        vec_path = os.path.join(model_dir, "tfidf_vectorizer.joblib")
        clf_path = os.path.join(model_dir, "intent_classifier.joblib")
        enc_path = os.path.join(model_dir, "label_encoder.joblib")

        if not all(os.path.exists(p) for p in [vec_path, clf_path, enc_path]):
            logger.warning(
                "Intent model files not found in %s. "
                "Run:  python audio/train_intent_model.py  "
                "to train the classifier. Falling back to UNKNOWN-only mode.",
                model_dir,
            )
            return

        try:
            import joblib
        except ImportError:
            from sklearn.externals import joblib  # type: ignore

        try:
            self._vectorizer = joblib.load(vec_path)
            self._classifier = joblib.load(clf_path)
            self._label_encoder = joblib.load(enc_path)
            self._ready = True
            logger.info(
                "Intent classifier loaded (%d classes: %s)",
                len(self._label_encoder.classes_),
                list(self._label_encoder.classes_),
            )
        except Exception:
            logger.exception("Failed to load intent model")

    # ------------------------------------------------------------------ #
    def classify(
        self,
        transcript: str,
        stt_confidence: float = 1.0,
    ) -> AudioEvidence:
        """
        Classify a transcript into an ``AudioEvidence`` object.

        Parameters
        ----------
        transcript      : raw text from the speech-to-text engine.
        stt_confidence  : confidence score reported by STT in [0, 1].
        """
        text = transcript.strip()
        now = time.time()

        # Empty or whitespace-only → UNKNOWN
        if not text:
            return AudioEvidence(
                timestamp=now,
                transcript="",
                intent="UNKNOWN",
                confidence=0.0,
                risk_score=0.0,
            )

        # Model not loaded → UNKNOWN
        if not self._ready:
            return AudioEvidence(
                timestamp=now,
                transcript=text,
                intent="UNKNOWN",
                confidence=0.0,
                risk_score=0.0,
            )

        # ---- TF-IDF + Logistic Regression inference ----
        X = self._vectorizer.transform([text.lower()])
        proba = self._classifier.predict_proba(X)[0]
        pred_idx = int(np.argmax(proba))
        classifier_conf = float(proba[pred_idx])

        intent = self._label_encoder.inverse_transform([pred_idx])[0]

        # If confidence is below threshold → UNKNOWN
        if classifier_conf < self.confidence_threshold:
            intent = "UNKNOWN"

        # Combined confidence = classifier probability × STT confidence
        combined_conf = round(classifier_conf * stt_confidence, 3)

        risk = self.risk_scores.get(intent, 0.0)

        return AudioEvidence(
            timestamp=now,
            transcript=text,
            intent=intent,
            confidence=combined_conf,
            risk_score=risk,
        )

    # ------------------------------------------------------------------ #
    @property
    def is_ready(self) -> bool:
        """True if the model is loaded and ready for inference."""
        return self._ready

    @property
    def classes(self) -> list[str]:
        """List of known intent class names."""
        if self._label_encoder is not None:
            return list(self._label_encoder.classes_)
        return list(DEFAULT_RISK_SCORES.keys())
