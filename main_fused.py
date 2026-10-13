"""
main_fused.py
-------------
Multimodal entry point:  existing CV system + voice subsystem + fusion.

This file is a thin wrapper that:
    1. Reuses the UNCHANGED existing ``DrowsinessDetector`` and video loop.
    2. Starts the audio pipeline in a background thread.
    3. Feeds both CV and audio evidence into the fusion engine each frame.
    4. Draws a small debug overlay showing the fused alertness state.

The original ``main.py`` continues to work exactly as before.
Run this file instead when you want the multimodal fusion:

    python main_fused.py                       # webcam, live window, voice
    python main_fused.py --no-voice            # disable voice (CV only)
    python main_fused.py --whisper-model tiny   # smaller / faster model

Press 'q' or ESC in the video window to quit.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import cv2

from detector import DetectorConfig, DrowsinessDetector
from utils import AlarmPlayer, EventLogger, BLACK, WHITE, GREEN, ORANGE, RED

from audio.pipeline import AudioPipeline
from fusion.cv_adapter import CVAdapter
from fusion.fusion_engine import FusionConfig, FusionEngine
from fusion.alertness_state import AlertnessState

DEFAULT_ALARM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "alarm.wav")

# Map alertness states to BGR colours for the overlay.
_STATE_COLOURS = {
    AlertnessState.NORMAL:             GREEN,
    AlertnessState.ATTENTION_DEGRADED: ORANGE,
    AlertnessState.DROWSY:             ORANGE,
    AlertnessState.DISTRACTED:         ORANGE,
    AlertnessState.HIGH_RISK:          RED,
    AlertnessState.ALERT:              RED,
}


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Multimodal driver monitoring: CV + Voice + Fusion.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # ---------- existing CV args (same as main.py) ----------
    p.add_argument("--source", default="webcam",
                   help="'webcam', camera index, or path to video file")
    p.add_argument("--output", default=None,
                   help="path to save annotated video")
    p.add_argument("--log", default=None,
                   help="path to save the CSV event log")
    p.add_argument("--ear-threshold", type=float, default=0.25)
    p.add_argument("--ear-frames", type=int, default=20)
    p.add_argument("--mar-threshold", type=float, default=0.60)
    p.add_argument("--mar-frames", type=int, default=15)
    p.add_argument("--yaw-threshold", type=float, default=25.0)
    p.add_argument("--pitch-threshold", type=float, default=20.0)
    p.add_argument("--pose-frames", type=int, default=20)
    p.add_argument("--alarm", default=DEFAULT_ALARM)
    p.add_argument("--no-sound", action="store_true")
    p.add_argument("--no-display", action="store_true")
    p.add_argument("--no-landmarks", action="store_true")
    p.add_argument("--max-frames", type=int, default=0)

    # ---------- new voice / fusion args ----------
    p.add_argument("--no-voice", action="store_true",
                   help="disable voice subsystem (run CV only, same as main.py)")
    p.add_argument("--whisper-model", default="tiny",
                   help="faster-whisper model size: tiny, base, small, …")
    p.add_argument("--whisper-device", default="cpu",
                   help="'cpu' or 'cuda'")
    p.add_argument("--whisper-language", default="en",
                   help="language code, or empty for auto-detect")
    p.add_argument("--audio-device", type=int, default=None,
                   help="PortAudio device index for the microphone")
    p.add_argument("--audio-ttl", type=float, default=10.0,
                   help="seconds before audio evidence expires")
    p.add_argument("--audio-weight", type=float, default=0.30,
                   help="weight of audio in the fused score (0–1)")
    p.add_argument("--serial-port", default=None,
                   help="Serial port for Proteus/ECU bridge (e.g. COM1 or /dev/ttyUSB0)")
    p.add_argument("--serial-baud", type=int, default=9600,
                   help="Baud rate for serial bridge")
    p.add_argument("--no-fusion-overlay", action="store_true",
                   help="hide the fusion debug overlay")
    return p.parse_args(argv)


def open_capture(source: str):
    if source.lower() == "webcam":
        return cv2.VideoCapture(0), True
    if source.isdigit():
        return cv2.VideoCapture(int(source)), True
    if not os.path.exists(source):
        sys.exit(f"[ERROR] Video file not found: {source}")
    return cv2.VideoCapture(source), False


# --------------------------------------------------------------------------- #
# Fusion debug overlay
# --------------------------------------------------------------------------- #
def draw_fusion_overlay(frame, result, audio_evidence, cv_evidence):
    """
    Small panel on the right side of the frame showing:
        VOICE / FUSION info.
    Does NOT touch or replace any existing overlays.
    """
    h, w = frame.shape[:2]
    panel_w = 340
    x0 = w - panel_w - 10
    y0 = 50  # below the FPS counter

    lines = []

    # Voice section
    lines.append(("--- VOICE ---", WHITE))
    if audio_evidence is not None:
        age = time.time() - audio_evidence.timestamp
        transcript = audio_evidence.transcript[:35]
        lines.append((f"Transcript: {transcript}", WHITE))
        lines.append((f"Intent: {audio_evidence.intent}", WHITE))
        lines.append((f"Voice Risk: {audio_evidence.risk_score:.2f}  (age {age:.0f}s)", WHITE))
    else:
        lines.append(("(no voice data)", (120, 120, 120)))

    lines.append(("", WHITE))

    # CV evidence
    cv_score = cv_evidence.drowsiness_score if cv_evidence else 0.0
    lines.append((f"CV Evidence: {cv_score:.2f}", WHITE))

    lines.append(("", WHITE))

    # Fused result
    state_color = _STATE_COLOURS.get(result.state, WHITE)
    lines.append(("--- FUSION ---", WHITE))
    lines.append((f"ALERTNESS: {result.state_name}", state_color))
    lines.append((f"Score: {result.score:.2f}", state_color))

    # Wrap long reason
    reason = result.reason
    if len(reason) > 38:
        lines.append((f"Reason: {reason[:38]}", WHITE))
        lines.append((f"  {reason[38:]}", WHITE))
    else:
        lines.append((f"Reason: {reason}", WHITE))

    # Draw background
    line_h = 20
    panel_h = line_h * len(lines) + 16
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + panel_w, y0 + panel_h), BLACK, -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    for i, (text, color) in enumerate(lines):
        if text:
            cv2.putText(
                frame, text,
                (x0 + 8, y0 + 18 + i * line_h),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA,
            )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None):
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

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
            sys.exit(f"[ERROR] Could not open video writer for: {args.output}")

    # ---- Existing CV system (unchanged) ----
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

    # ---- New: Fusion engine + CV adapter ----
    cv_adapter = CVAdapter()
    # ---- Serial bridge (Proteus / Hardware ECU) ----
    serial_conn = None
    if args.serial_port:
        try:
            import serial
            serial_conn = serial.Serial(args.serial_port, args.serial_baud, timeout=0.1)
            print(f"[INFO] Serial ECU bridge connected on {args.serial_port} @ {args.serial_baud} baud")
        except Exception as exc:
            logging.warning("Could not open serial port %s: %s", args.serial_port, exc)
            serial_conn = None

    last_sent_state = None
    last_serial_send = 0.0

    fusion_engine = FusionEngine(FusionConfig(
        audio_evidence_ttl=args.audio_ttl,
        audio_weight=args.audio_weight,
    ))

    # ---- New: Audio pipeline (async, background) ----
    audio_pipeline = None
    if not args.no_voice and is_webcam:
        try:
            audio_pipeline = AudioPipeline(
                whisper_model=args.whisper_model,
                whisper_device=args.whisper_device,
                whisper_language=args.whisper_language or None,
                device_index=args.audio_device,
            )
            audio_pipeline.start()
        except Exception as exc:
            logging.warning("Could not start audio pipeline: %s", exc)
            audio_pipeline = None
    elif not args.no_voice and not is_webcam:
        logging.info("Voice subsystem disabled for video-file input (no live mic)")

    print(f"[INFO] source={args.source}  {width}x{height} @ {fps:.1f} fps")
    if audio_pipeline:
        # Give the mic thread a moment to initialize and report status
        time.sleep(0.5)
        mic_ok = audio_pipeline._mic.is_running
        print(f"[INFO] voice=ON  mic={'ACTIVE' if mic_ok else 'FAILED (CV-only mode)'}")
        if not mic_ok:
            logging.warning(
                "Microphone failed to start. Voice detection disabled. "
                "Check: is pyaudio installed in this venv? Is a mic connected?"
            )
    else:
        print("[INFO] voice=OFF")
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
                frame = cv2.flip(frame, 1)

            frame_idx += 1
            video_time = frame_idx / fps

            # ---- Step 1: existing CV processing (UNCHANGED) ----
            frame, result = detector.process_frame(frame, frame_idx, video_time)

            # ---- Step 2: existing alarm + logging (UNCHANGED) ----
            for event, details in result.events:
                logger.log(event, frame_idx, video_time, details)
            if result.events:
                alarm.play()

            # ---- Step 3: NEW – extract CV evidence ----
            cv_evidence = cv_adapter.extract(detector, result)

            # ---- Step 4: NEW – get latest audio evidence (non-blocking) ----
            audio_evidence = None
            if audio_pipeline is not None:
                audio_evidence = audio_pipeline.latest_evidence

            # ---- Step 5: NEW – fuse ----
            fused = fusion_engine.fuse(cv_evidence, audio_evidence)

            # ---- Stream state to Proteus ECU over Serial ----
            if serial_conn is not None:
                now_s = time.time()
                if fused.state.name != last_sent_state or (now_s - last_serial_send) >= 0.3:
                    try:
                        serial_conn.write(f"{fused.state.name}\n".encode())
                        last_sent_state = fused.state.name
                        last_serial_send = now_s
                    except Exception as err:
                        logging.debug("Serial write failed: %s", err)

            # ---- Step 6: NEW – draw fusion overlay ----
            if not args.no_fusion_overlay and not args.no_display:
                draw_fusion_overlay(frame, fused, audio_evidence, cv_evidence)

            # ---- FPS counter (existing) ----
            elapsed = time.time() - start
            if elapsed > 0:
                display_fps = 0.9 * display_fps + 0.1 * (frame_idx / elapsed)
            cv2.putText(frame, f"FPS: {display_fps:4.1f}", (width - 130, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)

            if writer is not None:
                writer.write(frame)

            if not args.no_display:
                cv2.imshow("Driver Monitoring: CV + Voice Fusion", frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break

            if args.max_frames and frame_idx >= args.max_frames:
                break

    except KeyboardInterrupt:
        print("\n[INFO] interrupted by user")
    finally:
        cap.release()
        if serial_conn is not None:
            try:
                serial_conn.close()
            except Exception:
                pass
        if writer is not None:
            writer.release()
        detector.close()
        logger.close()
        if audio_pipeline is not None:
            audio_pipeline.stop()
        cv2.destroyAllWindows()

    total = time.time() - start
    print("\n" + "=" * 54)
    print(" SESSION SUMMARY (Multimodal)")
    print("=" * 54)
    print(f" frames processed   : {frame_idx}")
    print(f" duration           : {total:.1f}s  ({frame_idx / total if total else 0:.1f} fps)")
    print(f" drowsiness alerts  : {detector.total_drowsy}")
    print(f" yawns detected     : {detector.total_yawns}")
    print(f" distraction alerts : {detector.total_distractions}")
    print(f" voice subsystem    : {'active' if audio_pipeline else 'disabled'}")
    if args.output:
        print(f" annotated video    : {args.output}")
    if args.log:
        print(f" event log          : {args.log}  ({logger.count} rows)")
    print("=" * 54)


if __name__ == "__main__":
    main()
