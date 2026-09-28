"""
test_detector.py
----------------
A dependency-free self-test (no webcam, no face needed).

It builds synthetic facial landmarks, feeds them through DrowsinessDetector,
and checks that:

  * an open eye gives a high EAR and a closed eye a low one
  * DROWSINESS fires only AFTER ear_frames consecutive closed-eye frames
    (i.e. a short blink does NOT trigger it)
  * a sustained wide-open mouth fires YAWN
  * the distraction counter fires once the head angle stays past threshold
  * the CSV log and annotated video are actually written

Run it with:   python test_detector.py
"""

from __future__ import annotations

import os
import tempfile

import cv2
import numpy as np

from detector import DetectorConfig, DrowsinessDetector
from utils import EventLogger

W, H = 640, 480


class _LM:
    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z


class _FakeMesh:
    """Stands in for the MediaPipe backend: .process(rgb) -> landmarks or None."""

    def __init__(self):
        self.landmarks = None

    def process(self, _rgb):
        return self.landmarks

    def close(self):
        pass


def build_face(eye_open=7.0, mouth_open=5.0, x_shift=0.0):
    """
    Synthetic 478-point face. Only the indices the detector uses matter;
    the rest are filler.

    eye_open   = half the vertical eye opening in px (7 -> EAR ~0.28, 0.5 -> ~0.02)
    mouth_open = half the vertical mouth opening in px (5 -> MAR 0.2, 20 -> 0.8)
    x_shift    = shifts the left half of the face to fake a head turn
    """
    pts = [(320.0, 240.0)] * 478

    def put(i, x, y):
        pts[i] = (x, y)

    # left eye: p1=362, p2=385, p3=387, p4=263, p5=373, p6=380
    put(362, 330, 240); put(263, 380, 240)
    put(385, 345, 240 - eye_open); put(387, 365, 240 - eye_open)
    put(373, 365, 240 + eye_open); put(380, 345, 240 + eye_open)

    # right eye: p1=33, p2=160, p3=158, p4=133, p5=153, p6=144
    put(33, 260 + x_shift, 240); put(133, 310, 240)
    put(160, 275, 240 - eye_open); put(158, 295, 240 - eye_open)
    put(153, 295, 240 + eye_open); put(144, 275, 240 + eye_open)

    # mouth: p1=78, p2=81, p3=311, p4=308, p5=402, p6=178
    put(78, 300, 360); put(308, 350, 360)
    put(81, 315, 360 - mouth_open); put(311, 335, 360 - mouth_open)
    put(402, 335, 360 + mouth_open); put(178, 315, 360 + mouth_open)

    # head-pose points: nose, chin, eye corners, mouth corners
    put(1, 320, 300); put(152, 320, 400)
    put(61, 295 + x_shift, 360); put(291, 345, 360)
    return [_LM(x / W, y / H) for (x, y) in pts]


def run(detector, face, n_frames, logger=None, writer=None, start_idx=0):
    """Push n_frames identical synthetic frames through the detector."""
    events = []
    detector.face_mesh.landmarks = face
    for i in range(n_frames):
        frame = np.full((H, W, 3), 40, dtype=np.uint8)
        frame, res = detector.process_frame(frame, start_idx + i, (start_idx + i) / 30.0)
        for ev, det in res.events:
            events.append(ev)
            if logger:
                logger.log(ev, start_idx + i, (start_idx + i) / 30.0, det)
        if writer is not None:
            writer.write(frame)
    return events, res


def main():
    passed = failed = 0

    def check(name, condition, extra=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  PASS  {name} {extra}")
        else:
            failed += 1
            print(f"  FAIL  {name} {extra}")

    print("\nDriver Drowsiness Detection - self test")
    print("-" * 52)

    cfg = DetectorConfig(ear_frames=20, mar_frames=15, pose_frames=20)
    det = DrowsinessDetector(cfg, face_mesh=_FakeMesh())

    tmp = tempfile.mkdtemp()
    log_path = os.path.join(tmp, "events_log.csv")
    vid_path = os.path.join(tmp, "annotated_output.mp4")
    logger = EventLogger(log_path)
    writer = cv2.VideoWriter(vid_path, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (W, H))

    # 1. open eyes, closed mouth, facing forward -> no alerts
    ev, res = run(det, build_face(), 30, logger, writer)
    check("eyes open -> high EAR", res.ear > cfg.ear_threshold, f"(EAR={res.ear:.3f})")
    check("mouth closed -> low MAR", res.mar < cfg.mar_threshold, f"(MAR={res.mar:.3f})")
    check("facing forward -> no alert", not ev and not res.alerts)

    # 2. a short blink (5 frames) must NOT raise an alert
    ev, res = run(det, build_face(eye_open=0.5), 5, logger, writer, 100)
    check("closed eyes -> low EAR", res.ear < cfg.ear_threshold, f"(EAR={res.ear:.3f})")
    check("short blink does NOT alert", "DROWSINESS" not in ev)
    run(det, build_face(), 3, logger, writer, 110)          # eyes reopen -> counter resets

    # 3. sustained eye closure (25 frames) MUST raise exactly one alert
    ev, res = run(det, build_face(eye_open=0.5), 25, logger, writer, 200)
    check("sustained closure -> DROWSINESS", ev.count("DROWSINESS") == 1, f"(events={ev})")
    run(det, build_face(), 3, logger, writer, 230)

    # 4. sustained yawn
    ev, res = run(det, build_face(mouth_open=20), 20, logger, writer, 300)
    check("wide mouth -> high MAR", res.mar > cfg.mar_threshold, f"(MAR={res.mar:.3f})")
    check("sustained yawn -> YAWN event", ev.count("YAWN") == 1, f"(events={ev})")
    run(det, build_face(), 3, logger, writer, 330)

    # 5. head turned away -> DISTRACTION
    det2 = DrowsinessDetector(
        DetectorConfig(yaw_threshold=5.0, pitch_threshold=5.0, pose_frames=20),
        face_mesh=_FakeMesh(),
    )
    ev, res = run(det2, build_face(x_shift=45), 25, logger, writer, 400)
    check("turned head -> non-zero yaw", abs(res.yaw) > 0.0,
          f"(yaw={res.yaw:.1f}, pitch={res.pitch:.1f})")
    check("sustained turn -> DISTRACTION", ev.count("DISTRACTION") == 1, f"(events={ev})")

    # 6. no face at all -> counters reset, no crash
    ev, res = run(det, None, 5, logger, writer, 500)
    check("no face handled safely", not res.face_found and not ev)

    writer.release()
    logger.close()
    det.close()
    det2.close()

    check("CSV log written", os.path.exists(log_path) and os.path.getsize(log_path) > 0,
          f"({logger.count} rows)")
    check("annotated video written", os.path.exists(vid_path) and os.path.getsize(vid_path) > 0,
          f"({os.path.getsize(vid_path)} bytes)")

    print("-" * 52)
    print(f"  {passed} passed, {failed} failed\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
