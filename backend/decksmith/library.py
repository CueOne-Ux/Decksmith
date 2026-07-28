from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from .database import Database


def list_tracks(database: Database, include_missing: bool = False) -> list[dict[str, Any]]:
    database.initialize()
    where = "" if include_missing else "WHERE tracks.missing = 0"
    with database.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT tracks.id, tracks.path, tracks.title, tracks.artist, tracks.album,
                   tracks.genre, tracks.year,
                   COALESCE(tracks.user_comment, tracks.comment) AS comment,
                   tracks.duration_seconds,
                   COALESCE(tracks.analysis_bpm, tracks.bpm) AS bpm,
                   CASE WHEN tracks.analysis_key != '' THEN tracks.analysis_key
                        ELSE tracks.musical_key END AS musical_key,
                   tracks.analysis_scale, tracks.analysis_strength, tracks.energy_score,
                   tracks.analysis_status, tracks.analysis_error,
                   tracks.last_played_at, tracks.play_count,
                   tracks.mood, tracks.updated_at,
                   tracks.metadata_status, tracks.missing, tracks.file_size, tracks.rating,
                   tracks.color_tag, tracks.discovered_at, library_roots.path AS root_path,
                   COALESCE(GROUP_CONCAT(track_tags.tag, ','), '') AS tags
            FROM tracks
            LEFT JOIN library_roots ON library_roots.id = tracks.root_id
            LEFT JOIN track_tags ON track_tags.track_id = tracks.id
            {where}
            GROUP BY tracks.id
            ORDER BY tracks.artist COLLATE NOCASE, tracks.title COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_roots(database: Database) -> list[dict[str, Any]]:
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT library_roots.id, library_roots.path, library_roots.last_scanned_at,
                   COUNT(tracks.id) AS track_count,
                   COALESCE(SUM(CASE WHEN tracks.missing = 1 THEN 1 ELSE 0 END), 0) AS missing_count
            FROM library_roots
            LEFT JOIN tracks ON tracks.root_id = library_roots.id
            WHERE library_roots.enabled = 1
            GROUP BY library_roots.id
            ORDER BY library_roots.path COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def library_issues(database: Database) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        missing = connection.execute(
            """
            SELECT id, path, title, artist, 'missing' AS issue
            FROM tracks WHERE missing = 1 ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE
            """
        ).fetchall()
        metadata_errors = connection.execute(
            """
            SELECT id, path, title, artist, metadata_error, 'metadata' AS issue
            FROM tracks WHERE metadata_status = 'error'
            ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE
            """
        ).fetchall()
    return {
        "missing": [dict(row) for row in missing],
        "metadata_errors": [dict(row) for row in metadata_errors],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicates(database: Database) -> list[dict[str, Any]]:
    database.initialize()
    with database.connect() as connection:
        candidates = connection.execute(
            """
            SELECT id, path, title, artist, file_size, content_hash
            FROM tracks
            WHERE missing = 0 AND file_size IN (
                SELECT file_size FROM tracks WHERE missing = 0
                GROUP BY file_size HAVING COUNT(*) > 1
            )
            ORDER BY file_size, path
            """
        ).fetchall()

        hashed: list[dict[str, Any]] = []
        for row in candidates:
            item = dict(row)
            path = Path(item["path"])
            try:
                content_hash = item["content_hash"] or _sha256(path)
            except OSError:
                continue
            if not item["content_hash"]:
                connection.execute(
                    "UPDATE tracks SET content_hash = ? WHERE id = ?", (content_hash, item["id"])
                )
            item["content_hash"] = content_hash
            hashed.append(item)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in hashed:
        groups[item["content_hash"]].append(item)
    return [
        {"hash": content_hash, "file_size": items[0]["file_size"], "tracks": items}
        for content_hash, items in groups.items()
        if len(items) > 1
    ]


def update_track(
    database: Database,
    track_id: int,
    rating: int | None = None,
    tags: list[str] | None = None,
    color_tag: str | None = None,
    mood: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    update_tracks(
        database, [track_id], rating, tags, color_tag, mood, comment, tag_mode="replace"
    )
    return next(track for track in list_tracks(database, include_missing=True) if track["id"] == track_id)


def update_tracks(
    database: Database,
    track_ids: list[int],
    rating: int | None = None,
    tags: list[str] | None = None,
    color_tag: str | None = None,
    mood: str | None = None,
    comment: str | None = None,
    tag_mode: str = "add",
) -> int:
    database.initialize()
    if rating is not None and not 0 <= rating <= 5:
        raise ValueError("Rating must be between 0 and 5")
    if tag_mode not in {"add", "replace"}:
        raise ValueError("Tag mode must be add or replace")
    if mood is not None and len(mood.strip()) > 80:
        raise ValueError("Mood must contain at most 80 characters")
    if comment is not None and len(comment) > 4000:
        raise ValueError("Comment must contain at most 4000 characters")
    ids = list(dict.fromkeys(track_ids))
    if not ids:
        raise ValueError("Choose at least one track")
    clean_tags = None if tags is None else sorted({tag.strip() for tag in tags if tag.strip()}, key=str.casefold)
    with database.connect() as connection:
        placeholders = ",".join("?" for _ in ids)
        found = connection.execute(
            f"SELECT COUNT(*) FROM tracks WHERE id IN ({placeholders})", ids
        ).fetchone()[0]
        if found != len(ids):
            raise ValueError("One or more selected tracks do not exist")
        if rating is not None:
            connection.execute(
                f"UPDATE tracks SET rating = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                [rating, *ids],
            )
        if color_tag is not None:
            connection.execute(
                f"UPDATE tracks SET color_tag = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                [color_tag.strip(), *ids],
            )
        if mood is not None:
            connection.execute(
                f"UPDATE tracks SET mood = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                [mood.strip(), *ids],
            )
        if comment is not None:
            connection.execute(
                f"UPDATE tracks SET user_comment = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                [comment.strip(), *ids],
            )
        if clean_tags is not None:
            if tag_mode == "replace":
                connection.execute(
                    f"DELETE FROM track_tags WHERE track_id IN ({placeholders})", ids
                )
            connection.executemany(
                "INSERT OR IGNORE INTO track_tags(track_id, tag) VALUES (?, ?)",
                ((track_id, tag) for track_id in ids for tag in clean_tags),
            )
    return len(ids)


def record_playback(database: Database, track_id: int) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        row = connection.execute(
            """
            UPDATE tracks SET last_played_at = CURRENT_TIMESTAMP,
                play_count = play_count + 1
            WHERE id = ? RETURNING last_played_at, play_count
            """,
            (track_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Track {track_id} does not exist")
    return dict(row)
