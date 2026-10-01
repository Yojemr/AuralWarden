from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from threading import Event

from auralwarden.audio import PcmFormat
from auralwarden.capture import CaptureConfig, FfmpegPcmCapture
from auralwarden.hotwords import normalize_text
from auralwarden.transcribers import FasterWhisperConfig, FasterWhisperTranscriber


def gpu_memory_mb() -> int | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None
    result = subprocess.run(
        [
            executable,
            "--query-gpu=memory.used",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return int(result.stdout.strip().splitlines()[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--hotword", action="append", default=[])
    parser.add_argument("--expect", action="append", default=[])
    args = parser.parse_args()

    pcm_format = PcmFormat()
    capture = FfmpegPcmCapture(CaptureConfig(str(args.audio), pcm_format=pcm_format))
    chunks = list(capture.chunks(Event()))
    pcm = b"".join(chunk.data for chunk in chunks)
    duration = pcm_format.seconds_for_bytes(len(pcm))

    transcriber = FasterWhisperTranscriber(
        FasterWhisperConfig(
            model_name=str(args.model.resolve()),
            device="cuda",
            compute_type="float16",
            language=args.language,
            hotwords=args.hotword,
            local_files_only=True,
        )
    )
    memory_before = gpu_memory_mb()
    started = time.perf_counter()
    entries = transcriber.transcribe(pcm, pcm_format, 0.0)
    elapsed = time.perf_counter() - started
    memory_after = gpu_memory_mb()
    text = " ".join(entry.text for entry in entries).strip()
    normalized = normalize_text(text)
    missing = [expected for expected in args.expect if normalize_text(expected) not in normalized]
    payload = {
        "model": str(args.model.resolve()),
        "device": "cuda",
        "compute_type": "float16",
        "audio_seconds": round(duration, 3),
        "elapsed_seconds": round(elapsed, 3),
        "realtime_factor": round(elapsed / duration, 3) if duration else None,
        "gpu_memory_before_mb": memory_before,
        "gpu_memory_after_mb": memory_after,
        "segments": len(entries),
        "text": text,
        "missing_expectations": missing,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if entries and not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
