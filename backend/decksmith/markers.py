from __future__ import annotations

import base64
import binascii
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mutagen import MutagenError
from mutagen.id3 import GEOB, ID3, ID3NoHeaderError

from .database import Database


MARKERS2_DESCRIPTION = "Serato Markers2"
MAX_RECORD_SIZE = 1_048_576
SQLITE_BATCH_SIZE = 500


@dataclass(frozen=True)
class CuePoint:
    slot: int
    position_seconds: float
    name: str
    color: str


@dataclass(frozen=True)
class SavedLoop:
    slot: int
    start_seconds: float
    end_seconds: float
    color: str


@dataclass(frozen=True)
class MarkerPayload:
    cues: list[CuePoint]
    loops: list[SavedLoop]
    unsupported_records: list[str]

    @property
    def loop_record_count(self) -> int:
        return len(self.loops)


@dataclass(frozen=True)
class MarkerReadResult:
    status: str
    source_format: str | None
    cues: list[CuePoint]
    loops: list[SavedLoop]
    unsupported_records: list[str]
    error: str | None = None

    @property
    def loop_record_count(self) -> int:
        return len(self.loops)


def _decode_outer_payload(data: bytes) -> bytes:
    if len(data) < 4 or data[:2] != b"\x01\x01":
        raise ValueError("Unsupported Serato Markers2 container version")
    encoded = b"".join(data[2:].split(b"\0", 1)[0].split())
    if not encoded:
        raise ValueError("Serato Markers2 container is empty")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Serato Markers2 container has invalid base64 data") from error
    if len(decoded) < 2 or decoded[:2] != b"\x01\x01":
        raise ValueError("Unsupported Serato Markers2 payload version")
    return decoded


def _read_records(data: bytes) -> list[tuple[str, bytes]]:
    records: list[tuple[str, bytes]] = []
    offset = 2
    while offset < len(data):
        if not any(data[offset:]):
            break
        try:
            tag_end = data.index(0, offset)
        except ValueError as error:
            raise ValueError(f"Unterminated Serato marker tag at byte {offset}") from error
        if tag_end == offset:
            raise ValueError(f"Empty Serato marker tag at byte {offset}")
        try:
            tag = data[offset:tag_end].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError(f"Invalid Serato marker tag at byte {offset}") from error
        length_start = tag_end + 1
        if len(data) - length_start < 4:
            raise ValueError(f"Truncated Serato marker length for {tag}")
        size = struct.unpack(">I", data[length_start:length_start + 4])[0]
        if size > MAX_RECORD_SIZE:
            raise ValueError(f"Serato marker record {tag} is unreasonably large")
        payload_start = length_start + 4
        payload_end = payload_start + size
        if payload_end > len(data):
            raise ValueError(f"Truncated Serato marker record {tag}")
        records.append((tag, data[payload_start:payload_end]))
        offset = payload_end
    return records


def _parse_cue(payload: bytes) -> CuePoint:
    if len(payload) < 13:
        raise ValueError("Serato CUE record is too short")
    if payload[0] != 0:
        raise ValueError("Unsupported Serato CUE record version")
    slot = payload[1]
    if slot > 7:
        raise ValueError(f"Serato CUE slot {slot} is outside the supported 0-7 range")
    position_ms = struct.unpack(">I", payload[2:6])[0]
    color = f"#{payload[7]:02x}{payload[8]:02x}{payload[9]:02x}"
    raw_name = payload[12:]
    if not raw_name.endswith(b"\0"):
        raise ValueError("Serato CUE name is not null terminated")
    try:
        name = raw_name[:-1].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Serato CUE name is not valid UTF-8") from error
    return CuePoint(slot, position_ms / 1000.0, name, color)


def _parse_loop(payload: bytes) -> SavedLoop:
    if len(payload) != 21:
        raise ValueError("Serato LOOP record must be exactly 21 bytes")
    if payload[0] != 0:
        raise ValueError("Unsupported Serato LOOP record version")
    slot = payload[1]
    if slot > 7:
        raise ValueError(f"Serato LOOP slot {slot} is outside the supported 0-7 range")
    start_ms, end_ms, sentinel = struct.unpack(">III", payload[2:14])
    if end_ms <= start_ms:
        raise ValueError("Serato LOOP end must be after its start")
    if sentinel != 0xFFFFFFFF:
        raise ValueError("Serato LOOP record has an unsupported sentinel value")
    if payload[14] != 0 or payload[18] != 0 or payload[20] != 0 or payload[19] not in {0, 1}:
        raise ValueError("Serato LOOP record has unsupported control flags")
    color = f"#{payload[15]:02x}{payload[16]:02x}{payload[17]:02x}"
    return SavedLoop(slot, start_ms / 1000.0, end_ms / 1000.0, color)


