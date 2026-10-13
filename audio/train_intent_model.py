"""
train_intent_model.py
---------------------
Trains a TF-IDF + Logistic Regression intent classifier and saves
the vectorizer + model to disk using joblib.

Usage:
    venv312/bin/python3 audio/train_intent_model.py

Outputs:
    audio/models/tfidf_vectorizer.joblib
    audio/models/intent_classifier.joblib
    audio/models/label_encoder.joblib
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import cross_val_score, StratifiedKFold

try:
    import joblib
except ImportError:
    from sklearn.externals import joblib  # type: ignore

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(SCRIPT_DIR, "intent_data.json")
MODEL_DIR = os.path.join(SCRIPT_DIR, "models")


def load_dataset(path: str):
    """Load intent_data.json → (texts, labels)."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    texts = []
    labels = []
    for intent, samples in data.items():
        for text in samples:
            texts.append(text.strip().lower())
            labels.append(intent)

    return texts, labels


def train():
    print("\n" + "=" * 56)
    print(" TF-IDF + Logistic Regression — Intent Classifier")
    print("=" * 56)

    # ---- Load data ----
    texts, labels = load_dataset(DATA_PATH)
    print(f"\n  Dataset: {len(texts)} samples, {len(set(labels))} classes")
    for intent in sorted(set(labels)):
        count = labels.count(intent)
        print(f"    {intent:20s}  {count} samples")

    # ---- Encode labels ----
    le = LabelEncoder()
    y = le.fit_transform(labels)
    print(f"\n  Classes: {list(le.classes_)}")

    # ---- TF-IDF vectorisation ----
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        sublinear_tf=True,
        min_df=1,
        max_features=5000,
        strip_accents="unicode",
        lowercase=True,
    )
    X = vectorizer.fit_transform(texts)
    print(f"  Vocabulary size: {len(vectorizer.vocabulary_)}")
    print(f"  Feature matrix: {X.shape}")

    # ---- Train classifier ----
    clf = LogisticRegression(
        max_iter=1000,
        class_weight="balanced",
        solver="lbfgs",
        C=1.0,
    )
    clf.fit(X, y)
    print(f"\n  Training accuracy: {clf.score(X, y):.4f}")

    # ---- Cross-validation ----
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(clf, X, y, cv=cv, scoring="accuracy")
    print(f"  5-fold CV accuracy: {scores.mean():.4f} ± {scores.std():.4f}")

    # ---- Save model artefacts ----
    os.makedirs(MODEL_DIR, exist_ok=True)

    vectorizer_path = os.path.join(MODEL_DIR, "tfidf_vectorizer.joblib")
    classifier_path = os.path.join(MODEL_DIR, "intent_classifier.joblib")
    encoder_path = os.path.join(MODEL_DIR, "label_encoder.joblib")

    joblib.dump(vectorizer, vectorizer_path)
    joblib.dump(clf, classifier_path)
    joblib.dump(le, encoder_path)

    print(f"\n  Saved:")
    print(f"    {vectorizer_path}")
    print(f"    {classifier_path}")
    print(f"    {encoder_path}")

    # ---- Quick sanity check ----
    print("\n  Sanity check (inference on training data):")
    test_phrases = [
        "I'm feeling sleepy",
        "call my brother",
        "I'm completely exhausted",
        "stop the car right now",
        "this traffic is driving me crazy",
        "I can't concentrate on driving",
        "I'm feeling dizzy",
        "I'm stressed about the meeting",
    ]
    X_test = vectorizer.transform([t.lower() for t in test_phrases])
    preds = clf.predict(X_test)
    probs = clf.predict_proba(X_test)

    for phrase, pred_idx, prob_row in zip(test_phrases, preds, probs):
        intent = le.inverse_transform([pred_idx])[0]
        conf = prob_row[pred_idx]
        print(f"    \"{phrase}\"")
        print(f"      → {intent} (conf={conf:.3f})")

    print("\n" + "=" * 56)
    print(" TRAINING COMPLETE")
    print("=" * 56 + "\n")


if __name__ == "__main__":
    train()
