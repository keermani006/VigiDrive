"""
audio – Voice-based driver statement detection subsystem.

Modules
-------
microphone      : Continuous audio capture from the system microphone.
vad             : Voice Activity Detection (energy-based).
speech_to_text  : Transcription via faster-whisper (local, offline).
intent_classifier : Lightweight deterministic statement / intent classifier.
"""
