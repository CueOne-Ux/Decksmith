from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from .database import Database
from .metadata import read_metadata


AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a", ".aac", ".ogg", ".opus",
})


@dataclass
class ScanResult:
    root: str
    files_seen: int = 0
    tracks_added: int = 0
    tracks_updated: int = 0
    files_skipped: int = 0
    errors: int = 0
    cancelled: bool = False


ProgressCallback = Callable[[ScanResult, Path], None]
CancellationCallback = Callable[[], bool]


def discover_audio_files(root: Path) -> Iterable[Path]:
    for directory, folder_names, filenames in os.walk(root, followlinks=False):
        folder_names[:] = sorted(name for name in folder_names if not name.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            path = Path(directory, filename)
            if path.suffix.lower() in AUDIO_EXTENSIONS and not path.is_symlink():
                yield path


def scan_library(
    database: Database,
    root: str | Path,
    progress: ProgressCallback | None = None,
    should_cancel: CancellationCallback | None = None,
) -> ScanResult:
    root_path = Path(root).expanduser().resolve(strict=True)
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    database.initialize()
    result = ScanResult(root=str(root_path))

    with database.connect() as connection:
        connection.execute(
            "INSERT INTO library_roots(path) VALUES (?) ON CONFLICT(path) DO UPDATE SET enabled = 1",
            (str(root_path),),
        )
        root_id = connection.execute(
            "SELECT id FROM library_roots WHERE path = ?", (str(root_path),)
        ).fetchone()[0]
        scan_id = connection.execute(
            "INSERT INTO scan_runs(root_id) VALUES (?) RETURNING id", (root_id,)
        ).fetchone()[0]

        for path in discover_audio_files(root_path):
            if should_cancel and should_cancel():
                result.cancelled = True
                break
            result.files_seen += 1
            try:
                stat = path.stat()
                existing = connection.execute(
                    "SELECT id, file_size, modified_ns FROM tracks WHERE path = ?", (str(path),)
                ).fetchone()

                if existing and existing["file_size"] == stat.st_size and existing["modified_ns"] == stat.st_mtime_ns:
                    connection.execute(
                        "UPDATE tracks SET missing = 0, last_seen_scan_id = ? WHERE id = ?",
                        (scan_id, existing["id"]),
                    )
                    result.files_skipped += 1
                else:
                    metadata = read_metadata(path)
                    values = asdict(metadata)
                    connection.execute(
                        """
                        INSERT INTO tracks (
                            path, root_id, filename, extension, file_size, modified_ns,
                            title, artist, album, album_artist, genre, year, comment,
                            duration_seconds, bpm, musical_key, sample_rate, channels,
                            bitrate, metadata_status, metadata_error, missing, last_seen_scan_id
                        ) VALUES (
                            :path, :root_id, :filename, :extension, :file_size, :modified_ns,
                            :title, :artist, :album, :album_artist, :genre, :year, :comment,
                            :duration_seconds, :bpm, :musical_key, :sample_rate, :channels,
                            :bitrate, :status, :error, 0, :scan_id
                        )
                        ON CONFLICT(path) DO UPDATE SET
                            root_id = excluded.root_id,
                            filename = excluded.filename,
                            extension = excluded.extension,
                            file_size = excluded.file_size,
                            modified_ns = excluded.modified_ns,
                            title = excluded.title,
                            artist = excluded.artist,
                            album = excluded.album,
                            album_artist = excluded.album_artist,
                            genre = excluded.genre,
                            year = excluded.year,
                            comment = excluded.comment,
                            duration_seconds = excluded.duration_seconds,
                            bpm = excluded.bpm,
                            musical_key = excluded.musical_key,
                            sample_rate = excluded.sample_rate,
                            channels = excluded.channels,
                            bitrate = excluded.bitrate,
                            metadata_status = excluded.metadata_status,
                            metadata_error = excluded.metadata_error,
                            content_hash = NULL,
                            analysis_bpm = NULL,
                            analysis_key = '',
                            analysis_scale = '',
                            analysis_strength = NULL,
                            energy_score = NULL,
                            analysis_status = 'pending',
                            analysis_error = NULL,
                            analysis_modified_ns = NULL,
                            missing = 0,
                            last_seen_scan_id = excluded.last_seen_scan_id,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        {
                            **values,
                            "path": str(path),
                            "root_id": root_id,
                            "filename": path.name,
                            "extension": path.suffix.lower(),
                            "file_size": stat.st_size,
                            "modified_ns": stat.st_mtime_ns,
                            "scan_id": scan_id,
                        },
                    )
                    if existing:
                        result.tracks_updated += 1
                    else:
                        result.tracks_added += 1
            except (OSError, ValueError):
                result.errors += 1

            if progress:
                progress(result, path)

        if not result.cancelled:
            connection.execute(
                """
                UPDATE tracks SET missing = 1
                WHERE root_id = ? AND (last_seen_scan_id IS NULL OR last_seen_scan_id != ?)
                """,
                (root_id, scan_id),
            )
            connection.execute(
                "UPDATE library_roots SET last_scanned_at = CURRENT_TIMESTAMP WHERE id = ?",
                (root_id,),
            )
        connection.execute(
            """
            UPDATE scan_runs SET
                completed_at = CURRENT_TIMESTAMP, status = ?, files_seen = ?,
                tracks_added = ?, tracks_updated = ?, files_skipped = ?, errors = ?
            WHERE id = ?
            """,
            (
                "cancelled" if result.cancelled else "completed",
                result.files_seen, result.tracks_added, result.tracks_updated,
                result.files_skipped, result.errors, scan_id,
            ),
        )

    return result
