from __future__ import annotations

from pathlib import Path
from typing import Any

from .database import Database


MAX_ARTWORK_BYTES = 20 * 1024 * 1024


def _image_extension(data: bytes, mime: str = "") -> str | None:
    normalized = mime.casefold()
    if data.startswith(b"\xff\xd8\xff") or "jpeg" in normalized or "jpg" in normalized:
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n") or "png" in normalized:
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")) or "gif" in normalized:
        return ".gif"
    if (data.startswith(b"RIFF") and data[8:12] == b"WEBP") or "webp" in normalized:
        return ".webp"
    return None


def _embedded_artwork(audio: Any) -> tuple[bytes, str] | None:
    pictures = getattr(audio, "pictures", None)
    if pictures:
        picture = pictures[0]
        return bytes(picture.data), str(getattr(picture, "mime", ""))

    tags = getattr(audio, "tags", None)
    if tags is None:
        return None

    covers = tags.get("covr") if hasattr(tags, "get") else None
    if covers:
        cover = covers[0]
        return bytes(cover), str(getattr(cover, "imageformat", ""))

    values = tags.values() if hasattr(tags, "values") else []
    for value in values:
        data = getattr(value, "data", None)
        if data is not None and value.__class__.__name__.startswith("APIC"):
            return bytes(data), str(getattr(value, "mime", ""))
    return None


def extract_artwork(database: Database, track_id: int, cache_dir: str | Path) -> Path | None:
    database.initialize()
    cache = Path(cache_dir).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT path, modified_ns, missing FROM tracks WHERE id = ?", (track_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"Track {track_id} does not exist")
    if row["missing"]:
        raise FileNotFoundError(row["path"])

    stem = f"{track_id}-{row['modified_ns']}"
    cached = next((path for path in cache.glob(f"{stem}.*") if path.is_file()), None)
    if cached is not None:
        return cached

    try:
        from mutagen import File as MutagenFile
    except ImportError as error:
        raise RuntimeError("Mutagen is not installed in Decksmith's Python environment") from error

    try:
        audio = MutagenFile(row["path"], easy=False)
    except Exception:
        if Path(row["path"]).suffix.casefold() != ".mp3":
            return None
        from mutagen.id3 import ID3

        audio = type("TaggedAudio", (), {"tags": ID3(row["path"])})()
    if audio is None:
        return None
    embedded = _embedded_artwork(audio)
    if embedded is None:
        return None
    data, mime = embedded
    if not data or len(data) > MAX_ARTWORK_BYTES:
        return None
    extension = _image_extension(data, mime)
    if extension is None:
        return None

    for stale in cache.glob(f"{track_id}-*.*"):
        stale.unlink(missing_ok=True)
    destination = cache / f"{stem}{extension}"
    temporary = destination.with_suffix(f"{extension}.tmp")
    temporary.write_bytes(data)
    temporary.replace(destination)
    return destination
