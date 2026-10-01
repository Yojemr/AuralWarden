from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


SAMPLE_RATE = 44_100
DESTINATION = Path(__file__).resolve().parents[1] / "src" / "auralwarden" / "ui" / "assets"


def tone(frequency: float, duration: float, amplitude: float) -> list[float]:
    count = round(SAMPLE_RATE * duration)
    attack = max(1, round(count * 0.08))
    release = max(1, round(count * 0.28))
    samples: list[float] = []
    for index in range(count):
        envelope = min(1.0, index / attack, (count - index) / release)
        samples.append(
            amplitude * envelope * math.sin(2.0 * math.pi * frequency * index / SAMPLE_RATE)
        )
    return samples


def silence(duration: float) -> list[float]:
    return [0.0] * round(SAMPLE_RATE * duration)


def write(name: str, samples: list[float]) -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    payload = b"".join(
        struct.pack("<h", max(-32768, min(32767, round(sample * 32767))))
        for sample in samples
    )
    with wave.open(str(DESTINATION / name), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(payload)


def main() -> None:
    write(
        "notification-friendly.wav",
        tone(523.25, 0.16, 0.32) + silence(0.025) + tone(659.25, 0.24, 0.28),
    )
    write(
        "notification-notice.wav",
        tone(659.25, 0.12, 0.43)
        + silence(0.025)
        + tone(783.99, 0.12, 0.43)
        + silence(0.025)
        + tone(987.77, 0.25, 0.40),
    )
    write("notification-discreet.wav", tone(440.0, 0.16, 0.16))


if __name__ == "__main__":
    main()
