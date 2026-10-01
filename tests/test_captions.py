import json
import sys
import types
from pathlib import Path
from threading import Event

from auralwarden.backends.demo import create_demo_transcriber
from auralwarden.captions import (
    CaptionCue,
    CaptionTrack,
    YoutubeCaptionSource,
    is_youtube_source,
    parse_json3_captions,
    parse_m3u8_segments,
    parse_m3u8_target_duration,
    parse_webvtt_captions,
    resolve_youtube_caption_track,
)
from auralwarden.clips import AudioClipManager
from auralwarden.engine import MonitoringEngine
from auralwarden.events import EventBus
from auralwarden.models import AppSettings, EventKind, Hotword


def test_parse_json3_captions_joins_segments_and_keeps_time() -> None:
    payload = json.dumps(
        {
            "events": [
                {
                    "tStartMs": 1250,
                    "dDurationMs": 2000,
                    "segs": [{"utf8": "palabra "}, {"utf8": "clave"}],
                },
                {"tStartMs": 4000, "segs": [{"utf8": "\n"}]},
            ]
        }
    )

    cues = parse_json3_captions(payload, "es")

    assert cues == [CaptionCue("palabra clave", 1.25, 3.25, "es")]
    assert is_youtube_source("https://youtu.be/demo")
    assert not is_youtube_source("https://twitch.tv/demo")


def test_parse_segmented_webvtt_uses_mpegts_as_live_timeline() -> None:
    payload = """WEBVTT
X-TIMESTAMP-MAP=LOCAL:00:00.000,MPEGTS:79656000

00:00:00.000 --> 00:00:04.500 align:start position:0%
la palabra <c>clave</c>
"""

    cues = parse_webvtt_captions(payload, "en")

    assert cues == [CaptionCue("la palabra clave", 885.0666666666667, 889.5666666666667, "en")]


def test_parse_m3u8_assigns_media_sequences_and_resolves_relative_urls() -> None:
    playlist = """#EXTM3U
#EXT-X-MEDIA-SEQUENCE:41
#EXTINF:5.0,
captions/41.vtt
#EXTINF:5.0,
https://captions.test/42.vtt
"""

    assert parse_m3u8_segments(playlist, "https://captions.test/live/index.m3u8") == [
        (41, "https://captions.test/live/captions/41.vtt"),
        (42, "https://captions.test/42.vtt"),
    ]
    assert parse_m3u8_target_duration("#EXTM3U\n#EXT-X-TARGETDURATION:5\n") == 5.0


def test_caption_source_reads_only_new_live_vtt_segments() -> None:
    stop = Event()
    playlist_calls = 0

    def resolver(_source: str, _language: str):
        return CaptionTrack(
            "https://captions.test/live.m3u8",
            "en",
            True,
            "vtt",
            "m3u8_native",
        )

    def fetcher(url: str) -> bytes:
        nonlocal playlist_calls
        if url.endswith("live.m3u8"):
            playlist_calls += 1
            last = 2 if playlist_calls == 1 else 3
            return (
                "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:1\n"
                + "".join(f"#EXTINF:5.0,\n{sequence}.vtt\n" for sequence in range(1, last + 1))
            ).encode()
        sequence = int(url.rsplit("/", 1)[-1].split(".")[0])
        if sequence == 3:
            stop.set()
        return f"""WEBVTT
X-TIMESTAMP-MAP=LOCAL:00:00.000,MPEGTS:{sequence * 450000}

00:00:00.000 --> 00:00:04.500
segmento {sequence}
""".encode()

    source = YoutubeCaptionSource(
        "https://youtube.com/watch?v=test",
        poll_interval_seconds=0.25,
        resolver=resolver,
        fetcher=fetcher,
    )

    cues = list(source.cues(stop))

    assert [cue.text for cue in cues] == ["segmento 3"]


def test_resolver_accepts_single_mislabeled_automatic_live_track(monkeypatch) -> None:
    class FakeYoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _source, download=False):
            assert download is False
            return {
                "subtitles": {"live_chat": [{"ext": "json", "url": "chat"}]},
                "automatic_captions": {
                    "en": [
                        {
                            "ext": "vtt",
                            "protocol": "m3u8_native",
                            "url": "https://captions.test/live.m3u8",
                        }
                    ]
                },
            }

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    track = resolve_youtube_caption_track("https://youtube.com/watch?v=test", "es")

    assert track == CaptionTrack(
        "https://captions.test/live.m3u8", "en", True, "vtt", "m3u8_native"
    )


def test_resolver_prefers_requested_language_across_caption_groups(monkeypatch) -> None:
    class FakeYoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _source, download=False):
            return {
                "subtitles": {
                    "fr": [{"ext": "json3", "url": "https://captions.test/fr"}]
                },
                "automatic_captions": {
                    "es": [{"ext": "json3", "url": "https://captions.test/es"}]
                },
            }

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYoutubeDL))

    track = resolve_youtube_caption_track("https://youtube.com/watch?v=test", "es")

    assert track == CaptionTrack("https://captions.test/es", "es", True, "json3", "")


