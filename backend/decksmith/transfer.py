from __future__ import annotations

import hashlib
import json
import shutil
import stat as stat_flags
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .database import Database
from .markers import (
    cue_points_for_paths,
    marker_coverage,
    read_serato_markers,
    saved_loops_for_paths,
    scan_track_markers,
)
from .metadata import read_metadata
from .serato import sync_serato_crates


PRODUCT_NAME = "Decksmith"
PRODUCT_VERSION = "0.1.0"
PRODUCT_COMPANY = "CueRated Concepts"
SQLITE_BATCH_SIZE = 500


def _is_dataless(file_stat: Any) -> bool:
    dataless_flag = getattr(stat_flags, "SF_DATALESS", 0)
    return bool(dataless_flag and getattr(file_stat, "st_flags", 0) & dataless_flag)


def _digest_crate(hierarchy_path: str, tracks: list[str]) -> str:
    payload = json.dumps(
        {"hierarchy_path": hierarchy_path, "tracks": tracks},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _current_crates(database: Database) -> list[dict[str, Any]]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT crates.id, crates.name, crates.hierarchy_path, crates.source_path,
                   crates.source_modified_ns, crates.track_count,
                   SUM(CASE WHEN crate_tracks.track_id IS NOT NULL THEN 1 ELSE 0 END) AS matched_count,
                   SUM(CASE WHEN tracks.missing = 1 THEN 1 ELSE 0 END) AS missing_count
            FROM crates
            LEFT JOIN crate_tracks ON crate_tracks.crate_id = crates.id
            LEFT JOIN tracks ON tracks.id = crate_tracks.track_id
            GROUP BY crates.id
            ORDER BY crates.hierarchy_path COLLATE NOCASE
            """
        ).fetchall()
        crates = []
        for row in rows:
            tracks = connection.execute(
                "SELECT path FROM crate_tracks WHERE crate_id = ? ORDER BY position",
                (row["id"],),
            ).fetchall()
            item = dict(row)
            item["matched_count"] = int(item["matched_count"] or 0)
            item["missing_count"] = int(item["missing_count"] or 0)
            item["tracks"] = [track["path"] for track in tracks]
            item["digest"] = _digest_crate(item["hierarchy_path"], item["tracks"])
            crates.append(item)
    return crates


def _snapshot_crates(database: Database, snapshot_id: int) -> list[dict[str, Any]]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT source_path, name, hierarchy_path, source_modified_ns,
                   track_count, matched_count, digest, tracks_json
            FROM transfer_snapshot_crates
            WHERE snapshot_id = ?
            ORDER BY hierarchy_path COLLATE NOCASE
            """,
            (snapshot_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["tracks"] = json.loads(item.pop("tracks_json"))
        result.append(item)
    return result


def _crate_warnings(crate: dict[str, Any], duplicate_names: set[tuple[str, str]]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if crate.get("track_count", 0) == 0:
        warnings.append({"code": "empty_crate", "severity": "warning", "message": "This crate is empty."})
    unmatched = int(crate.get("track_count", 0)) - int(crate.get("matched_count", 0))
    if unmatched > 0:
        warnings.append({
            "code": "unmatched_tracks",
            "severity": "warning",
            "message": f"{unmatched} track path{'s are' if unmatched != 1 else ' is'} not indexed in Decksmith. Existing files will be read directly during export; missing files receive minimal metadata.",
        })
    missing = int(crate.get("missing_count", 0))
    if missing > 0:
        warnings.append({
            "code": "missing_tracks",
            "severity": "warning",
            "message": f"{missing} indexed track{'s are' if missing != 1 else ' is'} currently missing from disk.",
        })
    hierarchy = str(crate.get("hierarchy_path", "")).split("%%")
    sibling_key = ("%%".join(hierarchy[:-1]).casefold(), hierarchy[-1].casefold())
    if sibling_key in duplicate_names:
        warnings.append({
            "code": "duplicate_playlist_name",
            "severity": "error",
            "message": "Rekordbox does not allow duplicate playlist names at the same hierarchy level.",
        })
    return warnings


def _duplicate_sibling_names(crates: list[dict[str, Any]]) -> set[tuple[str, str]]:
    counts: dict[tuple[str, str], int] = {}
    for crate in crates:
        hierarchy = str(crate["hierarchy_path"]).split("%%")
        key = ("%%".join(hierarchy[:-1]).casefold(), hierarchy[-1].casefold())
        counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def _compare_snapshots(
    current: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    current_by_source = {crate["source_path"]: crate for crate in current}
    previous_by_source = {crate["source_path"]: crate for crate in previous}
    duplicates = _duplicate_sibling_names(current)
    changes: list[dict[str, Any]] = []

    for source_path, crate in current_by_source.items():
        old = previous_by_source.get(source_path)
        if old is None:
            status = "added"
            added_tracks = len(crate["tracks"])
            removed_tracks = 0
            reordered = False
        else:
            status = "unchanged" if old["digest"] == crate["digest"] else "modified"
            old_tracks = old["tracks"]
            old_set = set(old_tracks)
            current_set = set(crate["tracks"])
            added_tracks = len(current_set - old_set)
            removed_tracks = len(old_set - current_set)
            reordered = old_tracks != crate["tracks"] and not added_tracks and not removed_tracks
        changes.append({
            "crate_id": crate.get("id"),
            "source_path": source_path,
            "name": crate["name"],
            "hierarchy_path": crate["hierarchy_path"],
            "status": status,
            "track_count": crate["track_count"],
            "matched_count": crate["matched_count"],
            "added_tracks": added_tracks,
            "removed_tracks": removed_tracks,
            "reordered": reordered,
            "warnings": _crate_warnings(crate, duplicates),
        })

    for source_path, crate in previous_by_source.items():
        if source_path not in current_by_source:
            changes.append({
                "crate_id": None,
                "source_path": source_path,
                "name": crate["name"],
                "hierarchy_path": crate["hierarchy_path"],
                "status": "removed",
                "track_count": crate["track_count"],
                "matched_count": crate["matched_count"],
                "added_tracks": 0,
                "removed_tracks": crate["track_count"],
                "reordered": False,
                "warnings": [{
                    "code": "removed_crate",
                    "severity": "warning",
                    "message": "This crate no longer exists in Serato and will not be exported.",
                }],
            })

    return sorted(changes, key=lambda item: (item["hierarchy_path"].casefold(), item["status"]))


def _summary(changes: list[dict[str, Any]]) -> dict[str, int]:
    return {
        status: sum(change["status"] == status for change in changes)
        for status in ("added", "modified", "unchanged", "removed")
    }


def _metadata_coverage(database: Database, current: list[dict[str, Any]]) -> dict[str, Any]:
    paths = {path for crate in current for path in crate["tracks"]}
    if not paths:
        return {
            "tracks": 0, "bpm": 0, "key": 0, "comments": 0, "ratings": 0,
            "marker_tracks": 0, "cue_tracks": 0, "cue_points": 0,
            "loop_records": 0, "marker_failures": 0,
        }
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(DISTINCT tracks.id) AS tracks,
                   SUM(CASE WHEN COALESCE(analysis_bpm, bpm) IS NOT NULL THEN 1 ELSE 0 END) AS bpm,
                   SUM(CASE WHEN COALESCE(NULLIF(analysis_key, ''), musical_key) != '' THEN 1 ELSE 0 END) AS key,
                   SUM(CASE WHEN COALESCE(user_comment, comment) != '' THEN 1 ELSE 0 END) AS comments,
                   SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END) AS ratings
            FROM tracks
            WHERE tracks.id IN (
                SELECT DISTINCT track_id FROM crate_tracks WHERE track_id IS NOT NULL
            )
            """
        ).fetchone()
    coverage = {name: int(row[name] or 0) for name in ("tracks", "bpm", "key", "comments", "ratings")}
    coverage.update(marker_coverage(database, sorted(paths)))
    return coverage


def _metadata_limits(coverage: dict[str, Any]) -> list[dict[str, str]]:
    cue_message = (
        f"{coverage['cue_points']} cue points across {coverage['cue_tracks']} tracks are available for export. "
        "Hot Cue slots D-H are preserved as named memory cues because the published XML format only guarantees A-C."
    )
    if coverage["marker_failures"]:
        cue_status = "warning"
        cue_message += f" {coverage['marker_failures']} marker payloads could not be decoded and will be listed in validation."
    else:
        cue_status = "available"
    loop_message = (
        f"{coverage['loop_records']} saved loops are available for export as Rekordbox memory loops."
        if coverage["loop_records"]
        else "Saved loops are transferred as Rekordbox memory loops when detected. Unindexed tracks are read during export."
    )
    return [
        {"field": "cue_points", "status": cue_status, "message": cue_message},
        {"field": "saved_loops", "status": "available", "message": loop_message},
    ]


def capture_transfer_snapshot(
    database: Database, libraries: list[Path] | None = None
) -> dict[str, Any]:
    database.initialize()
    sync_result = sync_serato_crates(database, libraries)
    if sync_result["libraries"] == 0:
        raise ValueError("No Serato library was found. Confirm Serato has created its _Serato_ folder, then compare again.")
    current = _current_crates(database)
    with database.connect() as connection:
        marker_track_ids = [
            row["track_id"] for row in connection.execute(
                "SELECT DISTINCT track_id FROM crate_tracks WHERE track_id IS NOT NULL ORDER BY track_id"
            ).fetchall()
        ]
    marker_scan = scan_track_markers(database, marker_track_ids)
    with database.connect() as connection:
        previous_row = connection.execute(
            "SELECT id FROM transfer_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous_id = previous_row["id"] if previous_row else None
        cursor = connection.execute(
            """
            INSERT INTO transfer_snapshots(library_count, crate_count, track_count, error_count)
            VALUES (?, ?, ?, ?)
            """,
            (sync_result["libraries"], len(current), sum(crate["track_count"] for crate in current), sync_result["errors"]),
        )
        snapshot_id = int(cursor.lastrowid)
        for crate in current:
            connection.execute(
                """
                INSERT INTO transfer_snapshot_crates(
                    snapshot_id, source_path, name, hierarchy_path, source_modified_ns,
                    track_count, matched_count, digest, tracks_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id, crate["source_path"], crate["name"], crate["hierarchy_path"],
                    crate["source_modified_ns"], crate["track_count"], crate["matched_count"],
                    crate["digest"], json.dumps(crate["tracks"], ensure_ascii=False),
                ),
            )
        created_at = connection.execute(
            "SELECT created_at FROM transfer_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()["created_at"]
    previous = _snapshot_crates(database, previous_id) if previous_id is not None else []
    changes = _compare_snapshots(current, previous)
    coverage = _metadata_coverage(database, current)
    return {
        "snapshot_id": snapshot_id,
        "previous_snapshot_id": previous_id,
        "created_at": created_at,
        "libraries": sync_result["libraries"],
        "crates": len(current),
        "tracks": sum(crate["track_count"] for crate in current),
        "errors": sync_result["errors"],
        "summary": _summary(changes),
        "changes": changes,
        "metadata_coverage": coverage,
        "marker_scan": marker_scan,
        "metadata_limits": _metadata_limits(coverage),
    }


def latest_transfer_plan(database: Database) -> dict[str, Any] | None:
    database.initialize()
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM transfer_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        snapshot = dict(row)
        previous = connection.execute(
            "SELECT id FROM transfer_snapshots WHERE id < ? ORDER BY id DESC LIMIT 1",
            (snapshot["id"],),
        ).fetchone()
    current = _current_crates(database)
    previous_crates = _snapshot_crates(database, previous["id"]) if previous else []
    changes = _compare_snapshots(current, previous_crates)
    coverage = _metadata_coverage(database, current)
    return {
        "snapshot_id": snapshot["id"],
        "previous_snapshot_id": previous["id"] if previous else None,
        "created_at": snapshot["created_at"],
        "libraries": snapshot["library_count"],
        "crates": snapshot["crate_count"],
        "tracks": snapshot["track_count"],
        "errors": snapshot["error_count"],
        "summary": _summary(changes),
        "changes": changes,
        "metadata_coverage": coverage,
        "metadata_limits": _metadata_limits(coverage),
    }


def _track_metadata(database: Database, paths: list[str]) -> dict[str, dict[str, Any]]:
    if not paths:
        return {}
    result: dict[str, dict[str, Any]] = {}
    with database.connect() as connection:
        for offset in range(0, len(paths), SQLITE_BATCH_SIZE):
            batch = paths[offset:offset + SQLITE_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                f"""
                SELECT path, title, artist, album, genre, extension, file_size, modified_ns,
                       duration_seconds, COALESCE(analysis_bpm, bpm) AS export_bpm,
                       COALESCE(NULLIF(analysis_key, ''), musical_key) AS export_key,
                       sample_rate, bitrate, year, COALESCE(user_comment, comment) AS export_comment,
                       rating, color_tag, play_count, last_played_at, discovered_at, missing,
                       metadata_status, metadata_error
                FROM tracks WHERE path IN ({placeholders})
                """,
                tuple(batch),
            ).fetchall()
            result.update({row["path"]: dict(row) for row in rows})
    for path in paths:
        if path in result:
            continue
        file_path = Path(path)
        if not file_path.is_file():
            continue
        try:
            stat = file_path.stat()
        except OSError:
            continue
        item = read_metadata(file_path) if not _is_dataless(stat) else None
        result[path] = {
            "path": path,
            "title": item.title if item else file_path.stem,
            "artist": item.artist if item else "",
            "album": item.album if item else "",
            "genre": item.genre if item else "",
            "extension": file_path.suffix.casefold(),
            "file_size": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
            "duration_seconds": item.duration_seconds if item else None,
            "export_bpm": item.bpm if item else None,
            "export_key": item.musical_key if item else "",
            "sample_rate": item.sample_rate if item else None,
            "bitrate": item.bitrate if item else None,
            "year": item.year if item else "",
            "export_comment": item.comment if item else "",
            "rating": 0,
            "color_tag": "",
            "play_count": 0,
            "last_played_at": None,
            "discovered_at": _date_from_ns(stat.st_mtime_ns),
            "missing": 0,
            "metadata_status": item.status if item else "cloud_only",
            "metadata_error": item.error if item else "The file is a cloud-only placeholder.",
        }
    return result


def _date_from_ns(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC).date().isoformat()


def _set_if(attributes: dict[str, str], name: str, value: Any) -> None:
    if value is not None and value != "":
        attributes[name] = str(value)


def _track_attributes(path: str, track_id: int, metadata: dict[str, Any] | None) -> dict[str, str]:
    file_path = Path(path)
    attributes = {
        "TrackID": str(track_id),
        "Name": metadata["title"] if metadata and metadata["title"] else file_path.stem,
        "Location": "file://localhost" + quote(file_path.absolute().as_posix()),
    }
    if metadata is None:
        return attributes
    _set_if(attributes, "Artist", metadata["artist"])
    _set_if(attributes, "Album", metadata["album"])
    _set_if(attributes, "Genre", metadata["genre"])
    _set_if(attributes, "Kind", metadata["extension"].lstrip(".").upper())
    _set_if(attributes, "Size", metadata["file_size"])
    if metadata["duration_seconds"] is not None:
        attributes["TotalTime"] = str(max(0, round(metadata["duration_seconds"])))
    _set_if(attributes, "AverageBpm", metadata["export_bpm"])
    _set_if(attributes, "Tonality", metadata["export_key"])
    _set_if(attributes, "SampleRate", metadata["sample_rate"])
    if metadata["bitrate"] is not None:
        attributes["BitRate"] = str(round(metadata["bitrate"] / 1000) if metadata["bitrate"] > 10_000 else metadata["bitrate"])
    year = str(metadata["year"] or "")[:4]
    if year.isdigit():
        attributes["Year"] = year
    _set_if(attributes, "Comments", metadata["export_comment"])
    attributes["Rating"] = str(max(0, min(5, int(metadata["rating"] or 0))) * 51)
    attributes["PlayCount"] = str(max(0, int(metadata["play_count"] or 0)))
    date_modified = _date_from_ns(metadata["modified_ns"])
    _set_if(attributes, "DateModified", date_modified)
    _set_if(attributes, "DateAdded", str(metadata["discovered_at"] or "")[:10])
    _set_if(attributes, "LastPlayed", str(metadata["last_played_at"] or "")[:10])
    colours = {
        "violet": "0x660099", "rose": "0xFF007F", "amber": "0xFFA500",
        "cyan": "0x25FDE9", "blue": "0x0000FF", "red": "0xFF0000",
        "green": "0x00FF00", "lemon": "0xFFFF00",
    }
    if str(metadata["color_tag"]).casefold() in colours:
        attributes["Colour"] = colours[str(metadata["color_tag"]).casefold()]
    return attributes


def _append_playlist_tree(parent: ET.Element, tree: dict[str, Any]) -> None:
    for name, branch in tree.items():
        playlist = branch.get("playlist")
        children = branch.get("children", {})
        if children:
            node = ET.SubElement(parent, "NODE", Name=name, Type="0", Count=str(len(children) + int(playlist is not None)))
            if playlist is not None:
                playlist_node = ET.SubElement(node, "NODE", Name=name, Type="1", Entries=str(len(playlist)), KeyType="0")
                for key in playlist:
                    ET.SubElement(playlist_node, "TRACK", Key=str(key))
            _append_playlist_tree(node, children)
        elif playlist is not None:
            node = ET.SubElement(parent, "NODE", Name=name, Type="1", Entries=str(len(playlist)), KeyType="0")
            for key in playlist:
                ET.SubElement(node, "TRACK", Key=str(key))


def validate_rekordbox_xml(xml: bytes) -> dict[str, int | str]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise ValueError(f"Generated Rekordbox XML is not well formed: {error}") from error
    errors: list[str] = []
    if root.tag != "DJ_PLAYLISTS" or root.get("Version") != "1.0.0":
        errors.append("root element or version is invalid")
    collection = root.find("COLLECTION")
    playlists = root.find("PLAYLISTS")
    if collection is None:
        errors.append("COLLECTION is missing")
    if playlists is None:
        errors.append("PLAYLISTS is missing")
    if errors:
        raise ValueError("Generated Rekordbox XML failed validation: " + "; ".join(errors))

    tracks = collection.findall("TRACK")
    if collection.get("Entries") != str(len(tracks)):
        errors.append("COLLECTION entry count does not match its tracks")
    track_ids: set[str] = set()
    cue_count = 0
    loop_count = 0
    for track in tracks:
        track_id = track.get("TrackID", "")
        if not track_id or track_id in track_ids:
            errors.append("collection track ids are missing or duplicated")
        track_ids.add(track_id)
        if not track.get("Location", "").startswith("file://localhost/"):
            errors.append(f"track {track_id or '?'} has an invalid file location")
        for marker in track.findall("POSITION_MARK"):
            try:
                marker_type = marker.get("Type")
                start = float(marker.get("Start", "-1"))
                if marker_type not in {"0", "4"} or start < 0:
                    raise ValueError
                if marker_type == "4":
                    if float(marker.get("End", "-1")) <= start:
                        raise ValueError
                    loop_count += 1
                else:
                    cue_count += 1
                int(marker.get("Num", ""))
            except ValueError:
                errors.append(f"track {track_id or '?'} has an invalid position marker")

    root_nodes = playlists.findall("NODE")
    if len(root_nodes) != 1 or root_nodes[0].get("Name") != "ROOT" or root_nodes[0].get("Type") != "0":
        errors.append("playlist root is invalid")

    playlist_count = 0
    playlist_entries = 0

    def inspect_node(node: ET.Element) -> None:
        nonlocal playlist_count, playlist_entries
        node_type = node.get("Type")
        if node_type == "0":
            children = node.findall("NODE")
            if node.get("Count") != str(len(children)):
                errors.append(f"folder {node.get('Name', '?')} has an invalid child count")
            for child in children:
                inspect_node(child)
        elif node_type == "1":
            playlist_count += 1
            references = node.findall("TRACK")
            playlist_entries += len(references)
            if node.get("Entries") != str(len(references)) or node.get("KeyType") != "0":
                errors.append(f"playlist {node.get('Name', '?')} has invalid entry metadata")
            for reference in references:
                if reference.get("Key", "") not in track_ids:
                    errors.append(f"playlist {node.get('Name', '?')} references an unknown track")
        else:
            errors.append(f"node {node.get('Name', '?')} has an invalid type")

    if root_nodes:
        inspect_node(root_nodes[0])
    if errors:
        raise ValueError("Generated Rekordbox XML failed validation: " + "; ".join(dict.fromkeys(errors)))
    return {
        "status": "passed",
        "collection_tracks": len(tracks),
        "playlists": playlist_count,
        "playlist_entries": playlist_entries,
        "cue_points": cue_count,
        "saved_loops": loop_count,
    }


def _markers_for_export(
    database: Database, paths: list[str]
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    list[dict[str, str]],
]:
    cues = cue_points_for_paths(database, paths)
    loops = saved_loops_for_paths(database, paths)
    warnings: list[dict[str, str]] = []
    with database.connect() as connection:
        scanned_paths = {
            row["path"] for row in connection.execute(
                """
                SELECT tracks.path FROM marker_scans
                JOIN tracks ON tracks.id = marker_scans.track_id
                WHERE marker_scans.status = 'completed'
                """
            ).fetchall()
        }
    for path in paths:
        if path in scanned_paths:
            continue
        try:
            file_stat = Path(path).stat()
        except OSError:
            file_stat = None
        if file_stat is not None and _is_dataless(file_stat):
            warnings.append({
                "code": "cloud_file_unavailable",
                "severity": "warning",
                "message": f"{path} is a cloud-only placeholder. Its playlist location was preserved without downloading the file; embedded metadata, cues and loops were unavailable.",
            })
            continue
        marker_result = read_serato_markers(path)
        if marker_result.status == "failed":
            warnings.append({
                "code": "marker_decode_failure", "severity": "warning",
                "message": f"Serato markers in {path} could not be decoded safely: {marker_result.error}",
            })
            continue
        if marker_result.cues:
            cues[path] = [
                {
                    "slot": cue.slot, "name": cue.name,
                    "position_seconds": cue.position_seconds, "color": cue.color,
                }
                for cue in marker_result.cues
            ]
        if marker_result.loops:
            loops[path] = [
                {
                    "slot": loop.slot,
                    "start_seconds": loop.start_seconds,
                    "end_seconds": loop.end_seconds,
                    "color": loop.color,
                }
                for loop in marker_result.loops
            ]
    return cues, loops, warnings


def _build_xml(database: Database, crates: list[dict[str, Any]]) -> tuple[bytes, int, int, int, list[dict[str, str]]]:
    ordered_paths: list[str] = []
    for crate in crates:
        for path in crate["tracks"]:
            if path not in ordered_paths:
                ordered_paths.append(path)
    metadata = _track_metadata(database, ordered_paths)
    cue_points, saved_loops, marker_warnings = _markers_for_export(database, ordered_paths)
    path_keys = {path: index + 1 for index, path in enumerate(ordered_paths)}
    warnings: list[dict[str, str]] = list(marker_warnings)
    exported_cues = 0
    exported_loops = 0

    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name=PRODUCT_NAME, Version=PRODUCT_VERSION, Company=PRODUCT_COMPANY)
    collection = ET.SubElement(root, "COLLECTION", Entries=str(len(ordered_paths)))
    for path in ordered_paths:
        item = metadata.get(path)
        track_element = ET.SubElement(collection, "TRACK", _track_attributes(path, path_keys[path], item))
        for cue in cue_points.get(path, []):
            position = float(cue["position_seconds"])
            if item and item["duration_seconds"] is not None and position > float(item["duration_seconds"]) + 0.5:
                warnings.append({"code": "cue_out_of_range", "severity": "warning", "message": f"A cue at {position:.3f}s in {path} is beyond the indexed duration and was not exported."})
                continue
            slot = int(cue["slot"])
            marker_name = str(cue["name"] or f"Hot Cue {chr(65 + slot)}")
            marker_number = slot if slot <= 2 else -1
            ET.SubElement(
                track_element, "POSITION_MARK", Name=marker_name, Type="0",
                Start=f"{position:.3f}", Num=str(marker_number),
            )
            exported_cues += 1
            if slot > 2:
                warnings.append({
                    "code": "hot_cue_slot_downgraded", "severity": "warning",
                    "message": f"Hot Cue {chr(65 + slot)} in {path} was exported as a named memory cue because the published XML format only guarantees slots A-C.",
                })
        for loop in saved_loops.get(path, []):
            start = float(loop["start_seconds"])
            end = float(loop["end_seconds"])
            if item and item["duration_seconds"] is not None and end > float(item["duration_seconds"]) + 0.5:
                warnings.append({
                    "code": "loop_out_of_range",
                    "severity": "warning",
                    "message": f"A saved loop ending at {end:.3f}s in {path} is beyond the indexed duration and was not exported.",
                })
                continue
            ET.SubElement(
                track_element,
                "POSITION_MARK",
                Name=f"Serato Saved Loop {int(loop['slot']) + 1}",
                Type="4",
                Start=f"{start:.3f}",
                End=f"{end:.3f}",
                Num="-1",
            )
            exported_loops += 1
        if item is None:
            warnings.append({"code": "minimal_metadata", "severity": "warning", "message": f"{path} is not indexed. Only its file name and location were exported."})
        elif item["missing"]:
            warnings.append({"code": "missing_file", "severity": "warning", "message": f"{path} is marked missing and may not import into Rekordbox."})
        elif item.get("metadata_status") == "error":
            warnings.append({"code": "metadata_read_error", "severity": "warning", "message": f"Metadata for {path} could not be read completely. File location and fallback title were preserved."})

    playlists = ET.SubElement(root, "PLAYLISTS")
    tree: dict[str, Any] = {}
    for crate in crates:
        branch = tree
        parts = crate["hierarchy_path"].split("%%")
        for part in parts:
            node = branch.setdefault(part, {"children": {}, "playlist": None})
            branch = node["children"]
        node["playlist"] = [path_keys[path] for path in crate["tracks"]]
    root_node = ET.SubElement(playlists, "NODE", Name="ROOT", Type="0", Count=str(len(tree)))
    _append_playlist_tree(root_node, tree)
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    validate_rekordbox_xml(xml)
    return xml, len(ordered_paths), exported_cues, exported_loops, warnings


def create_rekordbox_package(
    database: Database, destination: str | Path, crate_ids: list[int] | None = None
) -> dict[str, Any]:
    database.initialize()
    plan = latest_transfer_plan(database)
    if plan is None:
        raise ValueError("Create a Serato snapshot before exporting.")
    current = _current_crates(database)
    current_by_id = {int(crate["id"]): crate for crate in current}
    latest_by_source = {
        crate["source_path"]: crate for crate in _snapshot_crates(database, int(plan["snapshot_id"]))
    }
    for crate in current:
        snapshotted = latest_by_source.get(crate["source_path"])
        if snapshotted is None or snapshotted["digest"] != crate["digest"]:
            raise ValueError("Serato state changed after the latest snapshot. Create a new snapshot before exporting.")

    if crate_ids is None:
        selected_ids = {
            int(change["crate_id"]) for change in plan["changes"]
            if change["crate_id"] is not None and change["status"] in {"added", "modified"}
        }
    else:
        selected_ids = {int(crate_id) for crate_id in crate_ids}
    unknown = selected_ids - set(current_by_id)
    if unknown:
        raise ValueError(f"Unknown crate ids: {', '.join(map(str, sorted(unknown)))}")
    selected = [crate for crate in current if int(crate["id"]) in selected_ids]
    if not selected:
        raise ValueError("Select at least one current crate to export.")

    selected_track_ids: set[int] = set()
    with database.connect() as connection:
        selected_id_list = sorted(selected_ids)
        for offset in range(0, len(selected_id_list), SQLITE_BATCH_SIZE):
            batch = selected_id_list[offset:offset + SQLITE_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            selected_track_ids.update(
                row["track_id"] for row in connection.execute(
                    f"""
                    SELECT DISTINCT track_id FROM crate_tracks
                    WHERE crate_id IN ({placeholders}) AND track_id IS NOT NULL
                    """,
                    tuple(batch),
                ).fetchall()
            )
    scan_track_markers(database, sorted(selected_track_ids))

    duplicate_names = _duplicate_sibling_names(selected)
    validation = [warning for crate in selected for warning in _crate_warnings(crate, duplicate_names)]
    errors = [warning for warning in validation if warning["severity"] == "error"]
    if errors:
        raise ValueError("Transfer validation failed: " + " ".join(error["message"] for error in errors))

    xml, track_count, cue_count, loop_count, track_warnings = _build_xml(database, selected)
    xml_validation = validate_rekordbox_xml(xml)
    selected_paths = list(dict.fromkeys(path for crate in selected for path in crate["tracks"]))
    selected_marker_coverage = marker_coverage(database, selected_paths)
    warnings = validation + track_warnings
    if selected_marker_coverage["marker_failures"]:
        warnings.append({
            "code": "marker_decode_failures", "severity": "warning",
            "message": f"{selected_marker_coverage['marker_failures']} track marker payloads could not be decoded. Their cues and loops were not silently approximated.",
        })
    base = Path(destination).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
    final = base / f"Decksmith Transfer {stamp}"
    suffix = 2
    while final.exists():
        final = base / f"Decksmith Transfer {stamp} ({suffix})"
        suffix += 1
    staging = Path(tempfile.mkdtemp(prefix=".decksmith-transfer-", dir=base))
    try:
        xml_path = staging / "decksmith-rekordbox.xml"
        report_path = staging / "transfer-report.json"
        instructions_path = staging / "README.txt"
        manifest_path = staging / "transfer-manifest.json"
        xml_path.write_bytes(xml)
        report = {
            "format": "Decksmith Transfer Report 1",
            "created_at": datetime.now(tz=UTC).isoformat(),
            "snapshot_id": plan["snapshot_id"],
            "crate_count": len(selected),
            "track_count": track_count,
            "cue_count": cue_count,
            "loop_count": loop_count,
            "loop_records_detected": loop_count,
            "crates": [
                {
                    "id": crate["id"], "name": crate["name"],
                    "hierarchy_path": crate["hierarchy_path"], "track_count": crate["track_count"],
                }
                for crate in selected
            ],
            "warnings": warnings,
            "xml_validation": xml_validation,
            "source_safety": {
                "serato_database_modified": False,
                "rekordbox_database_modified": False,
                "audio_files_modified": False,
            },
            "xml_sha256": hashlib.sha256(xml).hexdigest(),
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        instructions = (
            "Decksmith Rekordbox Transfer\n\n"
            "1. Open rekordbox.\n"
            "2. Open Preferences, Advanced, Database, rekordbox xml.\n"
            "3. Choose decksmith-rekordbox.xml as the Imported Library.\n"
            "4. Review the playlists under rekordbox xml before importing them.\n"
            "5. Read transfer-report.json for every warning and metadata limitation.\n\n"
            "Decksmith did not modify Serato, rekordbox, or any audio file.\n"
        )
        instructions_path.write_text(instructions, encoding="utf-8")
        manifest = {
            "format": "Decksmith Transfer Manifest 1",
            "created_at": datetime.now(tz=UTC).isoformat(),
            "files": {
                xml_path.name: hashlib.sha256(xml_path.read_bytes()).hexdigest(),
                report_path.name: hashlib.sha256(report_path.read_bytes()).hexdigest(),
                instructions_path.name: hashlib.sha256(instructions_path.read_bytes()).hexdigest(),
            },
            "validation_status": xml_validation["status"],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        staging.rename(final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    xml_final = final / "decksmith-rekordbox.xml"
    report_final = final / "transfer-report.json"
    manifest_final = final / "transfer-manifest.json"
    try:
        with database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO transfer_exports(
                    snapshot_id, destination_path, xml_path, report_path,
                    crate_count, track_count, warning_count, cue_count, loop_count,
                    validation_status, manifest_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan["snapshot_id"], str(final), str(xml_final), str(report_final),
                    len(selected), track_count, len(warnings), cue_count, loop_count,
                    str(xml_validation["status"]), str(manifest_final),
                ),
            )
            export_id = int(cursor.lastrowid)
    except Exception:
        shutil.rmtree(final, ignore_errors=True)
        raise
    return {
        "export_id": export_id,
        "destination_path": str(final),
        "xml_path": str(xml_final),
        "report_path": str(report_final),
        "manifest_path": str(manifest_final),
        "crate_count": len(selected),
        "track_count": track_count,
        "cue_count": cue_count,
        "loop_count": loop_count,
        "validation_status": xml_validation["status"],
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def verify_transfer_package(database: Database, destination: str | Path) -> dict[str, Any]:
    database.initialize()
    package = Path(destination).expanduser().resolve(strict=True)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM transfer_exports WHERE destination_path = ?",
            (str(package),),
        ).fetchone()
    if row is None:
        raise ValueError("This folder is not a recorded Decksmith transfer package.")
    record = dict(row)
    expected_files = {
        "decksmith-rekordbox.xml": Path(record["xml_path"]),
        "transfer-report.json": Path(record["report_path"]),
        "README.txt": package / "README.txt",
    }
    manifest_path = Path(record["manifest_path"])
    if manifest_path.parent != package or any(path.parent != package for path in expected_files.values()):
        raise ValueError("Transfer history contains a path outside the recorded package.")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Transfer manifest is missing.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Transfer manifest could not be read.") from error
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, dict):
        raise ValueError("Transfer manifest does not contain file hashes.")
    for name, path in expected_files.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Transfer package file is missing: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if manifest_files.get(name) != digest:
            raise ValueError(f"Transfer package integrity check failed for {name}")
    xml = expected_files["decksmith-rekordbox.xml"].read_bytes()
    xml_validation = validate_rekordbox_xml(xml)
    try:
        report = json.loads(expected_files["transfer-report.json"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Transfer report could not be read.") from error
    if report.get("xml_sha256") != hashlib.sha256(xml).hexdigest():
        raise ValueError("Transfer report XML hash does not match the package.")
    return {
        "status": "passed",
        "destination_path": str(package),
        "export_id": record["id"],
        "crate_count": record["crate_count"],
        "track_count": record["track_count"],
        "cue_count": record["cue_count"],
        "loop_count": record["loop_count"],
        "warning_count": record["warning_count"],
        "xml_validation": xml_validation,
    }


def list_transfer_exports(database: Database) -> list[dict[str, Any]]:
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM transfer_exports ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]
