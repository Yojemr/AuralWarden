from __future__ import annotations

from auralwarden.cli import build_parser


def test_monitor_parses_manual_speaker_names() -> None:
    args = build_parser().parse_args(
        ["monitor", "audio.wav", "--speaker-name", "Speaker 1=Ana"]
    )
    assert dict(args.speaker_name) == {"Speaker 1": "Ana"}
    assert args.window == 6.0
    assert args.overlap == 2.0


def test_monitor_enables_video_clips_explicitly() -> None:
    args = build_parser().parse_args(["monitor", "video.mp4", "--video-clips"])
    assert args.video_clips is True
