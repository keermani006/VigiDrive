"""
detector.py
-----------
The DrowsinessDetector class: everything the project does to a single frame.

Pipeline per frame
    1. MediaPipe Face Mesh  -> 468 facial landmarks
    2. EAR (eyes)           -> eyes open / closed
    3. MAR (mouth)          -> yawning
    4. cv2.solvePnP         -> head yaw / pitch / roll
    5. State machine        -> consecutive-frame counters + thresholds
    6. Overlay + events     -> annotated frame and a list of new events

The single most important design decision lives in step 5: an alert only fires
once a condition has held for N *consecutive* frames, which is what stops
ordinary blinking from raising a drowsiness alarm.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from face_mesh import FaceMeshDetector

from utils import (
    GREEN,
    GREY,
    ORANGE,
    RED,
    WHITE,
    aspect_ratio,
    draw_alerts,
    draw_no_face,
    draw_points,
    draw_status_panel,
    landmarks_to_points,
)

# --------------------------------------------------------------------------- #
# MediaPipe Face Mesh landmark indices
# Order for the ratio helper: (p1, p2, p3, p4, p5, p6)
#   p1 / p4 = horizontal corners,  (p2,p6) and (p3,p5) = vertical pairs
# --------------------------------------------------------------------------- #
LEFT_EYE = (362, 385, 387, 263, 373, 380)
RIGHT_EYE = (33, 160, 158, 133, 153, 144)
MOUTH = (78, 81, 311, 308, 402, 178)

# Points used for head pose (must match MODEL_POINTS_3D below, in order)
POSE_LANDMARKS = (1, 152, 33, 263, 61, 291)  # nose tip, chin, eye corners, mouth corners

# Generic 3D face model (millimetres, nose tip at origin)
MODEL_POINTS_3D = np.array(
    [
        (0.0, 0.0, 0.0),           # nose tip
        (0.0, -63.6, -12.5),       # chin
        (-43.3, 32.7, -26.0),      # left eye, outer corner
        (43.3, 32.7, -26.0),       # right eye, outer corner
        (-28.9, -28.9, -24.1),     # left mouth corner
        (28.9, -28.9, -24.1),      # right mouth corner
    ],
    dtype=np.float64,
)


@dataclass
class DetectorConfig:
    """All tunable thresholds in one place (exposed as CLI flags in main.py)."""

    ear_threshold: float = 0.25        # below this, the eye counts as closed
    ear_frames: int = 20               # consecutive frames -> DROWSY
    mar_threshold: float = 0.60        # above this, the mouth counts as wide open
    mar_frames: int = 15               # consecutive frames -> YAWNING
    yaw_threshold: float = 25.0        # degrees left/right off-centre
    pitch_threshold: float = 20.0      # degrees up/down off-centre
    pose_frames: int = 20              # consecutive frames -> DISTRACTED
    draw_landmarks: bool = True


@dataclass
class FrameResult:
    """What the detector learned about one frame."""

    face_found: bool = False
    ear: float = 0.0
    mar: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    alerts: list = field(default_factory=list)   # currently active alert names
    events: list = field(default_factory=list)   # (event, details) newly started


class DrowsinessDetector:
    """Wraps Face Mesh + all three checks behind a single process_frame() call."""

    def __init__(self, config: DetectorConfig | None = None, face_mesh=None):
        """
        config    : thresholds (see DetectorConfig)
        face_mesh : optional landmark backend; anything with .process(rgb) ->
                    landmark list or None. Left as None in normal use; the
                    self-test injects a fake one so it can run without a camera.
        """
        self.cfg = config or DetectorConfig()

        self.face_mesh = face_mesh if face_mesh is not None else FaceMeshDetector()

        # --- state machine counters ---
        self.eye_counter = 0
        self.mouth_counter = 0
        self.pose_counter = 0

        # --- latched alert states (so each episode is logged exactly once) ---
        self.drowsy_active = False
        self.yawn_active = False
        self.distracted_active = False

        # --- running totals, printed in the end-of-run summary ---
        self.total_drowsy = 0
        self.total_yawns = 0
        self.total_distractions = 0

    # ------------------------------------------------------------------ #
    # Head pose
    # ------------------------------------------------------------------ #
    @staticmethod
    def _estimate_head_pose(points: np.ndarray, frame_shape):
        """cv2.solvePnP -> (yaw, pitch, roll) in degrees."""
        h, w = frame_shape[:2]
        image_points = np.array([points[i] for i in POSE_LANDMARKS], dtype=np.float64)

        focal_length = float(w)
        camera_matrix = np.array(
            [[focal_length, 0, w / 2.0],
             [0, focal_length, h / 2.0],
             [0, 0, 1]],
            dtype=np.float64,
        )
        dist_coeffs = np.zeros((4, 1))       # assume no lens distortion

        ok, rotation_vec, _ = cv2.solvePnP(
            MODEL_POINTS_3D,
            image_points,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok:
            return 0.0, 0.0, 0.0

        rotation_mat, _ = cv2.Rodrigues(rotation_vec)
        angles = cv2.RQDecomp3x3(rotation_mat)[0]     # (pitch, yaw, roll) degrees

        def normalise(a):
            """Map an angle into [-90, 90] so 'looking straight ahead' is ~0."""
            a = float(a)
            while a > 90:
                a -= 180
            while a < -90:
                a += 180
            return a

        pitch, yaw, roll = (normalise(a) for a in angles)
        return yaw, pitch, roll

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def process_frame(self, frame, frame_idx: int = 0, video_time: float = 0.0):
        """
        Analyse one BGR frame, draw the overlays on it in-place and return
        (annotated_frame, FrameResult).
        """
        result = FrameResult()
        h, w = frame.shape[:2]

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        landmarks = self.face_mesh.process(rgb)

        if landmarks is None:
            # No face -> reset every counter, clear every latched alert.
            self.eye_counter = self.mouth_counter = self.pose_counter = 0
            self.drowsy_active = self.yawn_active = self.distracted_active = False
            draw_no_face(frame)
            self._draw_panel(frame, result)
            return frame, result

        result.face_found = True
        points = landmarks_to_points(landmarks, w, h)

        # ---------------- 1. EAR (eyes) ----------------
        left_ear = aspect_ratio(points, LEFT_EYE)
        right_ear = aspect_ratio(points, RIGHT_EYE)
        result.ear = (left_ear + right_ear) / 2.0

        # ---------------- 2. MAR (mouth) ----------------
        result.mar = aspect_ratio(points, MOUTH)

        # ---------------- 3. Head pose ----------------
        result.yaw, result.pitch, result.roll = self._estimate_head_pose(points, frame.shape)

        # ---------------- 4. State machine ----------------
        cfg = self.cfg

        # eyes closed?
        if result.ear < cfg.ear_threshold:
            self.eye_counter += 1
        else:
            self.eye_counter = 0
            self.drowsy_active = False

        if self.eye_counter >= cfg.ear_frames:
            result.alerts.append("DROWSINESS ALERT!")
            if not self.drowsy_active:                       # rising edge only
                self.drowsy_active = True
                self.total_drowsy += 1
                result.events.append(("DROWSINESS", f"EAR={result.ear:.3f}"))

        # yawning?
        if result.mar > cfg.mar_threshold:
            self.mouth_counter += 1
        else:
            self.mouth_counter = 0
            self.yawn_active = False

        if self.mouth_counter >= cfg.mar_frames:
            result.alerts.append("YAWNING")
            if not self.yawn_active:
                self.yawn_active = True
                self.total_yawns += 1
                result.events.append(("YAWN", f"MAR={result.mar:.3f}"))

        # looking away?
        looking_away = (
            abs(result.yaw) > cfg.yaw_threshold or abs(result.pitch) > cfg.pitch_threshold
        )
        if looking_away:
            self.pose_counter += 1
        else:
            self.pose_counter = 0
            self.distracted_active = False

        if self.pose_counter >= cfg.pose_frames:
            result.alerts.append("DISTRACTED - EYES ON ROAD")
            if not self.distracted_active:
                self.distracted_active = True
                self.total_distractions += 1
                result.events.append(
                    ("DISTRACTION", f"yaw={result.yaw:.1f} pitch={result.pitch:.1f}")
                )

        # ---------------- 5. Overlays ----------------
        if cfg.draw_landmarks:
            eye_color = RED if self.eye_counter else GREEN
            mouth_color = RED if self.mouth_counter else GREEN
            draw_points(frame, points, LEFT_EYE, eye_color, 2)
            draw_points(frame, points, RIGHT_EYE, eye_color, 2)
            draw_points(frame, points, MOUTH, mouth_color, 2)
            draw_points(frame, points, POSE_LANDMARKS, ORANGE, 2)

        self._draw_panel(frame, result)
        draw_alerts(frame, result.alerts)
        return frame, result

    # ------------------------------------------------------------------ #
    def _draw_panel(self, frame, result: FrameResult):
        cfg = self.cfg
        if not result.face_found:
            draw_status_panel(frame, [("FACE: not detected", ORANGE)])
            return

        ear_color = RED if result.ear < cfg.ear_threshold else GREEN
        mar_color = RED if result.mar > cfg.mar_threshold else GREEN
        pose_color = (
            RED
            if abs(result.yaw) > cfg.yaw_threshold or abs(result.pitch) > cfg.pitch_threshold
            else GREEN
        )

        lines = [
            (f"EAR : {result.ear:.3f}  (<{cfg.ear_threshold})", ear_color),
            (f"MAR : {result.mar:.3f}  (>{cfg.mar_threshold})", mar_color),
            (f"YAW : {result.yaw:6.1f}  PITCH: {result.pitch:6.1f}", pose_color),
            (
                f"counters e:{self.eye_counter} m:{self.mouth_counter} h:{self.pose_counter}",
                GREY,
            ),
            (
                f"drowsy:{self.total_drowsy}  yawns:{self.total_yawns}  "
                f"distract:{self.total_distractions}",
                WHITE,
            ),
        ]
        draw_status_panel(frame, lines, width=300)

    # ------------------------------------------------------------------ #
    def close(self):
        self.face_mesh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