def decode_markers2(data: bytes) -> MarkerPayload:
    decoded = _decode_outer_payload(data)
    cues: list[CuePoint] = []
    unsupported: list[str] = []
    loops: list[SavedLoop] = []
    seen_slots: set[int] = set()
    seen_loop_slots: set[int] = set()
    for tag, payload in _read_records(decoded):
        if tag == "CUE":
            cue = _parse_cue(payload)
            if cue.slot in seen_slots:
                raise ValueError(f"Duplicate Serato CUE slot {cue.slot}")
            seen_slots.add(cue.slot)
            cues.append(cue)
        elif tag == "LOOP":
            loop = _parse_loop(payload)
            if loop.slot in seen_loop_slots:
                raise ValueError(f"Duplicate Serato LOOP slot {loop.slot}")
            seen_loop_slots.add(loop.slot)
            loops.append(loop)
        elif tag not in {"COLOR", "BPMLOCK"} and tag not in unsupported:
            unsupported.append(tag)
    return MarkerPayload(
        sorted(cues, key=lambda cue: cue.slot),
        sorted(loops, key=lambda loop: loop.slot),
        unsupported,
    )


def read_serato_markers(path: str | Path) -> MarkerReadResult:
    track_path = Path(path)
    if track_path.suffix.casefold() != ".mp3":
        return MarkerReadResult("completed", None, [], [], [])
    try:
        tags = ID3(track_path)
    except ID3NoHeaderError:
        return MarkerReadResult("completed", None, [], [], [])
    except (OSError, MutagenError) as error:
        return MarkerReadResult("failed", None, [], [], [], str(error))
    frames = [
        frame for frame in tags.getall("GEOB")
        if isinstance(frame, GEOB) and frame.desc == MARKERS2_DESCRIPTION
    ]
    if not frames:
        return MarkerReadResult("completed", None, [], [], [])
    if len(frames) > 1:
        return MarkerReadResult("failed", "serato_markers2", [], [], [], "Multiple Serato Markers2 frames were found")
    try:
        payload = decode_markers2(bytes(frames[0].data))
    except ValueError as error:
        return MarkerReadResult("failed", "serato_markers2", [], [], [], str(error))
    return MarkerReadResult(
        "completed", "serato_markers2", payload.cues,
        payload.loops, payload.unsupported_records,
    )


