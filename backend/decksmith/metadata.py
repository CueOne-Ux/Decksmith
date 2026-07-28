from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AudioMetadata:
    title: str
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    genre: str = ""
    year: str = ""
    comment: str = ""
    duration_seconds: float | None = None
    bpm: float | None = None
    musical_key: str = ""
    sample_rate: int | None = None
    channels: int | None = None
    bitrate: int | None = None
    status: str = "filename"
    error: str | None = None


def _first(tags: Any, *names: str) -> str:
    if tags is None:
        return ""
    for name in names:
        value = tags.get(name)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        text = str(value).strip()
        if text:
            return text
    return ""


def read_metadata(path: Path) -> AudioMetadata:
    fallback = AudioMetadata(title=path.stem)
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return fallback

    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return AudioMetadata(title=path.stem, status="unsupported")

        info = getattr(audio, "info", None)
        bpm_text = _first(audio.tags, "bpm", "tbpm")
        try:
            bpm = float(bpm_text) if bpm_text else None
        except ValueError:
            bpm = None

        return AudioMetadata(
            title=_first(audio.tags, "title") or path.stem,
            artist=_first(audio.tags, "artist"),
            album=_first(audio.tags, "album"),
            album_artist=_first(audio.tags, "albumartist", "album artist"),
            genre=_first(audio.tags, "genre"),
            year=_first(audio.tags, "date", "year"),
            comment=_first(audio.tags, "comment", "description"),
            duration_seconds=getattr(info, "length", None),
            bpm=bpm,
            musical_key=_first(audio.tags, "initialkey", "key"),
            sample_rate=getattr(info, "sample_rate", None),
            channels=getattr(info, "channels", None),
            bitrate=getattr(info, "bitrate", None),
            status="complete",
        )
    except Exception as error:
        return AudioMetadata(
            title=path.stem,
            status="error",
            error=f"{type(error).__name__}: {error}",
        )
