"""
Audio pipeline diagnostic – run this to test each stage independently.

    venv312/bin/python3 tests/diagnose_audio.py

Tests:
  1. Microphone capture (is audio coming in?)
  2. VAD (is speech being detected?)
  3. Whisper STT (can it transcribe?)
"""

from __future__ import annotations

import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.vad import EnergyVAD


def test_microphone(duration=4):
    """Record a few seconds and report energy levels."""
    print("\n" + "=" * 56)
    print(" STAGE 1: MICROPHONE CAPTURE")
    print("=" * 56)

    try:
        import pyaudio
        print(f"  pyaudio version: {pyaudio.__version__}")
    except ImportError:
        print("  FAIL: pyaudio not installed!")
        return None

    pa = pyaudio.PyAudio()

    # Show available input devices
    print("\n  Available input devices:")
    default_idx = None
    try:
        default_info = pa.get_default_input_device_info()
        default_idx = default_info["index"]
    except Exception:
        pass

    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            marker = " <-- DEFAULT" if i == default_idx else ""
            print(f"    [{i}] {info['name']} (inputs={info['maxInputChannels']}){marker}")

    print(f"\n  Recording {duration}s of audio... SPEAK NOW!")
    print("  " + "-" * 40)

    RATE = 16000
    CHUNK = int(RATE * 0.5)  # 0.5s chunks
    chunks = []

    try:
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )

        vad = EnergyVAD(energy_threshold=0.015, min_speech_chunks=2)

        for i in range(int(duration / 0.5)):
            raw = stream.read(CHUNK, exception_on_overflow=False)
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            rms = EnergyVAD.rms_energy(samples)
            is_speech = vad.is_speech(samples)
            peak = float(np.max(np.abs(samples)))
            bar = "#" * int(min(rms * 500, 40))
            status = "SPEECH" if is_speech else "silence"
            print(f"    chunk {i:2d}  rms={rms:.4f}  peak={peak:.3f}  [{status:7s}]  {bar}")
            chunks.append(samples)

        stream.stop_stream()
        stream.close()
        print("  " + "-" * 40)
        print("  Microphone OK!")

        all_audio = np.concatenate(chunks)
        overall_rms = EnergyVAD.rms_energy(all_audio)
        print(f"  Overall RMS: {overall_rms:.4f}")

        if overall_rms < 0.002:
            print("  WARNING: Very low audio level. Mic might be muted or too far.")
        elif overall_rms < 0.01:
            print("  NOTE: Low audio. VAD threshold (0.015) may be too high for your mic.")
            print("        Try lowering it or speaking louder/closer.")

        pa.terminate()
        return all_audio

    except Exception as e:
        print(f"  FAIL: {e}")
        pa.terminate()
        return None


def test_whisper(audio):
    """Try to transcribe the recorded audio."""
    print("\n" + "=" * 56)
    print(" STAGE 2: WHISPER TRANSCRIPTION")
    print("=" * 56)

    try:
        from faster_whisper import WhisperModel
        print("  faster-whisper: installed")
    except ImportError:
        print("  FAIL: faster-whisper not installed!")
        return

    print("  Loading 'base' model (first time may download ~150MB)...")
    t0 = time.time()
    model = WhisperModel("base", device="cpu", compute_type="int8")
    print(f"  Model loaded in {time.time() - t0:.1f}s")

    print("  Transcribing recorded audio...")
    t0 = time.time()
    segments, info = model.transcribe(
        audio, beam_size=1, language="en", vad_filter=True,
    )

    texts = []
    for seg in segments:
        texts.append(seg.text.strip())
        prob = min(max(2.0 ** seg.avg_logprob, 0.0), 1.0)
        print(f"    segment: \"{seg.text.strip()}\"  conf={prob:.2f}")

    transcript = " ".join(texts).strip()
    elapsed = time.time() - t0
    print(f"  Transcription: \"{transcript}\"")
    print(f"  Time: {elapsed:.1f}s")

    if not transcript:
        print("  WARNING: Empty transcript. Possible causes:")
        print("    - Audio too quiet (speak louder/closer)")
        print("    - VAD filtered everything as silence")
        print("    - Background noise too high")

    return transcript


def test_intent(transcript):
    """Classify the transcript."""
    print("\n" + "=" * 56)
    print(" STAGE 3: INTENT CLASSIFICATION")
    print("=" * 56)

    from audio.intent_classifier import IntentClassifier
    clf = IntentClassifier()

    if not transcript:
        print("  (skipped - no transcript)")
        return

    ev = clf.classify(transcript, stt_confidence=0.9)
    print(f"  Transcript: \"{ev.transcript}\"")
    print(f"  Intent:     {ev.intent}")
    print(f"  Risk:       {ev.risk_score}")
    print(f"  Confidence: {ev.confidence}")


def main():
    print("\nAudio Pipeline Diagnostic")
    print("Speak clearly when prompted!\n")

    audio = test_microphone(duration=5)

    if audio is not None:
        transcript = test_whisper(audio)
        test_intent(transcript)
    else:
        print("\n  Cannot test further stages without mic audio.")

    print("\n" + "=" * 56)
    print(" DONE")
    print("=" * 56 + "\n")


if __name__ == "__main__":
    main()
