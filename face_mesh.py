"""
face_mesh.py
------------
A thin wrapper around MediaPipe's face-landmark model.

Supports both:
1. Legacy MediaPipe Face Mesh
2. New MediaPipe Tasks FaceLandmarker

The Tasks API is explicitly forced to CPU on macOS to avoid
Metal/GPU initialization crashes.
"""

from __future__ import annotations

import os


TASK_MODEL_FILENAME = "face_landmarker.task"

TASK_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)


class FaceMeshDetector:
    """Detects facial landmarks using MediaPipe."""

    def __init__(
        self,
        model_path: str | None = None,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ):
        self.backend = None
        self._impl = None
        self._timestamp_ms = 0

        import mediapipe as mp

        # --------------------------------------------------------------
        # Backend 1: Legacy Solutions API
        # --------------------------------------------------------------
        solutions = getattr(mp, "solutions", None)

        if solutions is not None and hasattr(solutions, "face_mesh"):
            self._impl = solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
            )

            self.backend = "solutions"
            return

        # --------------------------------------------------------------
        # Backend 2: MediaPipe Tasks API
        # --------------------------------------------------------------
        if model_path is None:
            model_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "assets",
                TASK_MODEL_FILENAME,
            )

        if not os.path.exists(model_path):
            raise RuntimeError(
                "This MediaPipe version no longer ships the classic "
                "Face Mesh API, and the Tasks model file was not found at:\n"
                f"    {model_path}\n\n"
                "Download the model into assets/:\n"
                f"    {TASK_MODEL_URL}"
            )

        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        # --------------------------------------------------------------
        # IMPORTANT:
        # Force CPU instead of GPU/Metal.
        #
        # MediaPipe's GPU path can trigger a Metal crash on macOS.
        # --------------------------------------------------------------
        base_options = mp_python.BaseOptions(
            model_asset_path=model_path,
            delegate=mp_python.BaseOptions.Delegate.CPU,
        )

        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

        self._impl = vision.FaceLandmarker.create_from_options(options)

        self._mp = mp
        self.backend = "tasks"

    # ------------------------------------------------------------------
    def process(self, rgb_frame):
        """
        Return the landmark list for the first detected face,
        or None if no face is detected.
        """

        if self.backend == "solutions":
            result = self._impl.process(rgb_frame)

            if not result.multi_face_landmarks:
                return None

            return result.multi_face_landmarks[0].landmark

        # Tasks API
        mp_image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=rgb_frame,
        )

        self._timestamp_ms += 33

        result = self._impl.detect_for_video(
            mp_image,
            self._timestamp_ms,
        )

        if not result.face_landmarks:
            return None

        return result.face_landmarks[0]

    # ------------------------------------------------------------------
    def close(self):
        try:
            if self._impl is not None:
                self._impl.close()
        except Exception:
            pass

