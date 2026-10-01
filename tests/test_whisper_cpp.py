import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from auralwarden.audio import PcmFormat
from auralwarden.transcribers.whisper_cpp import (
    WhisperCppConfig,
    WhisperCppTranscriber,
    parse_whisper_cpp_json,
)


def test_whisper_cpp_json_is_mapped_to_timed_transcript_entries() -> None:
    payload = {
        "transcription": [
            {
                "timestamps": {"from": "00:00:01,250", "to": "00:00:03,500"},
                "text": " ayuda por favor ",
                "tokens": [
                    {
                        "text": " ayuda",
                        "timestamps": {"from": "00:00:01,250", "to": "00:00:02,000"},
                        "p": 0.9,
                    },
                    {
                        "text": " por favor",
                        "timestamps": {"from": "00:00:02,000", "to": "00:00:03,500"},
                        "p": 0.8,
                    },
                ],
            }
        ]
    }
    entries = parse_whisper_cpp_json(payload, 10.0, high_precision=True)
    assert len(entries) == 1
    assert entries[0].text == "ayuda por favor"
    assert entries[0].elapsed_seconds == 11.25
    assert entries[0].end_seconds == 13.5
    assert entries[0].source == "whisper.cpp"
    assert entries[0].second_pass is True
    assert entries[0].confidence == pytest.approx(0.85)
    assert entries[0].words[0].start_seconds == 11.25


def test_whisper_cpp_numeric_offsets_are_milliseconds() -> None:
    entries = parse_whisper_cpp_json(
        {"transcription": [{"offsets": {"from": 1250, "to": 3500}, "text": "hola"}]},
        5.0,
    )
    assert entries[0].elapsed_seconds == 6.25
    assert entries[0].end_seconds == 8.5


def test_whisper_cpp_verification_omits_prompt_and_live_hotwords(
    tmp_path: Path, monkeypatch
) -> None:
    executable = tmp_path / "whisper-cli.exe"
    model = tmp_path / "model.bin"
    executable.write_bytes(b"exe")
    model.write_bytes(b"model")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        output = Path(command[command.index("-of") + 1]).with_suffix(".json")
        output.write_text(json.dumps({"transcription": []}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("auralwarden.transcribers.whisper_cpp.subprocess.run", fake_run)
    transcriber = WhisperCppTranscriber(
        WhisperCppConfig(
            str(executable),
            str(model),
            initial_prompt="Clase de Python",
            hotwords=["Persona Alfa"],
        )
    )
    pcm_format = PcmFormat()
    pcm = bytes(pcm_format.bytes_for_seconds(1))

    transcriber.update_hotwords(["Persona Beta"])
    transcriber.transcribe(pcm, pcm_format, 0)
    transcriber.transcribe_verification(pcm, pcm_format, 0)

    assert "--prompt" in calls[0]
    assert "Persona Beta" in calls[0][calls[0].index("--prompt") + 1]
    assert "Persona Alfa" not in calls[0][calls[0].index("--prompt") + 1]
    assert "--prompt" not in calls[1]
