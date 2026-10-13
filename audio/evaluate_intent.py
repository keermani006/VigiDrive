"""
evaluate_intent.py
------------------
Evaluate the TF-IDF + Logistic Regression intent classifier.

Produces:
    - Overall accuracy, precision, recall, F1
    - Per-class performance table
    - Confusion matrix
    - Unseen / paraphrased phrase test

Usage:
    venv312/bin/python3 audio/evaluate_intent.py
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split

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


# --------------------------------------------------------------------------- #
# Unseen / paraphrased test phrases
# --------------------------------------------------------------------------- #
UNSEEN_PHRASES = [
    # FATIGUE – paraphrased, not in training data
    ("I'm completely drained", "FATIGUE"),
    ("my body just wants to shut down", "FATIGUE"),
    ("I can barely keep going I'm so wiped", "FATIGUE"),
    ("I desperately need some sleep", "FATIGUE"),
    ("I've never been this exhausted before", "FATIGUE"),

    # LOSS_OF_FOCUS – paraphrased
    ("my attention span is zero right now", "LOSS_OF_FOCUS"),
    ("I just realized I wasn't watching the road", "LOSS_OF_FOCUS"),
    ("I keep daydreaming instead of driving", "LOSS_OF_FOCUS"),
    ("I have no clue what happened in the last mile", "LOSS_OF_FOCUS"),

    # STRESS – paraphrased
    ("I'm freaking out about this drive", "STRESS"),
    ("all this pressure is making me crazy", "STRESS"),
    ("my anxiety is through the roof", "STRESS"),

    # FRUSTRATION – paraphrased
    ("ugh this commute is the absolute worst", "FRUSTRATION"),
    ("I can't believe how terrible these drivers are", "FRUSTRATION"),
    ("this stupid traffic won't move at all", "FRUSTRATION"),

    # DISTRESS – paraphrased
    ("I feel like I might collapse", "DISTRESS"),
    ("my head is pounding and I can't think", "DISTRESS"),
    ("I'm seeing double right now", "DISTRESS"),
    ("something is wrong with my breathing", "DISTRESS"),

    # URGENT_STOP – paraphrased
    ("we have to stop this car right this second", "URGENT_STOP"),
    ("get me to a hospital as fast as possible", "URGENT_STOP"),
    ("I'm about to lose consciousness please stop", "URGENT_STOP"),

    # NORMAL – paraphrased
    ("let's grab some coffee at the next exit", "NORMAL"),
    ("how much longer until we arrive", "NORMAL"),
    ("the kids are being quiet back there", "NORMAL"),
    ("that sunset looks amazing", "NORMAL"),
]


def load_dataset(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    texts, labels = [], []
    for intent, samples in data.items():
        for text in samples:
            texts.append(text.strip().lower())
            labels.append(intent)
    return texts, labels


def evaluate():
    print("\n" + "=" * 64)
    print(" INTENT CLASSIFIER — EVALUATION REPORT")
    print("=" * 64)

    # ---- Load model ----
    vectorizer = joblib.load(os.path.join(MODEL_DIR, "tfidf_vectorizer.joblib"))
    clf = joblib.load(os.path.join(MODEL_DIR, "intent_classifier.joblib"))
    le = joblib.load(os.path.join(MODEL_DIR, "label_encoder.joblib"))
    classes = list(le.classes_)
    print(f"\n  Model loaded. Classes: {classes}\n")

    # ---- Train/test split evaluation ----
    texts, labels = load_dataset(DATA_PATH)
    X_all = vectorizer.transform([t.lower() for t in texts])
    y_all = le.transform(labels)

    # Stratified 80/20 split
    X_train, X_test, y_train, y_test = train_test_split(
        X_all, y_all, test_size=0.2, random_state=42, stratify=y_all,
    )

    # Retrain on the split for fair evaluation
    clf_eval = clf.__class__(**clf.get_params())
    clf_eval.fit(X_train, y_train)
    y_pred = clf_eval.predict(X_test)

    print("  ── HELD-OUT TEST SET (20% stratified split) ──\n")
    print(f"  Accuracy:  {accuracy_score(y_test, y_pred):.4f}")
    print(f"  Precision: {precision_score(y_test, y_pred, average='weighted'):.4f}")
    print(f"  Recall:    {recall_score(y_test, y_pred, average='weighted'):.4f}")
    print(f"  F1-score:  {f1_score(y_test, y_pred, average='weighted'):.4f}")

    print("\n  Per-class report:")
    report = classification_report(
        y_test, y_pred, target_names=classes, digits=3,
    )
    for line in report.split("\n"):
        print(f"    {line}")

    # ---- Confusion matrix ----
    cm = confusion_matrix(y_test, y_pred)
    print("\n  Confusion matrix:")
    header = "  {:>15s}".format("") + "".join(f" {c[:7]:>7s}" for c in classes)
    print(header)
    for i, row in enumerate(cm):
        row_str = "  {:>15s}".format(classes[i][:15])
        row_str += "".join(f" {v:7d}" for v in row)
        print(row_str)

    # ---- Full model on training data ----
    print("\n\n  ── FULL MODEL ON TRAINING DATA ──\n")
    y_full_pred = clf.predict(X_all)
    print(f"  Accuracy:  {accuracy_score(y_all, y_full_pred):.4f}")
    print(f"  F1-score:  {f1_score(y_all, y_full_pred, average='weighted'):.4f}")

    # ---- Unseen / paraphrased phrases ----
    print("\n\n  ── UNSEEN / PARAPHRASED PHRASE TEST ──\n")
    correct = 0
    total = len(UNSEEN_PHRASES)

    for phrase, expected in UNSEEN_PHRASES:
        X_u = vectorizer.transform([phrase.lower()])
        proba = clf.predict_proba(X_u)[0]
        pred_idx = int(np.argmax(proba))
        predicted = le.inverse_transform([pred_idx])[0]
        conf = proba[pred_idx]
        match = "✓" if predicted == expected else "✗"
        if predicted == expected:
            correct += 1
        print(f"    {match}  \"{phrase}\"")
        print(f"       expected={expected}  predicted={predicted}  conf={conf:.3f}")

    print(f"\n  Unseen accuracy: {correct}/{total} = {correct/total:.2%}")

    print("\n" + "=" * 64)
    print(" EVALUATION COMPLETE")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    evaluate()
