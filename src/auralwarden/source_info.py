from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from auralwarden import __version__

@dataclass(frozen=True, slots=True)
class SourceInfo:
    title: str
    author: str = ""


def fallback_source_info(source: str) -> SourceInfo:
    value = source.strip()
    if value.startswith("demo://"):
        return SourceInfo("Demostración de AuralWarden")
    local = Path(value).expanduser()
    try:
        if local.is_file():
            return SourceInfo(local.name)
    except OSError:
        # Some URL-like or malformed values are not valid Windows paths.
        pass
    parsed = urlparse(value)
    host = (parsed.hostname or "").removeprefix("www.")
    if host in {"youtube.com", "m.youtube.com", "youtu.be"}:
        return SourceInfo("Directo de YouTube")
    if host in {"twitch.tv", "m.twitch.tv"}:
        return SourceInfo("Directo de Twitch")
    if host in {"kick.com", "www.kick.com"}:
        return SourceInfo("Directo de Kick")
    if Path(parsed.path).suffix.casefold() in {
        ".aac",
        ".m3u",
        ".m3u8",
        ".mp3",
        ".ogg",
        ".opus",
        ".pls",
    }:
        return SourceInfo("Transmisión de audio", host)
    if host:
        return SourceInfo(host)
    return SourceInfo("Transmisión sin identificar")


def resolve_source_info(
    source: str,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = 8.0,
) -> SourceInfo:
    fallback = fallback_source_info(source)
    parsed = urlparse(source.strip())
    host = (parsed.hostname or "").removeprefix("www.")
    if host not in {"youtube.com", "m.youtube.com", "youtu.be"}:
        try:
            from streamlink import Streamlink

            plugin = Streamlink().resolve_url(source.strip())
            metadata = plugin.get_metadata()
            title = " ".join(str(metadata.get("title") or "").split())
            author = " ".join(str(metadata.get("author") or "").split())
            return SourceInfo(title or fallback.title, author or fallback.author)
        except Exception:
            return fallback

    endpoint = "https://www.youtube.com/oembed?" + urlencode(
        {"url": source.strip(), "format": "json"}
    )
    request = Request(endpoint, headers={"User-Agent": f"AuralWarden/{__version__}"})
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return fallback
    title = " ".join(str(payload.get("title") or "").split())
    author = " ".join(str(payload.get("author_name") or "").split())
    return SourceInfo(title or fallback.title, author)
