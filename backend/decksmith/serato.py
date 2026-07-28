from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .database import Database


@dataclass(frozen=True)
class Record:
    tag: str
    value: bytes


@dataclass(frozen=True)
class ParsedCrate:
    name: str
    hierarchy: list[str]
    source_path: Path
    tracks: list[Path]


def decode_records(data: bytes) -> list[Record]:
    records: list[Record] = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 8:
            raise ValueError(f"Truncated Serato record header at byte {offset}")
        try:
            tag = data[offset:offset + 4].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError(f"Invalid Serato tag at byte {offset}") from error
        length = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        end = offset + 8 + length
        if end > len(data):
            raise ValueError(f"Serato record {tag!r} extends beyond the file")
        records.append(Record(tag, data[offset + 8:end]))
        offset = end
    return records


def _text(value: bytes) -> str:
    return value.decode("utf-16-be").rstrip("\x00")


def _resolve_track_path(value: str, serato_dir: Path) -> Path:
    normalized = value.replace("\\", "/").lstrip("/")
    first = normalized.split("/", 1)[0]
    if first in {"Users", "Volumes", "home", "mnt", "media"}:
        return Path("/", normalized)
    return serato_dir.parent / normalized


def parse_crate(path: str | Path, serato_dir: str | Path) -> ParsedCrate:
    crate_path = Path(path).resolve(strict=True)
    root = Path(serato_dir).resolve(strict=True)
    records = decode_records(crate_path.read_bytes())
    tracks: list[Path] = []
    for record in records:
        if record.tag != "otrk":
            continue
        for child in decode_records(record.value):
            if child.tag == "ptrk":
                tracks.append(_resolve_track_path(_text(child.value), root))
                break
    hierarchy = crate_path.stem.split("%%")
    return ParsedCrate(hierarchy[-1], hierarchy, crate_path, tracks)


def discover_serato_libraries(home: str | Path | None = None) -> list[Path]:
    home_path = Path(home).expanduser() if home is not None else Path.home()
    candidates = [home_path / "Music" / "_Serato_", home_path / "Documents" / "_Serato_", home_path / "_Serato_"]
    volumes = Path("/Volumes")
    if volumes.is_dir():
        candidates.extend(volumes.glob("*/_Serato_"))
    return sorted({path.resolve() for path in candidates if path.is_dir()})


def iter_crate_files(serato_dir: Path) -> Iterable[Path]:
    subcrates = serato_dir / "Subcrates"
    if not subcrates.is_dir():
        return []
    return sorted(
        (path for path in subcrates.iterdir() if path.is_file() and path.suffix.lower() == ".crate"),
        key=lambda path: path.name.casefold(),
    )


def sync_serato_crates(database: Database, libraries: list[Path] | None = None) -> dict[str, int]:
    database.initialize()
    roots = libraries if libraries is not None else discover_serato_libraries()
    result = {"libraries": len(roots), "crates": 0, "tracks": 0, "errors": 0}
    with database.connect() as connection:
        for serato_dir in roots:
            connection.execute(
                """
                INSERT INTO serato_libraries(path, last_read_at) VALUES (?, CURRENT_TIMESTAMP)
                ON CONFLICT(path) DO UPDATE SET last_read_at = CURRENT_TIMESTAMP
                """,
                (str(serato_dir),),
            )
            library_id = connection.execute(
                "SELECT id FROM serato_libraries WHERE path = ?", (str(serato_dir),)
            ).fetchone()[0]
            seen_sources: set[str] = set()
            for crate_file in iter_crate_files(serato_dir):
                try:
                    crate = parse_crate(crate_file, serato_dir)
                    modified_ns = crate_file.stat().st_mtime_ns
                except (OSError, ValueError, UnicodeError):
                    result["errors"] += 1
                    continue
                source = str(crate.source_path)
                seen_sources.add(source)
                connection.execute(
                    """
                    INSERT INTO crates(
                        library_id, name, hierarchy_path, source_path, source_modified_ns, track_count
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_path) DO UPDATE SET
                        library_id = excluded.library_id,
                        name = excluded.name,
                        hierarchy_path = excluded.hierarchy_path,
                        source_modified_ns = excluded.source_modified_ns,
                        track_count = excluded.track_count,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (library_id, crate.name, "%%".join(crate.hierarchy), source, modified_ns, len(crate.tracks)),
                )
                crate_id = connection.execute("SELECT id FROM crates WHERE source_path = ?", (source,)).fetchone()[0]
                connection.execute("DELETE FROM crate_tracks WHERE crate_id = ?", (crate_id,))
                for position, track_path in enumerate(crate.tracks):
                    track_id = connection.execute("SELECT id FROM tracks WHERE path = ?", (str(track_path),)).fetchone()
                    connection.execute(
                        "INSERT INTO crate_tracks(crate_id, position, path, track_id) VALUES (?, ?, ?, ?)",
                        (crate_id, position, str(track_path), track_id[0] if track_id else None),
                    )
                result["crates"] += 1
                result["tracks"] += len(crate.tracks)
            if seen_sources:
                placeholders = ",".join("?" for _ in seen_sources)
                connection.execute(
                    f"DELETE FROM crates WHERE library_id = ? AND source_path NOT IN ({placeholders})",
                    (library_id, *sorted(seen_sources)),
                )
            else:
                connection.execute("DELETE FROM crates WHERE library_id = ?", (library_id,))
    return result


def list_crates(database: Database) -> list[dict[str, Any]]:
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT crates.id, crates.name, crates.hierarchy_path, crates.track_count,
                   serato_libraries.path AS library_path,
                   SUM(CASE WHEN crate_tracks.track_id IS NOT NULL THEN 1 ELSE 0 END) AS matched_count
            FROM crates
            JOIN serato_libraries ON serato_libraries.id = crates.library_id
            LEFT JOIN crate_tracks ON crate_tracks.crate_id = crates.id
            GROUP BY crates.id
            ORDER BY crates.hierarchy_path COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def crate_track_ids(database: Database, crate_id: int) -> list[int]:
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT track_id FROM crate_tracks
            WHERE crate_id = ? AND track_id IS NOT NULL ORDER BY position
            """,
            (crate_id,),
        ).fetchall()
    return [row[0] for row in rows]
