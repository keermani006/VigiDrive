"""
fusion – Multimodal evidence fusion engine.

Modules
-------
cv_adapter       : Thin adapter that extracts CVEvidence from the existing
                   detector's output WITHOUT modifying the detector itself.
alertness_state  : Enum-like final alertness states and the AlertnessResult.
fusion_engine    : Deterministic rule-based engine that combines CVEvidence
                   and AudioEvidence into an AlertnessResult.
"""
