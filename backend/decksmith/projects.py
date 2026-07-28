from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .database import Database


CHANNEL_COLORS = {1: "violet", 2: "cyan", 3: "rose", 4: "amber"}
SUPPORTED_COLORS = {"violet", "cyan", "rose", "amber", "blue", "red", "green"}
STEM_KINDS = {"vocals", "drums", "bass", "other"}
EDITABLE_CLIP_FIELDS = {
    "channel",
    "start_seconds",
    "source_in_seconds",
    "duration_seconds",
    "gain_db",
    "pan",
    "pitch_semitones",
    "tempo_percent",
    "color",
    "expanded",
    "locked",
    "muted",
    "solo",
    "loop_enabled",
    "reversed",
    "fade_in_seconds",
    "fade_out_seconds",
    "eq_low_db",
    "eq_mid_db",
    "eq_high_db",
    "highpass_hz",
    "lowpass_hz",
    "compressor_enabled",
    "compressor_threshold_db",
    "compressor_ratio",
}


def _tempo_factor(value: Any) -> float:
    return float(value) / 100.0


def _source_span(duration_seconds: Any, tempo_percent: Any) -> float:
    return float(duration_seconds) * _tempo_factor(tempo_percent)


def _validate_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("Project name cannot be empty.")
    if len(value) > 120:
        raise ValueError("Project name must be 120 characters or fewer.")
    return value


def _validate_tempo(tempo: float) -> float:
    value = float(tempo)
    if value < 40 or value > 240:
        raise ValueError("Project tempo must be between 40 and 240 BPM.")
    return round(value, 3)


def _validate_marker_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("Marker name cannot be empty.")
    if len(value) > 80:
        raise ValueError("Marker name must be 80 characters or fewer.")
    return value


def _project_snapshot(connection: Any, project_id: int) -> dict[str, Any]:
    project = connection.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise ValueError("Arrangement project was not found.")
    clips = connection.execute(
        "SELECT * FROM timeline_clips WHERE project_id = ? ORDER BY channel, start_seconds, id",
        (project_id,),
    ).fetchall()
    markers = connection.execute(
        "SELECT * FROM project_markers WHERE project_id = ? ORDER BY start_seconds, id",
        (project_id,),
    ).fetchall()
    stem_states = connection.execute(
        """
        SELECT clip_stem_states.*
        FROM clip_stem_states
        JOIN timeline_clips ON timeline_clips.id = clip_stem_states.clip_id
        WHERE timeline_clips.project_id = ?
        ORDER BY clip_stem_states.clip_id, clip_stem_states.stem_kind
        """,
        (project_id,),
    ).fetchall()
    rendered_sources = connection.execute(
        """
        SELECT rendered_clip_sources.*
        FROM rendered_clip_sources
        JOIN timeline_clips ON timeline_clips.id = rendered_clip_sources.clip_id
        WHERE timeline_clips.project_id = ?
        ORDER BY rendered_clip_sources.clip_id
        """,
        (project_id,),
    ).fetchall()
    return {
        "project": dict(project),
        "clips": [dict(clip) for clip in clips],
        "markers": [dict(marker) for marker in markers],
        "stem_states": [dict(state) for state in stem_states],
        "rendered_sources": [dict(source) for source in rendered_sources],
    }


def _record_history(connection: Any, project_id: int, action: str) -> None:
    snapshot = _project_snapshot(connection, project_id)
    connection.execute("DELETE FROM project_redo_history WHERE project_id = ?", (project_id,))
    connection.execute(
        "INSERT INTO project_history(project_id, action, snapshot_json) VALUES (?, ?, ?)",
        (project_id, action, json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))),
    )