def test_caption_detection_is_fused_without_adding_visible_transcript(tmp_path: Path) -> None:
    settings = AppSettings(
        hotwords=[Hotword("palabra clave")],
        clip_pre_seconds=0,
        clip_post_seconds=0,
        audio_buffer_seconds=30,
        save_event_audio_clips=False,
    )
    bus = EventBus()
    observed = []
    bus.subscribe(observed.append)
    engine = MonitoringEngine(
        source=object(),
        transcriber=create_demo_transcriber(),
        settings=settings,
        session_root=tmp_path,
        event_bus=bus,
    )
    engine.session = __import__("auralwarden.session", fromlist=["SessionWorkspace"]).SessionWorkspace(
        tmp_path, "https://youtube.com/watch?v=test"
    )
    manager = AudioClipManager(tmp_path / "clips", engine.ring, 0, 0)
    engine._caption_queue.put(CaptionCue("una palabra", 1, 1.5, "es"))
    engine._caption_queue.put(CaptionCue("clave importante", 1.5, 2, "es"))

    engine._drain_caption_cues(2, manager, None)

    detections = [event for event in observed if event.kind == EventKind.HOTWORD]
    caption_events = [
        event
        for event in observed
        if event.kind == EventKind.INFO
        and event.payload.get("code") == "caption_cue"
    ]
    assert len(detections) == 1
    assert [event.payload["text"] for event in caption_events] == [
        "una palabra",
        "clave importante",
    ]
    assert detections[0].payload["source"] == "youtube_captions"
    assert engine.transcript.entries == []


def test_caption_source_keeps_retrying_until_a_late_track_appears() -> None:
    stop = Event()
    statuses = []
    resolver_calls = 0

    def resolver(_source: str, _language: str):
        nonlocal resolver_calls
        resolver_calls += 1
        if resolver_calls == 1:
            return None
        return CaptionTrack("https://captions.test/late", "es", True)

    def fetcher(_url: str) -> bytes:
        stop.set()
        return b'{"events": []}'

    source = YoutubeCaptionSource(
        "https://youtube.com/watch?v=test",
        poll_interval_seconds=0.25,
        retry_initial_seconds=0.25,
        retry_max_seconds=0.25,
        resolver=resolver,
        fetcher=fetcher,
        status_callback=lambda code, message, details: statuses.append(
            (code, message, details)
        ),
    )

    assert list(source.cues(stop)) == []
    assert resolver_calls == 2
    assert [item[0] for item in statuses] == [
        "caption_track_waiting",
        "caption_track_ready",
    ]
    assert statuses[0][2]["delay_seconds"] == 0.25


def test_caption_source_replaces_an_expired_track_without_stopping() -> None:
    stop = Event()
    statuses = []
    resolver_calls = 0
    old_fetches = 0

    def resolver(_source: str, _language: str):
        nonlocal resolver_calls
        resolver_calls += 1
        url = "https://captions.test/old" if resolver_calls == 1 else "https://captions.test/new"
        return CaptionTrack(url, "es", True)

    def fetcher(url: str) -> bytes:
        nonlocal old_fetches
        if url.endswith("/old"):
            old_fetches += 1
            if old_fetches > 1:
                raise OSError("expired")
            text = "anterior"
        else:
            text = "palabra clave"
            stop.set()
        return json.dumps(
            {
                "events": [
                    {
                        "tStartMs": 3_000 if text == "anterior" else 4_000,
                        "dDurationMs": 1_000,
                        "segs": [{"utf8": text}],
                    }
                ]
            }
        ).encode("utf-8")

    source = YoutubeCaptionSource(
        "https://youtube.com/watch?v=test",
        poll_interval_seconds=0.25,
        retry_initial_seconds=0.25,
        retry_max_seconds=0.25,
        resolver=resolver,
        fetcher=fetcher,
        status_callback=lambda code, message, details: statuses.append(
            (code, message, details)
        ),
    )

    cues = list(source.cues(stop))

    assert [cue.text for cue in cues] == ["palabra clave"]
    assert resolver_calls == 2
    assert "caption_track_retrying" in [item[0] for item in statuses]
    assert [item[0] for item in statuses].count("caption_track_ready") == 2


def test_caption_source_reports_unavailable_but_continues_scheduled_retries() -> None:
    stop = Event()
    statuses = []
    resolver_calls = 0

    def resolver(_source: str, _language: str):
        nonlocal resolver_calls
        resolver_calls += 1
        if resolver_calls >= 3:
            stop.set()
        return None

    source = YoutubeCaptionSource(
        "https://youtube.com/watch?v=test",
        poll_interval_seconds=0.25,
        retry_initial_seconds=0.25,
        retry_max_seconds=0.25,
        unavailable_after_attempts=3,
        resolver=resolver,
        status_callback=lambda code, message, details: statuses.append(
            (code, message, details)
        ),
    )

    assert list(source.cues(stop)) == []
    assert [item[0] for item in statuses] == [
        "caption_track_waiting",
        "caption_track_retrying",
        "caption_monitor_unavailable",
    ]
    assert statuses[-1][2]["retrying"] is True
