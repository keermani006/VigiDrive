"""
alertness_state.py
------------------
Defines the final alertness states produced by the fusion engine and the
``AlertnessResult`` structure that carries the fused output.

States (ordered by severity)
-----------------------------
NORMAL              – no concern.
ATTENTION_DEGRADED  – early warning; one modality shows mild risk.
DROWSY              – CV-confirmed drowsiness (eyes closed).
DISTRACTED          – CV-confirmed distraction (head pose).
HIGH_RISK           – multiple modalities corroborate elevated risk.
ALERT               – immediate intervention required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List


class AlertnessState(IntEnum):
    """Driver alertness levels, ordered by severity (0 = safest)."""
    NORMAL             = 0
    ATTENTION_DEGRADED = 1
    DROWSY             = 2
    DISTRACTED         = 3
    HIGH_RISK          = 4
    ALERT              = 5

    @classmethod
    def from_name(cls, name: str) -> "AlertnessState":
        """Case-insensitive lookup by name."""
        return cls[name.upper().strip()]


@dataclass
class AlertnessResult:
    """Fused alertness output produced once per fusion cycle."""
    score: float                     # combined severity in [0, 1]
    state: AlertnessState            # overall alertness level
    reason: str                      # human-readable explanation
    cv_score: float = 0.0            # normalised CV evidence score
    audio_score: float = 0.0         # voice risk score
    active_alerts: List[str] = field(default_factory=list)

    @property
    def state_name(self) -> str:
        return self.state.name