def _restore_project_snapshot(connection: Any, project_id: int, snapshot: dict[str, Any]) -> None:
    project = snapshot.get("project") or {}
    project_fields = [
        "name", "tempo", "musical_key", "time_signature_numerator",
        "time_signature_denominator", "snap_enabled", "snap_beats",
        "selection_start_seconds", "selection_end_seconds", "selection_loop_enabled",
        "master_gain_db", "master_limiter_enabled", "master_low_eq_db",
        "master_mid_eq_db", "master_high_eq_db", "master_stereo_width",
        "target_lufs",
    ]
    available = [field for field in project_fields if field in project]
    if available:
        connection.execute(
            f"UPDATE projects SET {', '.join(f'{field} = ?' for field in available)}, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            tuple(project[field] for field in available) + (project_id,),
        )
    connection.execute("DELETE FROM timeline_clips WHERE project_id = ?", (project_id,))
    clips = sorted(snapshot.get("clips") or [], key=lambda clip: clip.get("parent_clip_id") is not None)
    clip_columns = {row["name"] for row in connection.execute("PRAGMA table_info(timeline_clips)")}
    for clip in clips:
        values = {key: value for key, value in clip.items() if key in clip_columns}
        values["project_id"] = project_id
        columns = list(values)
        connection.execute(
            f"INSERT INTO timeline_clips({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
    for state in snapshot.get("stem_states") or []:
        if connection.execute(
            "SELECT 1 FROM timeline_clips WHERE id = ? AND project_id = ?",
            (state.get("clip_id"), project_id),
        ).fetchone() is None:
            continue
        connection.execute(
            """
            INSERT INTO clip_stem_states(clip_id, stem_kind, muted, solo, updated_at)
            VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            """,
            (
                state.get("clip_id"), state.get("stem_kind"), state.get("muted", 0),
                state.get("solo", 0), state.get("updated_at"),
            ),
        )
    for source in snapshot.get("rendered_sources") or []:
        if connection.execute(
            "SELECT 1 FROM timeline_clips WHERE id = ? AND project_id = ?",
            (source.get("clip_id"), project_id),
        ).fetchone() is None:
            continue
        source_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(rendered_clip_sources)")
        }
        values = {key: value for key, value in source.items() if key in source_columns}
        columns = list(values)
        connection.execute(
            f"INSERT INTO rendered_clip_sources({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
    connection.execute("DELETE FROM project_markers WHERE project_id = ?", (project_id,))
    marker_columns = {row["name"] for row in connection.execute("PRAGMA table_info(project_markers)")}
    for marker in snapshot.get("markers") or []:
        values = {key: value for key, value in marker.items() if key in marker_columns}
        values["project_id"] = project_id
        columns = list(values)
        connection.execute(
            f"INSERT INTO project_markers({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )


def _project_result(connection: Any, project_id: int) -> dict[str, Any]:
    project = connection.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if project is None:
        raise ValueError("Arrangement project was not found.")
    clips = connection.execute(
        """
        SELECT timeline_clips.*,
               COALESCE(rendered_clip_sources.title, tracks.title) AS title,
               CASE WHEN timeline_clips.clip_kind = 'rendered' THEN 'Decksmith' ELSE tracks.artist END AS artist,
               CASE
                   WHEN timeline_clips.clip_kind = 'rendered'
                       THEN rendered_clip_sources.path
                   WHEN timeline_clips.clip_kind IN ('vocals', 'drums', 'bass', 'other')
                       THEN stem_cache.path
                   ELSE tracks.path
               END AS path,
               CASE WHEN timeline_clips.clip_kind = 'rendered'
                   THEN rendered_clip_sources.bpm ELSE tracks.bpm END AS source_bpm,
               CASE WHEN timeline_clips.clip_kind = 'rendered'
                   THEN rendered_clip_sources.musical_key ELSE tracks.musical_key END AS source_key,
               CASE WHEN timeline_clips.clip_kind = 'rendered'
                   THEN rendered_clip_sources.duration_seconds ELSE tracks.duration_seconds END
                   AS source_duration_seconds,
               CASE
                   WHEN timeline_clips.clip_kind = 'rendered'
                       THEN CASE WHEN rendered_clip_sources.path IS NULL THEN 1 ELSE 0 END
                   WHEN timeline_clips.clip_kind IN ('vocals', 'drums', 'bass', 'other')
                       THEN CASE WHEN stem_cache.path IS NULL THEN 1 ELSE 0 END
                   ELSE tracks.missing
               END AS missing,
               CASE
                   WHEN timeline_clips.clip_kind = 'rendered' THEN 'wav'
                   WHEN timeline_clips.clip_kind IN ('vocals', 'drums', 'bass', 'other')
                       THEN 'wav'
                   ELSE tracks.extension
               END AS extension,
               rendered_clip_sources.render_mode AS rendered_mode
        FROM timeline_clips
        JOIN tracks ON tracks.id = timeline_clips.track_id
        LEFT JOIN rendered_clip_sources
          ON rendered_clip_sources.clip_id = timeline_clips.id
        LEFT JOIN stem_cache
          ON stem_cache.track_id = timeline_clips.track_id
         AND stem_cache.stem_kind = timeline_clips.clip_kind
         AND stem_cache.model = 'htdemucs'
         AND stem_cache.source_modified_ns = tracks.modified_ns
        WHERE timeline_clips.project_id = ?
        ORDER BY timeline_clips.channel, timeline_clips.start_seconds, timeline_clips.id
        """,
        (project_id,),
    ).fetchall()
    markers = connection.execute(
        "SELECT * FROM project_markers WHERE project_id = ? ORDER BY start_seconds, id",
        (project_id,),
    ).fetchall()
    can_undo = connection.execute(
        "SELECT 1 FROM project_history WHERE project_id = ? AND action <> 'created' LIMIT 1",
        (project_id,),
    ).fetchone() is not None
    can_redo = connection.execute(
        "SELECT 1 FROM project_redo_history WHERE project_id = ? LIMIT 1", (project_id,)
    ).fetchone() is not None
    stem_rows = connection.execute(
        """
        SELECT clip_stem_states.*
        FROM clip_stem_states
        JOIN timeline_clips ON timeline_clips.id = clip_stem_states.clip_id
        WHERE timeline_clips.project_id = ?
        """,
        (project_id,),
    ).fetchall()
    stem_states: dict[int, dict[str, dict[str, int]]] = {}
    for state in stem_rows:
        stem_states.setdefault(int(state["clip_id"]), {})[str(state["stem_kind"])] = {
            "muted": int(state["muted"]), "solo": int(state["solo"]),
        }
    clip_results = []
    for clip in clips:
        item = dict(clip)
        if item["clip_kind"] == "rendered":
            item["missing"] = int(not item.get("path") or not Path(item["path"]).is_file())
        item["stem_states"] = stem_states.get(int(clip["id"]), {})
        clip_results.append(item)
    return {
        "project": dict(project),
        "clips": clip_results,
        "markers": [dict(marker) for marker in markers],
        "can_undo": can_undo,
        "can_redo": can_redo,
    }


def list_projects(database: Database) -> list[dict[str, Any]]:
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT projects.*,
                   COUNT(timeline_clips.id) AS clip_count,
                   COALESCE(MAX(timeline_clips.start_seconds + timeline_clips.duration_seconds), 0)
                       AS duration_seconds
            FROM projects
            LEFT JOIN timeline_clips ON timeline_clips.project_id = projects.id
            GROUP BY projects.id
            ORDER BY projects.updated_at DESC, projects.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def load_project(database: Database, project_id: int) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        return _project_result(connection, int(project_id))


def create_project(database: Database, name: str, tempo: float = 120) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        cursor = connection.execute(
            "INSERT INTO projects(name, tempo) VALUES (?, ?)",
            (_validate_name(name), _validate_tempo(tempo)),
        )
        project_id = int(cursor.lastrowid)
        _record_history(connection, project_id, "created")
        return _project_result(connection, project_id)


def update_project(
    database: Database,
    project_id: int,
    name: str | None = None,
    tempo: float | None = None,
    snap_enabled: bool | None = None,
    snap_beats: float | None = None,
    master_gain_db: float | None = None,
    master_limiter_enabled: bool | None = None,
    musical_key: str | None = None,
    master_low_eq_db: float | None = None,
    master_mid_eq_db: float | None = None,
    master_high_eq_db: float | None = None,
    master_stereo_width: float | None = None,
    target_lufs: float | None = None,
) -> dict[str, Any]:
    database.initialize()
    updates: list[str] = []
    values: list[Any] = []
    if name is not None:
        updates.append("name = ?")
        values.append(_validate_name(name))
    if tempo is not None:
        updates.append("tempo = ?")
        values.append(_validate_tempo(tempo))
    if snap_enabled is not None:
        updates.append("snap_enabled = ?")
        values.append(int(bool(snap_enabled)))
    if snap_beats is not None:
        beat_value = float(snap_beats)
        if beat_value not in {0.125, 0.25, 0.5, 1, 2, 4, 8, 16}:
            raise ValueError("Snap grid is not supported.")
        updates.append("snap_beats = ?")
        values.append(beat_value)
    if master_gain_db is not None:
        gain = round(float(master_gain_db), 3)
        if gain < -24 or gain > 12:
            raise ValueError("Master gain must be between -24 and 12 dB.")
        updates.append("master_gain_db = ?")
        values.append(gain)
    if master_limiter_enabled is not None:
        updates.append("master_limiter_enabled = ?")
        values.append(int(bool(master_limiter_enabled)))
    if musical_key is not None:
        key = str(musical_key).strip().upper()
        if len(key) > 12:
            raise ValueError("Project key must be 12 characters or fewer.")
        updates.append("musical_key = ?")
        values.append(key)
    for field, raw_value in (
        ("master_low_eq_db", master_low_eq_db),
        ("master_mid_eq_db", master_mid_eq_db),
        ("master_high_eq_db", master_high_eq_db),
    ):
        if raw_value is not None:
            value = round(float(raw_value), 3)
            if value < -12 or value > 12:
                raise ValueError("Master EQ gain must be between -12 and 12 dB.")
            updates.append(f"{field} = ?")
            values.append(value)
    if master_stereo_width is not None:
        width = round(float(master_stereo_width), 3)
        if width < 0 or width > 2:
            raise ValueError("Master stereo width must be between 0 and 2.")
        updates.append("master_stereo_width = ?")
        values.append(width)
    if target_lufs is not None:
        loudness = round(float(target_lufs), 1)
        if loudness < -24 or loudness > -6:
            raise ValueError("Target loudness must be between -24 and -6 LUFS.")
        updates.append("target_lufs = ?")
        values.append(loudness)
    if not updates:
        return load_project(database, project_id)
    with database.connect() as connection:
        _record_history(connection, int(project_id), "project_updated")
        values.append(int(project_id))
        connection.execute(
            f"UPDATE projects SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            tuple(values),
        )
        return _project_result(connection, int(project_id))


def add_track_to_project(
    database: Database,
    project_id: int,
    track_id: int,
    channel: int,
    start_seconds: float | None = None,
) -> dict[str, Any]:
    database.initialize()
    channel_number = int(channel)
    if channel_number not in {1, 2, 3, 4}:
        raise ValueError("Arrangement channel must be between 1 and 4.")
    with database.connect() as connection:
        _project_snapshot(connection, int(project_id))
        track = connection.execute(
            "SELECT id, duration_seconds, missing, color_tag FROM tracks WHERE id = ?",
            (int(track_id),),
        ).fetchone()
        if track is None:
            raise ValueError("Library track was not found.")
        if track["missing"]:
            raise ValueError("This track is missing from disk and cannot be added.")
        if track["duration_seconds"] is None or float(track["duration_seconds"]) <= 0:
            raise ValueError("Track duration is unavailable. Rescan its music folder before adding it.")
        if start_seconds is None:
            end_row = connection.execute(
                """
                SELECT COALESCE(MAX(start_seconds + duration_seconds), 0) AS channel_end
                FROM timeline_clips WHERE project_id = ? AND channel = ?
                """,
                (int(project_id), channel_number),
            ).fetchone()
            start = float(end_row["channel_end"] or 0)
        else:
            start = float(start_seconds)
        if start < 0:
            raise ValueError("Clip start cannot be negative.")
        color = str(track["color_tag"] or "").strip().casefold()
        if color not in {"violet", "cyan", "rose", "amber", "blue", "red", "green"}:
            color = CHANNEL_COLORS[channel_number]
        _record_history(connection, int(project_id), "track_added")
        cursor = connection.execute(
            """
            INSERT INTO timeline_clips(
                project_id, track_id, channel, start_seconds, duration_seconds, color
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(project_id), int(track_id), channel_number, round(start, 3),
                float(track["duration_seconds"]), color,
            ),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(project_id),),
        )
        result = _project_result(connection, int(project_id))
        result["selected_clip_id"] = int(cursor.lastrowid)
        return result


def _require_cached_stem(connection: Any, track_id: int, stem_kind: str) -> Any:
    kind = str(stem_kind).strip().casefold()
    if kind not in STEM_KINDS:
        raise ValueError("Stem kind must be vocals, drums, bass or other.")
    stem = connection.execute(
        """
        SELECT stem_cache.*
        FROM stem_cache
        JOIN tracks ON tracks.id = stem_cache.track_id
        WHERE stem_cache.track_id = ? AND stem_cache.stem_kind = ?
          AND stem_cache.model = 'htdemucs'
          AND stem_cache.source_modified_ns = tracks.modified_ns
        """,
        (int(track_id), kind),
    ).fetchone()
    if stem is None:
        raise ValueError(f"The {kind} stem is not separated or its cache is stale.")
    return stem


def _copy_clip_stem_states(connection: Any, source_clip_id: int, target_clip_id: int) -> None:
    connection.execute(
        """
        INSERT INTO clip_stem_states(clip_id, stem_kind, muted, solo)
        SELECT ?, stem_kind, muted, solo
        FROM clip_stem_states WHERE clip_id = ?
        """,
        (int(target_clip_id), int(source_clip_id)),
    )


def _copy_rendered_clip_source(
    connection: Any, source_clip_id: int, target_clip_id: int
) -> None:
    connection.execute(
        """
        INSERT INTO rendered_clip_sources(
            clip_id, render_mode, path, title, file_size, duration_seconds,
            bpm, musical_key, original_clip_json
        )
        SELECT ?, render_mode, path, title, file_size, duration_seconds,
               bpm, musical_key, original_clip_json
        FROM rendered_clip_sources WHERE clip_id = ?
        """,
        (int(target_clip_id), int(source_clip_id)),
    )


def update_clip_stem_state(
    database: Database,
    clip_id: int,
    stem_kind: str,
    *,
    muted: bool | None = None,
    solo: bool | None = None,
) -> dict[str, Any]:
    database.initialize()
    kind = str(stem_kind).strip().casefold()
    if kind not in STEM_KINDS:
        raise ValueError("Stem kind must be vocals, drums, bass or other.")
    if muted is None and solo is None:
        raise ValueError("A stem mute or solo change is required.")
    with database.connect() as connection:
        clip = connection.execute(
            "SELECT * FROM timeline_clips WHERE id = ?", (int(clip_id),)
        ).fetchone()
        if clip is None:
            raise ValueError("Timeline clip was not found.")
        if str(clip["clip_kind"]) != "song":
            raise ValueError("Stem lane mixing is available on full-song clips.")
        _require_cached_stem(connection, int(clip["track_id"]), kind)
        current = connection.execute(
            "SELECT muted, solo FROM clip_stem_states WHERE clip_id = ? AND stem_kind = ?",
            (int(clip_id), kind),
        ).fetchone()
        next_muted = int(bool(muted)) if muted is not None else int(current["muted"] if current else 0)
        next_solo = int(bool(solo)) if solo is not None else int(current["solo"] if current else 0)
        if muted:
            next_solo = 0
        if solo:
            next_muted = 0
        project_id = int(clip["project_id"])
        _record_history(connection, project_id, "stem_mix_updated")
        connection.execute(
            """
            INSERT INTO clip_stem_states(clip_id, stem_kind, muted, solo)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(clip_id, stem_kind) DO UPDATE SET
                muted = excluded.muted,
                solo = excluded.solo,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(clip_id), kind, next_muted, next_solo),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = int(clip_id)
        return result


def set_timeline_clip_source(
    database: Database,
    clip_id: int,
    clip_kind: str,
) -> dict[str, Any]:
    """Switch an existing timeline clip between its song and cached stem sources."""
    database.initialize()
    kind = str(clip_kind).strip().casefold()
    if kind not in {"song", *STEM_KINDS}:
        raise ValueError("Clip source must be the full song, vocals, drums, bass or other.")
    with database.connect() as connection:
        clip = connection.execute(
            "SELECT * FROM timeline_clips WHERE id = ?", (int(clip_id),)
        ).fetchone()
        if clip is None:
            raise ValueError("Timeline clip was not found.")
        if clip["locked"]:
            raise ValueError("Unlock this clip before changing its source.")
        if clip["clip_kind"] == "rendered":
            raise ValueError("Unfreeze this clip before changing its source.")
        if kind in STEM_KINDS:
            _require_cached_stem(connection, int(clip["track_id"]), kind)
        project_id = int(clip["project_id"])
        if str(clip["clip_kind"]) != kind:
            _record_history(connection, project_id, "clip_source_changed")
            connection.execute(
                """
                UPDATE timeline_clips
                SET clip_kind = ?, expanded = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (kind, int(clip_id)),
            )
            connection.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (project_id,),
            )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = int(clip_id)
        return result


def add_stem_to_project(
    database: Database,
    source_clip_id: int,
    stem_kind: str,
    channel: int,
    start_seconds: float | None = None,
) -> dict[str, Any]:
    """Create an independent, fully editable timeline clip from a cached stem."""
    database.initialize()
    kind = str(stem_kind).strip().casefold()
    channel_number = int(channel)
    if channel_number not in {1, 2, 3, 4}:
        raise ValueError("Arrangement channel must be between 1 and 4.")
    with database.connect() as connection:
        clip = connection.execute(
            "SELECT * FROM timeline_clips WHERE id = ?", (int(source_clip_id),)
        ).fetchone()
        if clip is None:
            raise ValueError("Timeline clip was not found.")
        _require_cached_stem(connection, int(clip["track_id"]), kind)
        project_id = int(clip["project_id"])
        start = float(clip["start_seconds"]) if start_seconds is None else round(float(start_seconds), 3)
        if start < 0:
            raise ValueError("Stem clip start time cannot be negative.")
        _record_history(connection, project_id, "stem_clip_added")
        cursor = connection.execute(
            """
            INSERT INTO timeline_clips(
                project_id, track_id, clip_kind, channel, start_seconds,
                source_in_seconds, duration_seconds, gain_db, pan,
                pitch_semitones, tempo_percent, color, expanded, locked,
                muted, solo, loop_enabled, reversed, fade_in_seconds,
                fade_out_seconds, eq_low_db, eq_mid_db, eq_high_db,
                highpass_hz, lowpass_hz, compressor_enabled,
                compressor_threshold_db, compressor_ratio
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, clip["track_id"], kind, channel_number, start,
                clip["source_in_seconds"], clip["duration_seconds"],
                clip["gain_db"], clip["pan"], clip["pitch_semitones"],
                clip["tempo_percent"], CHANNEL_COLORS[channel_number], clip["muted"],
                clip["solo"], clip["loop_enabled"], clip["reversed"],
                clip["fade_in_seconds"], clip["fade_out_seconds"], clip["eq_low_db"],
                clip["eq_mid_db"], clip["eq_high_db"], clip["highpass_hz"],
                clip["lowpass_hz"], clip["compressor_enabled"],
                clip["compressor_threshold_db"], clip["compressor_ratio"],
            ),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (project_id,),
        )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = int(cursor.lastrowid)
        return result


def update_timeline_clip(
    database: Database,
    clip_id: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    database.initialize()
    unknown = set(changes) - EDITABLE_CLIP_FIELDS
    if unknown:
        raise ValueError(f"Unsupported clip fields: {', '.join(sorted(unknown))}")
    updates: list[str] = []
    values: list[Any] = []
    normalized_changes: dict[str, Any] = {}
    numeric_ranges = {
        "channel": (1, 4),
        "start_seconds": (0, None),
        "source_in_seconds": (0, None),
        "duration_seconds": (0.001, None),
        "gain_db": (-60, 12),
        "pan": (-1, 1),
        "pitch_semitones": (-24, 24),
        "tempo_percent": (25, 400),
        "fade_in_seconds": (0, None),
        "fade_out_seconds": (0, None),
        "eq_low_db": (-12, 12),
        "eq_mid_db": (-12, 12),
        "eq_high_db": (-12, 12),
        "highpass_hz": (20, 20000),
        "lowpass_hz": (20, 20000),
        "compressor_threshold_db": (-60, 0),
        "compressor_ratio": (1, 20),
    }
    boolean_fields = {
        "expanded", "locked", "muted", "solo", "loop_enabled", "reversed",
        "compressor_enabled",
    }
    for field, value in changes.items():
        if value is None:
            continue
        if field in numeric_ranges:
            number = float(value)
            minimum, maximum = numeric_ranges[field]
            if number < minimum or (maximum is not None and number > maximum):
                raise ValueError(f"{field.replace('_', ' ').title()} is outside its safe range.")
            if field == "channel":
                value = int(number)
            elif field == "tempo_percent":
                value = round(number, 6)
            else:
                value = round(number, 3)
        elif field in boolean_fields:
            value = int(bool(value))
        elif field == "color":
            value = str(value).strip().casefold()
            if value not in SUPPORTED_COLORS:
                raise ValueError("Clip colour is not supported.")
        updates.append(f"{field} = ?")
        values.append(value)
        normalized_changes[field] = value
    if not updates:
        raise ValueError("No clip changes were provided.")
    with database.connect() as connection:
        clip = connection.execute(
            """
            SELECT timeline_clips.*, tracks.duration_seconds AS source_duration_seconds
            FROM timeline_clips
            JOIN tracks ON tracks.id = timeline_clips.track_id
            WHERE timeline_clips.id = ?
            """,
            (int(clip_id),),
        ).fetchone()
        if clip is None:
            raise ValueError("Timeline clip was not found.")
        if clip["locked"] and any(field in changes for field in {"channel", "start_seconds"}):
            raise ValueError("Unlock this clip before moving it.")
        if "tempo_percent" in normalized_changes and "duration_seconds" not in normalized_changes:
            old_span = _source_span(clip["duration_seconds"], clip["tempo_percent"])
            adjusted_duration = round(
                old_span / _tempo_factor(normalized_changes["tempo_percent"]), 6
            )
            normalized_changes["duration_seconds"] = adjusted_duration
            updates.append("duration_seconds = ?")
            values.append(adjusted_duration)
        source_in = float(normalized_changes.get("source_in_seconds", clip["source_in_seconds"]))
        duration = float(normalized_changes.get("duration_seconds", clip["duration_seconds"]))
        tempo_percent = float(normalized_changes.get("tempo_percent", clip["tempo_percent"]))
        source_span = _source_span(duration, tempo_percent)
        source_duration = float(clip["source_duration_seconds"] or 0)
        if source_duration <= 0 or source_in + source_span > source_duration + 0.001:
            raise ValueError("Trim range exceeds the source track duration.")
        fade_in = float(normalized_changes.get("fade_in_seconds", clip["fade_in_seconds"]))
        fade_out = float(normalized_changes.get("fade_out_seconds", clip["fade_out_seconds"]))
        if fade_in + fade_out > duration + 0.001:
            raise ValueError("Combined fades cannot exceed the clip duration.")
        highpass = float(normalized_changes.get("highpass_hz", clip["highpass_hz"]))
        lowpass = float(normalized_changes.get("lowpass_hz", clip["lowpass_hz"]))
        if highpass >= lowpass:
            raise ValueError("High-pass frequency must remain below the low-pass frequency.")
        project_id = int(clip["project_id"])
        _record_history(connection, project_id, "clip_updated")
        if clip["group_id"] is not None and "start_seconds" in normalized_changes:
            delta = float(normalized_changes["start_seconds"]) - float(clip["start_seconds"])
            minimum = connection.execute(
                "SELECT MIN(start_seconds) AS value FROM timeline_clips WHERE project_id = ? AND group_id = ?",
                (project_id, clip["group_id"]),
            ).fetchone()["value"]
            if float(minimum) + delta < 0:
                raise ValueError("Grouped clips cannot move before the timeline start.")
            connection.execute(
                """
                UPDATE timeline_clips SET start_seconds = ROUND(start_seconds + ?, 3),
                    updated_at = CURRENT_TIMESTAMP
                WHERE project_id = ? AND group_id = ? AND id <> ?
                """,
                (delta, project_id, clip["group_id"], int(clip_id)),
            )
        values.append(int(clip_id))
        connection.execute(
            f"UPDATE timeline_clips SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            tuple(values),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        return _project_result(connection, project_id)


def resize_timeline_clip(
    database: Database,
    clip_id: int,
    edge: str,
    boundary_seconds: float,
) -> dict[str, Any]:
    database.initialize()
    normalized_edge = str(edge).strip().casefold()
    if normalized_edge not in {"start", "end"}:
        raise ValueError("Clip resize edge must be start or end.")
    boundary = round(float(boundary_seconds), 3)
    if not math.isfinite(boundary):
        raise ValueError("Clip resize boundary must be a finite timeline position.")
    with database.connect() as connection:
        clip = connection.execute(
            """
            SELECT timeline_clips.*, tracks.duration_seconds AS source_duration_seconds
            FROM timeline_clips
            JOIN tracks ON tracks.id = timeline_clips.track_id
            WHERE timeline_clips.id = ?
            """,
            (int(clip_id),),
        ).fetchone()
        if clip is None:
            raise ValueError("Timeline clip was not found.")
        if clip["locked"]:
            raise ValueError("Unlock this clip before resizing it.")

        project_id = int(clip["project_id"])
        start = float(clip["start_seconds"])
        source_in = float(clip["source_in_seconds"])
        duration = float(clip["duration_seconds"])
        tempo_factor = _tempo_factor(clip["tempo_percent"])
        source_span = duration * tempo_factor
        end = start + duration
        source_duration = float(clip["source_duration_seconds"] or 0)
        reversed_clip = bool(clip["reversed"])
        minimum_duration = max(
            0.05,
            float(clip["fade_in_seconds"]) + float(clip["fade_out_seconds"]),
        )
        tolerance = 0.001
        if source_duration <= 0:
            raise ValueError("Source track duration is unavailable.")

        if normalized_edge == "start":
            available_before = max(0.0, (
                (source_duration - (source_in + source_span)) / tempo_factor
                if reversed_clip
                else source_in / tempo_factor
            ))
            minimum_boundary = max(0.0, start - available_before)
            maximum_boundary = end - minimum_duration
            if boundary < minimum_boundary - tolerance:
                raise ValueError("Clip start cannot extend beyond the available source audio.")
            if boundary > maximum_boundary + tolerance:
                raise ValueError("Clip resize would make the clip shorter than its fades allow.")
            boundary = min(max(boundary, minimum_boundary), maximum_boundary)
            delta = boundary - start
            new_start = boundary
            new_duration = duration - delta
            new_source_in = source_in if reversed_clip else source_in + delta * tempo_factor
        else:
            available_after = max(
                0.0,
                source_in / tempo_factor
                if reversed_clip
                else (source_duration - (source_in + source_span)) / tempo_factor,
            )
            minimum_boundary = start + minimum_duration
            maximum_boundary = end + available_after
            if boundary < minimum_boundary - tolerance:
                raise ValueError("Clip resize would make the clip shorter than its fades allow.")
            if boundary > maximum_boundary + tolerance:
                raise ValueError("Clip end cannot extend beyond the available source audio.")
            boundary = min(max(boundary, minimum_boundary), maximum_boundary)
            delta = boundary - end
            new_start = start
            new_duration = duration + delta
            new_source_in = source_in - delta * tempo_factor if reversed_clip else source_in

        new_start = round(new_start, 3)
        new_source_in = round(new_source_in, 3)
        new_duration = round(new_duration, 3)
        if (
            new_source_in < -tolerance
            or new_source_in + new_duration * tempo_factor > source_duration + tolerance
        ):
            raise ValueError("Clip resize exceeds the source track duration.")
        if new_duration < minimum_duration - tolerance:
            raise ValueError("Clip resize would make the clip shorter than its fades allow.")
        if (
            abs(new_start - start) < tolerance
            and abs(new_source_in - source_in) < tolerance
            and abs(new_duration - duration) < tolerance
        ):
            result = _project_result(connection, project_id)
            result["selected_clip_id"] = int(clip_id)
            return result

        _record_history(connection, project_id, "clip_resized")
        connection.execute(
            """
            UPDATE timeline_clips
            SET start_seconds = ?, source_in_seconds = ?, duration_seconds = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_start, max(0.0, new_source_in), new_duration, int(clip_id)),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = int(clip_id)
        return result


def duplicate_timeline_clip(database: Database, clip_id: int) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        clip = connection.execute(
            "SELECT * FROM timeline_clips WHERE id = ?", (int(clip_id),)
        ).fetchone()
        if clip is None:
            raise ValueError("Timeline clip was not found.")
        project_id = int(clip["project_id"])
        _record_history(connection, project_id, "clip_duplicated")
        cursor = connection.execute(
            """
            INSERT INTO timeline_clips(
                project_id, track_id, parent_clip_id, clip_kind, channel,
                start_seconds, source_in_seconds, duration_seconds, gain_db, pan,
                pitch_semitones, tempo_percent, color, expanded, locked, muted, solo,
                loop_enabled, reversed, fade_in_seconds, fade_out_seconds
                , eq_low_db, eq_mid_db, eq_high_db, highpass_hz, lowpass_hz,
                compressor_enabled, compressor_threshold_db, compressor_ratio
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, clip["track_id"], clip["parent_clip_id"], clip["clip_kind"],
                clip["channel"], float(clip["start_seconds"]) + float(clip["duration_seconds"]),
                clip["source_in_seconds"], clip["duration_seconds"], clip["gain_db"],
                clip["pan"], clip["pitch_semitones"], clip["tempo_percent"], clip["color"],
                clip["expanded"], clip["muted"], clip["solo"], clip["loop_enabled"],
                clip["reversed"], clip["fade_in_seconds"], clip["fade_out_seconds"],
                clip["eq_low_db"], clip["eq_mid_db"], clip["eq_high_db"],
                clip["highpass_hz"], clip["lowpass_hz"], clip["compressor_enabled"],
                clip["compressor_threshold_db"], clip["compressor_ratio"],
            ),
        )
        _copy_clip_stem_states(connection, int(clip_id), int(cursor.lastrowid))
        _copy_rendered_clip_source(connection, int(clip_id), int(cursor.lastrowid))
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = int(cursor.lastrowid)
        return result


def split_timeline_clip(
    database: Database,
    clip_id: int,
    offset_seconds: float,
) -> dict[str, Any]:
    database.initialize()
    offset = round(float(offset_seconds), 3)
    with database.connect() as connection:
        clip = connection.execute(
            "SELECT * FROM timeline_clips WHERE id = ?", (int(clip_id),)
        ).fetchone()
        if clip is None:
            raise ValueError("Timeline clip was not found.")
        if clip["locked"]:
            raise ValueError("Unlock this clip before splitting it.")
        original_duration = float(clip["duration_seconds"])
        if offset < 0.05 or offset > original_duration - 0.05:
            raise ValueError("Split point must be inside the clip with room on both sides.")
        remaining = round(original_duration - offset, 3)
        original_source_in = float(clip["source_in_seconds"])
        tempo_factor = _tempo_factor(clip["tempo_percent"])
        reversed_clip = bool(clip["reversed"])
        left_source_in = (
            round(original_source_in + remaining * tempo_factor, 3)
            if reversed_clip else original_source_in
        )
        right_source_in = (
            original_source_in
            if reversed_clip
            else round(original_source_in + offset * tempo_factor, 3)
        )
        project_id = int(clip["project_id"])
        _record_history(connection, project_id, "clip_split")
        connection.execute(
            """
            UPDATE timeline_clips
            SET source_in_seconds = ?, duration_seconds = ?, loop_enabled = 0,
                fade_in_seconds = MIN(fade_in_seconds, ?), fade_out_seconds = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (left_source_in, offset, offset, int(clip_id)),
        )
        cursor = connection.execute(
            """
            INSERT INTO timeline_clips(
                project_id, track_id, parent_clip_id, clip_kind, channel,
                start_seconds, source_in_seconds, duration_seconds, gain_db, pan,
                pitch_semitones, tempo_percent, color, expanded, locked, muted, solo,
                loop_enabled, reversed, fade_in_seconds, fade_out_seconds
                , eq_low_db, eq_mid_db, eq_high_db, highpass_hz, lowpass_hz,
                compressor_enabled, compressor_threshold_db, compressor_ratio
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, clip["track_id"], clip["parent_clip_id"], clip["clip_kind"],
                clip["channel"], round(float(clip["start_seconds"]) + offset, 3),
                right_source_in, remaining, clip["gain_db"], clip["pan"],
                clip["pitch_semitones"], clip["tempo_percent"], clip["color"],
                clip["expanded"], clip["muted"], clip["solo"], clip["reversed"],
                min(float(clip["fade_out_seconds"]), remaining),
                clip["eq_low_db"], clip["eq_mid_db"], clip["eq_high_db"],
                clip["highpass_hz"], clip["lowpass_hz"], clip["compressor_enabled"],
                clip["compressor_threshold_db"], clip["compressor_ratio"],
            ),
        )
        _copy_clip_stem_states(connection, int(clip_id), int(cursor.lastrowid))
        _copy_rendered_clip_source(connection, int(clip_id), int(cursor.lastrowid))
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = int(cursor.lastrowid)
        return result


def quantize_timeline_clip(database: Database, clip_id: int) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        clip = connection.execute(
            """
            SELECT timeline_clips.*, projects.tempo, projects.snap_beats
            FROM timeline_clips
            JOIN projects ON projects.id = timeline_clips.project_id
            WHERE timeline_clips.id = ?
            """,
            (int(clip_id),),
        ).fetchone()
        if clip is None:
            raise ValueError("Timeline clip was not found.")
        if clip["locked"]:
            raise ValueError("Unlock this clip before quantising it.")
        grid_seconds = (60 / float(clip["tempo"])) * float(clip["snap_beats"])
        quantized = round(round(float(clip["start_seconds"]) / grid_seconds) * grid_seconds, 3)
        project_id = int(clip["project_id"])
        _record_history(connection, project_id, "clip_quantized")
        connection.execute(
            "UPDATE timeline_clips SET start_seconds = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (max(0, quantized), int(clip_id)),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = int(clip_id)
        return result


def crossfade_timeline_clips(
    database: Database,
    clip_id: int,
    target_clip_id: int,
) -> dict[str, Any]:
    database.initialize()
    if int(clip_id) == int(target_clip_id):
        raise ValueError("Choose two different clips for a crossfade.")
    with database.connect() as connection:
        clips = connection.execute(
            "SELECT * FROM timeline_clips WHERE id IN (?, ?)",
            (int(clip_id), int(target_clip_id)),
        ).fetchall()
        if len(clips) != 2:
            raise ValueError("Both crossfade clips must exist.")
        if len({int(clip["project_id"]) for clip in clips}) != 1:
            raise ValueError("Crossfade clips must belong to the same project.")
        ordered = sorted(clips, key=lambda clip: (float(clip["start_seconds"]), int(clip["id"])))
        outgoing, incoming = ordered
        if abs(float(outgoing["start_seconds"]) - float(incoming["start_seconds"])) < 0.001:
            raise ValueError("Crossfade clips need different start positions.")
        overlap = (
            float(outgoing["start_seconds"])
            + float(outgoing["duration_seconds"])
            - float(incoming["start_seconds"])
        )
        if overlap <= 0.001:
            raise ValueError("Crossfade clips must overlap on the timeline.")
        outgoing_available = float(outgoing["duration_seconds"]) - float(outgoing["fade_in_seconds"])
        incoming_available = float(incoming["duration_seconds"]) - float(incoming["fade_out_seconds"])
        fade_duration = round(min(overlap, outgoing_available, incoming_available), 3)
        if fade_duration <= 0:
            raise ValueError("Existing fades leave no room for this crossfade.")
        project_id = int(outgoing["project_id"])
        _record_history(connection, project_id, "clips_crossfaded")
        connection.execute(
            "UPDATE timeline_clips SET fade_out_seconds = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (fade_duration, int(outgoing["id"])),
        )
        connection.execute(
            "UPDATE timeline_clips SET fade_in_seconds = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (fade_duration, int(incoming["id"])),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = int(clip_id)
        return result


def create_project_marker(
    database: Database,
    project_id: int,
    marker_kind: str,
    name: str,
    start_seconds: float,
    end_seconds: float | None = None,
    color: str = "violet",
) -> dict[str, Any]:
    database.initialize()
    kind = marker_kind.strip().casefold()
    if kind not in {"marker", "section"}:
        raise ValueError("Marker type is not supported.")
    start = round(float(start_seconds), 3)
    if start < 0:
        raise ValueError("Marker start cannot be negative.")
    end = round(float(end_seconds), 3) if end_seconds is not None else None
    if kind == "marker":
        end = None
    elif end is None or end <= start:
        raise ValueError("Section end must be after its start.")
    marker_color = color.strip().casefold()
    if marker_color not in SUPPORTED_COLORS:
        raise ValueError("Marker colour is not supported.")
    with database.connect() as connection:
        _project_snapshot(connection, int(project_id))
        _record_history(connection, int(project_id), f"{kind}_created")
        cursor = connection.execute(
            """
            INSERT INTO project_markers(project_id, marker_kind, name, start_seconds, end_seconds, color)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(project_id), kind, _validate_marker_name(name), start, end, marker_color),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (int(project_id),)
        )
        result = _project_result(connection, int(project_id))
        result["selected_marker_id"] = int(cursor.lastrowid)
        return result


def update_project_marker(
    database: Database,
    marker_id: int,
    changes: dict[str, Any],
) -> dict[str, Any]:
    database.initialize()
    unknown = set(changes) - {"name", "start_seconds", "end_seconds", "color"}
    if unknown:
        raise ValueError(f"Unsupported marker fields: {', '.join(sorted(unknown))}")
    with database.connect() as connection:
        marker = connection.execute(
            "SELECT * FROM project_markers WHERE id = ?", (int(marker_id),)
        ).fetchone()
        if marker is None:
            raise ValueError("Project marker was not found.")
        name = _validate_marker_name(str(changes.get("name", marker["name"])))
        start = round(float(changes.get("start_seconds", marker["start_seconds"])), 3)
        if start < 0:
            raise ValueError("Marker start cannot be negative.")
        if marker["marker_kind"] == "section":
            end = round(float(changes.get("end_seconds", marker["end_seconds"])), 3)
            if end <= start:
                raise ValueError("Section end must be after its start.")
        else:
            end = None
        color = str(changes.get("color", marker["color"])).strip().casefold()
        if color not in SUPPORTED_COLORS:
            raise ValueError("Marker colour is not supported.")
        project_id = int(marker["project_id"])
        _record_history(connection, project_id, f"{marker['marker_kind']}_updated")
        connection.execute(
            """
            UPDATE project_markers
            SET name = ?, start_seconds = ?, end_seconds = ?, color = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name, start, end, color, int(marker_id)),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        result = _project_result(connection, project_id)
        result["selected_marker_id"] = int(marker_id)
        return result


def delete_project_marker(database: Database, marker_id: int) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        marker = connection.execute(
            "SELECT project_id, marker_kind FROM project_markers WHERE id = ?", (int(marker_id),)
        ).fetchone()
        if marker is None:
            raise ValueError("Project marker was not found.")
        project_id = int(marker["project_id"])
        _record_history(connection, project_id, f"{marker['marker_kind']}_deleted")
        connection.execute("DELETE FROM project_markers WHERE id = ?", (int(marker_id),))
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        return _project_result(connection, project_id)


def group_timeline_clips(database: Database, clip_ids: list[int]) -> dict[str, Any]:
    database.initialize()
    ids = sorted({int(value) for value in clip_ids})
    if len(ids) < 2:
        raise ValueError("Select at least two clips to create a group.")
    with database.connect() as connection:
        placeholders = ",".join("?" for _ in ids)
        clips = connection.execute(
            f"SELECT id, project_id FROM timeline_clips WHERE id IN ({placeholders})", tuple(ids)
        ).fetchall()
        if len(clips) != len(ids) or len({clip["project_id"] for clip in clips}) != 1:
            raise ValueError("Grouped clips must exist in the same project.")
        project_id = int(clips[0]["project_id"])
        group_id = int(connection.execute(
            "SELECT COALESCE(MAX(group_id), 0) + 1 AS value FROM timeline_clips WHERE project_id = ?",
            (project_id,),
        ).fetchone()["value"])
        _record_history(connection, project_id, "clips_grouped")
        connection.execute(
            f"UPDATE timeline_clips SET group_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            (group_id, *ids),
        )
        result = _project_result(connection, project_id)
        result["selected_clip_ids"] = ids
        return result


def ungroup_timeline_clips(database: Database, project_id: int, group_id: int) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS value FROM timeline_clips WHERE project_id = ? AND group_id = ?",
            (int(project_id), int(group_id)),
        ).fetchone()["value"]
        if not count:
            raise ValueError("Clip group was not found.")
        _record_history(connection, int(project_id), "clips_ungrouped")
        connection.execute(
            "UPDATE timeline_clips SET group_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE project_id = ? AND group_id = ?",
            (int(project_id), int(group_id)),
        )
        return _project_result(connection, int(project_id))


def batch_update_timeline_clips(
    database: Database, clip_ids: list[int], changes: dict[str, Any]
) -> dict[str, Any]:
    database.initialize()
    ids = sorted({int(value) for value in clip_ids})
    if not ids:
        raise ValueError("Select at least one clip to edit.")
    allowed = {"gain_db", "pan", "pitch_semitones", "tempo_percent", "color", "muted", "solo", "locked"}
    unknown = set(changes) - allowed
    if unknown or not changes:
        raise ValueError("Batch clip changes contain unsupported fields.")
    normalized: dict[str, Any] = {}
    ranges = {"gain_db": (-60, 12), "pan": (-1, 1), "pitch_semitones": (-24, 24), "tempo_percent": (25, 400)}
    for field, value in changes.items():
        if field in ranges:
            number = round(float(value), 6 if field == "tempo_percent" else 3)
            minimum, maximum = ranges[field]
            if number < minimum or number > maximum:
                raise ValueError(f"{field.replace('_', ' ').title()} is outside its safe range.")
            normalized[field] = number
        elif field == "color":
            color = str(value).strip().casefold()
            if color not in SUPPORTED_COLORS:
                raise ValueError("Clip colour is not supported.")
            normalized[field] = color
        else:
            normalized[field] = int(bool(value))
    with database.connect() as connection:
        placeholders = ",".join("?" for _ in ids)
        clips = connection.execute(
            f"""
            SELECT timeline_clips.id, timeline_clips.project_id,
                timeline_clips.source_in_seconds, timeline_clips.duration_seconds,
                timeline_clips.tempo_percent,
                tracks.duration_seconds AS source_duration_seconds
            FROM timeline_clips
            JOIN tracks ON tracks.id = timeline_clips.track_id
            WHERE timeline_clips.id IN ({placeholders})
            """,
            tuple(ids),
        ).fetchall()
        if len(clips) != len(ids) or len({clip["project_id"] for clip in clips}) != 1:
            raise ValueError("Selected clips must exist in the same project.")
        project_id = int(clips[0]["project_id"])
        _record_history(connection, project_id, "clips_batch_updated")
        if "tempo_percent" in normalized:
            new_tempo = float(normalized["tempo_percent"])
            for clip in clips:
                old_span = _source_span(clip["duration_seconds"], clip["tempo_percent"])
                new_duration = round(old_span / _tempo_factor(new_tempo), 6)
                if (
                    float(clip["source_in_seconds"]) + old_span
                    > float(clip["source_duration_seconds"] or 0) + 0.001
                ):
                    raise ValueError("Tempo change exceeds a source track duration.")
                clip_changes = {**normalized, "duration_seconds": new_duration}
                assignments = ", ".join(f"{field} = ?" for field in clip_changes)
                connection.execute(
                    f"UPDATE timeline_clips SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (*clip_changes.values(), int(clip["id"])),
                )
        else:
            assignments = ", ".join(f"{field} = ?" for field in normalized)
            connection.execute(
                f"UPDATE timeline_clips SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                (*normalized.values(), *ids),
            )
        result = _project_result(connection, project_id)
        result["selected_clip_ids"] = ids
        return result


def shift_timeline_group_channels(
    database: Database, project_id: int, group_id: int, delta: int
) -> dict[str, Any]:
    database.initialize()
    shift = int(delta)
    if shift not in {-1, 1}:
        raise ValueError("Group channel shift must be -1 or 1.")
    with database.connect() as connection:
        clips = connection.execute(
            "SELECT id, channel, locked FROM timeline_clips WHERE project_id = ? AND group_id = ?",
            (int(project_id), int(group_id)),
        ).fetchall()
        if not clips:
            raise ValueError("Clip group was not found.")
        if any(clip["locked"] for clip in clips):
            raise ValueError("Unlock every grouped clip before shifting channels.")
        if any(int(clip["channel"]) + shift not in {1, 2, 3, 4} for clip in clips):
            raise ValueError("The group cannot move beyond channels 1 to 4.")
        _record_history(connection, int(project_id), "group_channels_shifted")
        connection.execute(
            "UPDATE timeline_clips SET channel = channel + ?, updated_at = CURRENT_TIMESTAMP WHERE project_id = ? AND group_id = ?",
            (shift, int(project_id), int(group_id)),
        )
        result = _project_result(connection, int(project_id))
        result["selected_clip_ids"] = [int(clip["id"]) for clip in clips]
        return result


def delete_timeline_clips(database: Database, clip_ids: list[int]) -> dict[str, Any]:
    database.initialize()
    ids = sorted({int(value) for value in clip_ids})
    if not ids:
        raise ValueError("Select at least one clip to delete.")
    with database.connect() as connection:
        placeholders = ",".join("?" for _ in ids)
        clips = connection.execute(
            f"SELECT id, project_id, locked FROM timeline_clips WHERE id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
        if len(clips) != len(ids) or len({clip["project_id"] for clip in clips}) != 1:
            raise ValueError("Selected clips must exist in the same project.")
        if any(clip["locked"] for clip in clips):
            raise ValueError("Unlock selected clips before deleting them.")
        project_id = int(clips[0]["project_id"])
        _record_history(connection, project_id, "clips_deleted")
        connection.execute(f"DELETE FROM timeline_clips WHERE id IN ({placeholders})", tuple(ids))
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        return _project_result(connection, project_id)


def trim_timeline_clips_to_selection(
    database: Database, clip_ids: list[int], start_seconds: float, end_seconds: float
) -> dict[str, Any]:
    database.initialize()
    ids = sorted({int(value) for value in clip_ids})
    start = round(float(start_seconds), 3)
    end = round(float(end_seconds), 3)
    if not ids or start < 0 or end <= start:
        raise ValueError("A valid selection and at least one clip are required.")
    with database.connect() as connection:
        placeholders = ",".join("?" for _ in ids)
        clips = connection.execute(
            f"SELECT * FROM timeline_clips WHERE id IN ({placeholders})", tuple(ids)
        ).fetchall()
        if len(clips) != len(ids) or len({clip["project_id"] for clip in clips}) != 1:
            raise ValueError("Selected clips must exist in the same project.")
        if any(clip["locked"] for clip in clips):
            raise ValueError("Unlock selected clips before trimming them.")
        if any(max(start, float(clip["start_seconds"])) >= min(end, float(clip["start_seconds"]) + float(clip["duration_seconds"])) for clip in clips):
            raise ValueError("Every selected clip must overlap the timeline selection.")
        project_id = int(clips[0]["project_id"])
        _record_history(connection, project_id, "clips_trimmed_to_selection")
        for clip in clips:
            clip_start = float(clip["start_seconds"])
            clip_end = clip_start + float(clip["duration_seconds"])
            new_start = max(start, clip_start)
            new_end = min(end, clip_end)
            trim_left = new_start - clip_start
            trim_right = clip_end - new_end
            duration = round(new_end - new_start, 3)
            source_in = float(clip["source_in_seconds"])
            tempo_factor = _tempo_factor(clip["tempo_percent"])
            if clip["reversed"]:
                source_in = round(source_in + trim_right * tempo_factor, 3)
            else:
                source_in = round(source_in + trim_left * tempo_factor, 3)
            fade_in = min(float(clip["fade_in_seconds"]), duration)
            fade_out = min(float(clip["fade_out_seconds"]), max(0, duration - fade_in))
            connection.execute(
                """
                UPDATE timeline_clips SET start_seconds = ?, source_in_seconds = ?,
                    duration_seconds = ?, fade_in_seconds = ?, fade_out_seconds = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (round(new_start, 3), source_in, duration, fade_in, fade_out, int(clip["id"])),
            )
        result = _project_result(connection, project_id)
        result["selected_clip_ids"] = ids
        return result


def update_project_selection(
    database: Database,
    project_id: int,
    start_seconds: float | None,
    end_seconds: float | None,
    loop_enabled: bool = False,
) -> dict[str, Any]:
    database.initialize()
    start = None if start_seconds is None else round(float(start_seconds), 3)
    end = None if end_seconds is None else round(float(end_seconds), 3)
    if (start is None) != (end is None):
        raise ValueError("Selection start and end must be set together.")
    if start is not None and (start < 0 or end is None or end <= start):
        raise ValueError("Selection end must be after its non-negative start.")
    with database.connect() as connection:
        _project_snapshot(connection, int(project_id))
        _record_history(connection, int(project_id), "selection_updated")
        connection.execute(
            """
            UPDATE projects
            SET selection_start_seconds = ?, selection_end_seconds = ?,
                selection_loop_enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (start, end, int(bool(loop_enabled and start is not None)), int(project_id)),
        )
        return _project_result(connection, int(project_id))


def undo_project(database: Database, project_id: int) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT id, action, snapshot_json FROM project_history
            WHERE project_id = ? AND action <> 'created' ORDER BY id DESC LIMIT 1
            """,
            (int(project_id),),
        ).fetchone()
        if row is None:
            raise ValueError("There is nothing to undo.")
        current = _project_snapshot(connection, int(project_id))
        connection.execute(
            "INSERT INTO project_redo_history(project_id, action, snapshot_json) VALUES (?, ?, ?)",
            (int(project_id), row["action"], json.dumps(current, ensure_ascii=False, separators=(",", ":"))),
        )
        connection.execute("DELETE FROM project_history WHERE id = ?", (int(row["id"]),))
        _restore_project_snapshot(connection, int(project_id), json.loads(row["snapshot_json"]))
        return _project_result(connection, int(project_id))


def redo_project(database: Database, project_id: int) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT id, action, snapshot_json FROM project_redo_history
            WHERE project_id = ? ORDER BY id DESC LIMIT 1
            """,
            (int(project_id),),
        ).fetchone()
        if row is None:
            raise ValueError("There is nothing to redo.")
        current = _project_snapshot(connection, int(project_id))
        connection.execute(
            "INSERT INTO project_history(project_id, action, snapshot_json) VALUES (?, ?, ?)",
            (int(project_id), row["action"], json.dumps(current, ensure_ascii=False, separators=(",", ":"))),
        )
        connection.execute("DELETE FROM project_redo_history WHERE id = ?", (int(row["id"]),))
        _restore_project_snapshot(connection, int(project_id), json.loads(row["snapshot_json"]))
        return _project_result(connection, int(project_id))


def list_project_history(database: Database, project_id: int) -> list[dict[str, Any]]:
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT id, project_id, action, created_at
            FROM project_history WHERE project_id = ? ORDER BY id DESC
            """,
            (int(project_id),),
        ).fetchall()
    return [dict(row) for row in rows]
