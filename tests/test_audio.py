import wave
from pathlib import Path

from auralwarden.audio import PcmFormat, PcmRingBuffer, pcm_rms, write_pcm_wav


def test_ring_buffer_keeps_only_configured_tail() -> None:
    pcm_format = PcmFormat(sample_rate=10, channels=1, sample_width=2)
    ring = PcmRingBuffer(2, pcm_format)
    ring.append(bytes(range(60)))
    assert ring.duration_seconds == 2.0
    assert ring.snapshot() == bytes(range(20, 60))
    assert ring.tail(0.5) == bytes(range(50, 60))


def test_write_pcm_wav_has_expected_duration(tmp_path: Path) -> None:
    pcm_format = PcmFormat()
    output = tmp_path / "audio.wav"
    write_pcm_wav(output, bytes(pcm_format.bytes_for_seconds(1.25)), pcm_format)
    with wave.open(str(output), "rb") as audio:
        assert audio.getframerate() == 16_000
        assert audio.getnchannels() == 1
        assert audio.getnframes() == 20_000


def test_pcm_rms_distinguishes_silence_from_audio() -> None:
    pcm_format = PcmFormat()
    assert pcm_rms(bytes(32_000), pcm_format) == 0.0
    assert pcm_rms(b"\xe8\x03" * 16_000, pcm_format) > 0.03
