"""Writes say-1s.wav next to this file: 1.000 s of a 440 Hz tone at -12 dBFS, 44100 Hz, mono, 16-bit PCM (88,244
bytes), the shape the dog's AudioHub upload expects (the driver's own upload converts to 44100 Hz). Standard library
only, so the bytes are reproducible and no voice or model is involved. wtdd/dog/test_audio.py chunks it (base64 in
4096-character blocks, 1-based) and uploads it to the recording stub; a test never sends it to a dog.

  /Users/johnnysheng/code/origin-build/.venv/bin/python wtdd/dog/fixtures/make_say_1s.py
"""
from __future__ import annotations
import math
import struct
import wave
from pathlib import Path

RATE, SECONDS, HZ, AMP = 44100, 1.0, 440.0, 0.25   # 0.25 of full scale is -12 dBFS
OUT = Path(__file__).with_name("say-1s.wav")


def main() -> Path:
    n = round(RATE * SECONDS)
    frames = b"".join(struct.pack("<h", round(AMP * 32767 * math.sin(2 * math.pi * HZ * i / RATE))) for i in range(n))
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    print(f"{OUT.name}: {OUT.stat().st_size} bytes, {n} frames at {RATE} Hz mono 16-bit")
    return OUT


if __name__ == "__main__":
    main()