def scan_track_markers(database: Database, track_ids: list[int] | None = None) -> dict[str, int]:
    database.initialize()
    parameters: tuple[Any, ...] = ()
    where = "WHERE tracks.missing = 0"
    if track_ids is not None:
        if not track_ids:
            return {"total": 0, "scanned": 0, "skipped": 0, "failed": 0, "cues": 0, "loop_records": 0}
        placeholders = ",".join("?" for _ in track_ids)
        where += f" AND tracks.id IN ({placeholders})"
        parameters = tuple(track_ids)
    with database.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT tracks.id, tracks.path, tracks.modified_ns,
                   marker_scans.source_modified_ns AS scanned_modified_ns,
                   marker_scans.status AS marker_status,
                   marker_scans.cue_count AS cached_cues,
                   marker_scans.loop_record_count AS cached_loops
            FROM tracks
            LEFT JOIN marker_scans ON marker_scans.track_id = tracks.id
            {where}
            ORDER BY tracks.id
            """,
            parameters,
        ).fetchall()
    result = {"total": len(rows), "scanned": 0, "skipped": 0, "failed": 0, "cues": 0, "loop_records": 0}
    for row in rows:
        if row["scanned_modified_ns"] == row["modified_ns"] and row["marker_status"] == "completed":
            result["skipped"] += 1
            result["cues"] += int(row["cached_cues"] or 0)
            result["loop_records"] += int(row["cached_loops"] or 0)
            continue
        marker_result = read_serato_markers(row["path"])
        with database.connect() as connection:
            connection.execute("DELETE FROM cue_points WHERE track_id = ?", (row["id"],))
            connection.execute("DELETE FROM saved_loops WHERE track_id = ?", (row["id"],))
            if marker_result.status == "completed":
                for cue in marker_result.cues:
                    connection.execute(
                        """
                        INSERT INTO cue_points(
                            track_id, source, slot, name, position_seconds, color, source_modified_ns
                        ) VALUES (?, 'serato_markers2', ?, ?, ?, ?, ?)
                        """,
                        (row["id"], cue.slot, cue.name, cue.position_seconds, cue.color, row["modified_ns"]),
                    )
                for loop in marker_result.loops:
                    connection.execute(
                        """
                        INSERT INTO saved_loops(
                            track_id, source, slot, start_seconds, end_seconds,
                            color, source_modified_ns
                        ) VALUES (?, 'serato_markers2', ?, ?, ?, ?, ?)
                        """,
                        (
                            row["id"], loop.slot, loop.start_seconds,
                            loop.end_seconds, loop.color, row["modified_ns"],
                        ),
                    )
            connection.execute(
                """
                INSERT INTO marker_scans(
                    track_id, source_modified_ns, status, source_format,
                    cue_count, loop_record_count, error, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(track_id) DO UPDATE SET
                    source_modified_ns = excluded.source_modified_ns,
                    status = excluded.status,
                    source_format = excluded.source_format,
                    cue_count = excluded.cue_count,
                    loop_record_count = excluded.loop_record_count,
                    error = excluded.error,
                    scanned_at = CURRENT_TIMESTAMP
                """,
                (
                    row["id"], row["modified_ns"], marker_result.status,
                    marker_result.source_format, len(marker_result.cues),
                    marker_result.loop_record_count, marker_result.error,
                ),
            )
        result["scanned"] += 1
        result["cues"] += len(marker_result.cues)
        result["loop_records"] += marker_result.loop_record_count
        if marker_result.status == "failed":
            result["failed"] += 1
    return result


def cue_points_for_paths(database: Database, paths: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not paths:
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    with database.connect() as connection:
        for offset in range(0, len(paths), SQLITE_BATCH_SIZE):
            batch = paths[offset:offset + SQLITE_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                f"""
                SELECT tracks.path, cue_points.slot, cue_points.name,
                       cue_points.position_seconds, cue_points.color
                FROM cue_points
                JOIN tracks ON tracks.id = cue_points.track_id
                WHERE tracks.path IN ({placeholders})
                ORDER BY tracks.path, cue_points.slot
                """,
                tuple(batch),
            ).fetchall()
            for row in rows:
                result.setdefault(row["path"], []).append({
                    "slot": row["slot"], "name": row["name"],
                    "position_seconds": row["position_seconds"], "color": row["color"],
                })
    return result


def saved_loops_for_paths(database: Database, paths: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not paths:
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    with database.connect() as connection:
        for offset in range(0, len(paths), SQLITE_BATCH_SIZE):
            batch = paths[offset:offset + SQLITE_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                f"""
                SELECT tracks.path, saved_loops.slot, saved_loops.start_seconds,
                       saved_loops.end_seconds, saved_loops.color
                FROM saved_loops
                JOIN tracks ON tracks.id = saved_loops.track_id
                WHERE tracks.path IN ({placeholders})
                ORDER BY tracks.path, saved_loops.slot
                """,
                tuple(batch),
            ).fetchall()
            for row in rows:
                result.setdefault(row["path"], []).append({
                    "slot": row["slot"],
                    "start_seconds": row["start_seconds"],
                    "end_seconds": row["end_seconds"],
                    "color": row["color"],
                })
    return result


def marker_coverage(database: Database, paths: list[str]) -> dict[str, int]:
    if not paths:
        return {"marker_tracks": 0, "cue_tracks": 0, "cue_points": 0, "loop_records": 0, "marker_failures": 0}
    totals = {"marker_tracks": 0, "cue_tracks": 0, "cue_points": 0, "loop_records": 0, "marker_failures": 0}
    with database.connect() as connection:
        for offset in range(0, len(paths), SQLITE_BATCH_SIZE):
            batch = paths[offset:offset + SQLITE_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            row = connection.execute(
                f"""
                SELECT COUNT(marker_scans.track_id) AS marker_tracks,
                       SUM(CASE WHEN marker_scans.cue_count > 0 THEN 1 ELSE 0 END) AS cue_tracks,
                       SUM(marker_scans.cue_count) AS cue_points,
                       SUM(marker_scans.loop_record_count) AS loop_records,
                       SUM(CASE WHEN marker_scans.status = 'failed' THEN 1 ELSE 0 END) AS marker_failures
                FROM tracks
                LEFT JOIN marker_scans ON marker_scans.track_id = tracks.id
                WHERE tracks.path IN ({placeholders})
                """,
                tuple(batch),
            ).fetchone()
            for name in totals:
                totals[name] += int(row[name] or 0)
    return totals
