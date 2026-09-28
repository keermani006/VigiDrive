"""
main.py
-------
Command-line entry point for the Driver Drowsiness & Distraction Detection System.

Examples
    python main.py                                        # webcam, live window
    python main.py --source webcam --output outputs/annotated_output.mp4
    python main.py --source drive.mp4 --log outputs/events_log.csv
    python main.py --source webcam --ear-threshold 0.22 --ear-frames 25
    python main.py --source drive.mp4 --no-display        # headless batch run

Press 'q' or ESC in the video window to quit early.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import cv2

from detector import DetectorConfig, DrowsinessDetector
from utils import AlarmPlayer, EventLogger

DEFAULT_ALARM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "alarm.wav")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Real-time driver drowsiness & distraction detection (OpenCV + MediaPipe).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--source", default="webcam",
                   help="'webcam', a camera index like '0', or a path to a video file")
    p.add_argument("--output", default=None,
                   help="path to save the annotated video, e.g. outputs/annotated_output.mp4")
    p.add_argument("--log", default=None,
                   help="path to save the CSV event log, e.g. outputs/events_log.csv")

    p.add_argument("--ear-threshold", type=float, default=0.25,
                   help="EAR below this counts as a closed eye")
    p.add_argument("--ear-frames", type=int, default=20,
                   help="consecutive closed-eye frames before a DROWSINESS alert")
    p.add_argument("--mar-threshold", type=float, default=0.60,
                   help="MAR above this counts as a wide-open mouth")
    p.add_argument("--mar-frames", type=int, default=15,
                   help="consecutive open-mouth frames before a YAWN alert")
    p.add_argument("--yaw-threshold", type=float, default=25.0,
                   help="degrees of left/right head turn allowed")
    p.add_argument("--pitch-threshold", type=float, default=20.0,
                   help="degrees of up/down head tilt allowed")
    p.add_argument("--pose-frames", type=int, default=20,
                   help="consecutive looking-away frames before a DISTRACTION alert")

    p.add_argument("--alarm", default=DEFAULT_ALARM, help="path to the alert .wav file")
    p.add_argument("--no-sound", action="store_true", help="disable the audio alarm")
    p.add_argument("--no-display", action="store_true",
                   help="do not open a window (useful for headless / server runs)")
    p.add_argument("--no-landmarks", action="store_true",
                   help="do not draw the landmark dots on the frame")
    p.add_argument("--max-frames", type=int, default=0,
                   help="stop after N frames (0 = no limit); handy for quick tests")
    return p.parse_args(argv)


def open_capture(source: str):
    """Open a webcam index or a video file and return (capture, is_webcam)."""
    if source.lower() == "webcam":
        return cv2.VideoCapture(0), True
    if source.isdigit():
        return cv2.VideoCapture(int(source)), True
    if not os.path.exists(source):
        sys.exit(f"[ERROR] Video file not found: {source}")
    return cv2.VideoCapture(source), False


def main(argv=None):
    args = parse_args(argv)

    cap, is_webcam = open_capture(args.source)
    if not cap.isOpened():
        sys.exit(f"[ERROR] Could not open video source: {args.source}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 1 or fps > 120:
        fps = 30.0

    writer = None
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        writer = cv2.VideoWriter(
            args.output, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
        )
        if not writer.isOpened():
            sys.exit(f"[ERROR] Could not open the video writer for: {args.output}")

    config = DetectorConfig(
        ear_threshold=args.ear_threshold,
        ear_frames=args.ear_frames,
        mar_threshold=args.mar_threshold,
        mar_frames=args.mar_frames,
        yaw_threshold=args.yaw_threshold,
        pitch_threshold=args.pitch_threshold,
        pose_frames=args.pose_frames,
        draw_landmarks=not args.no_landmarks,
    )

    alarm = AlarmPlayer(args.alarm, cooldown=2.0, enabled=not args.no_sound)
    logger = EventLogger(args.log)
    detector = DrowsinessDetector(config)

    print(f"[INFO] source={args.source}  {width}x{height} @ {fps:.1f} fps")
    print(f"[INFO] thresholds: EAR<{config.ear_threshold} for {config.ear_frames}f | "
          f"MAR>{config.mar_threshold} for {config.mar_frames}f | "
          f"yaw>{config.yaw_threshold} pitch>{config.pitch_threshold} for {config.pose_frames}f")
    if not args.no_display:
        print("[INFO] press 'q' or ESC in the window to quit")

    frame_idx = 0
    start = time.time()
    display_fps = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if is_webcam:
                frame = cv2.flip(frame, 1)          # mirror the webcam view

            frame_idx += 1
            video_time = frame_idx / fps
            frame, result = detector.process_frame(frame, frame_idx, video_time)

            for event, details in result.events:
                logger.log(event, frame_idx, video_time, details)
            if result.events:
                alarm.play()

            elapsed = time.time() - start
            if elapsed > 0:
                display_fps = 0.9 * display_fps + 0.1 * (frame_idx / elapsed)
            cv2.putText(frame, f"FPS: {display_fps:4.1f}", (width - 130, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)

            if writer is not None:
                writer.write(frame)

            if not args.no_display:
                cv2.imshow("Driver Drowsiness & Distraction Detection", frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break

            if args.max_frames and frame_idx >= args.max_frames:
                break
    except KeyboardInterrupt:
        print("\n[INFO] interrupted by user")
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        detector.close()
        logger.close()
        cv2.destroyAllWindows()

    total = time.time() - start
    print("\n" + "=" * 46)
    print(" SESSION SUMMARY")
    print("=" * 46)
    print(f" frames processed   : {frame_idx}")
    print(f" duration           : {total:.1f}s  ({frame_idx / total if total else 0:.1f} fps)")
    print(f" drowsiness alerts  : {detector.total_drowsy}")
    print(f" yawns detected     : {detector.total_yawns}")
    print(f" distraction alerts : {detector.total_distractions}")
    if args.output:
        print(f" annotated video    : {args.output}")
    if args.log:
        print(f" event log          : {args.log}  ({logger.count} rows)")
    print("=" * 46)


if __name__ == "__main__":
    main()
