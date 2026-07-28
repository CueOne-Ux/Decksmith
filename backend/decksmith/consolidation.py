from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from .database import Database
from .projects import CHANNEL_COLORS, _project_result, _record_history
from .rendering import render_status


ORIGINAL_SOURCE_FIELDS = (
    "clip_kind",
    "source_in_seconds",
    "duration_seconds",
    "pitch_semitones",
    "tempo_percent",
    "reversed",
    "expanded",
)


def _prepared_render(database: Database, clip_id: int) -> dict[str, Any]:
    status = render_status(database, [int(clip_id)])
    render = next(
        (item for item in status["renders"] if int(item["clip_id"]) == int(clip_id)),
        None,
    )
    if render is None:
        raise ValueError("This clip is still preparing. Try freeze or bounce when its audio is ready.")
    source = Path(render["path"])
    if not source.is_file() or source.stat().st_size != int(render["file_size"]):
        raise ValueError("The prepared clip audio is unavailable. Let Decksmith prepare it again.")
    return render


def _publish_source(
    render: dict[str, Any], destination_directory: str | Path, *, label: str
) -> Path:
    destination_root = Path(destination_directory).expanduser().resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    source = Path(render["path"])
    destination = destination_root / (
        f"{label}-clip-{int(render['clip_id'])}-{str(render['signature'])[:12]}-"
        f"{uuid.uuid4().hex[:10]}.wav"
    )
    working = destination.with_suffix(".working")
    shutil.copy2(source, working)
    if working.stat().st_size != int(render["file_size"]):
        working.unlink(missing_ok=True)
        raise RuntimeError("Decksmith could not verify the consolidated audio copy.")
    working.replace(destination)
    return destination


def _source_metadata(connection: Any, clip: Any) -> tuple[float | None, str]:
    track = connection.execute(
        "SELECT bpm, musical_key FROM tracks WHERE id = ?", (int(clip["track_id"]),)
    ).fetchone()
    bpm = None
    if track is not None and track["bpm"] is not None:
        bpm = round(float(track["bpm"]) * float(clip["tempo_percent"]) / 100.0, 3)
    # Pitch is baked into the consolidated file. Leaving the key blank is safer than
    # presenting the original track key as if it were still exact.
    return bpm, ""


def freeze_timeline_clip(
    database: Database, clip_id: int, destination_directory: str | Path
) -> dict[str, Any]:
    """Pin a clip's prepared PCM source while keeping live mixer controls editable."""
    database.initialize()
    with database.connect() as connection:
        clip = connection.execute(
            "SELECT * FROM timeline_clips WHERE id = ?", (int(clip_id),)
        ).fetchone()
        if clip is None:
            raise ValueError("Timeline clip was not found.")
        if clip["locked"]:
            raise ValueError("Unlock this clip before freezing it.")
        if clip["clip_kind"] == "rendered":
            source = connection.execute(
                "SELECT render_mode FROM rendered_clip_sources WHERE clip_id = ?",
                (int(clip_id),),
            ).fetchone()
            if source and source["render_mode"] == "freeze":
                result = _project_result(connection, int(clip["project_id"]))
                result["selected_clip_id"] = int(clip_id)
                return result
            raise ValueError("This bounced clip is already consolidated audio.")
    render = _prepared_render(database, int(clip_id))
    destination = _publish_source(render, destination_directory, label="freeze")
    if _prepared_render(database, int(clip_id))["signature"] != render["signature"]:
        destination.unlink(missing_ok=True)
        raise ValueError("The clip changed while it was being frozen. Try again with the current edit.")
    with database.connect() as connection:
        clip = connection.execute(
            "SELECT * FROM timeline_clips WHERE id = ?", (int(clip_id),)
        ).fetchone()
        if clip is None:
            destination.unlink(missing_ok=True)
            raise ValueError("Timeline clip was not found.")
        project_id = int(clip["project_id"])
        track = connection.execute(
            "SELECT title FROM tracks WHERE id = ?", (int(clip["track_id"]),)
        ).fetchone()
        bpm, musical_key = _source_metadata(connection, clip)
        original = {field: clip[field] for field in ORIGINAL_SOURCE_FIELDS}
        _record_history(connection, project_id, "clip_frozen")
        connection.execute(
            """
            UPDATE timeline_clips
            SET clip_kind = 'rendered', source_in_seconds = 0,
                pitch_semitones = 0, tempo_percent = 100, reversed = 0,
                expanded = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(clip_id),),
        )
        connection.execute(
            """
            INSERT INTO rendered_clip_sources(
                clip_id, render_mode, path, title, file_size, duration_seconds,
                bpm, musical_key, original_clip_json
            ) VALUES (?, 'freeze', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(clip_id), str(destination), f"{track['title']} · Frozen",
                destination.stat().st_size, float(clip["duration_seconds"]), bpm,
                musical_key, json.dumps(original, separators=(",", ":")),
            ),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = int(clip_id)
        return result


def unfreeze_timeline_clip(database: Database, clip_id: int) -> dict[str, Any]:
    """Restore the non-destructive source settings saved by freeze."""
    database.initialize()
    with database.connect() as connection:
        clip = connection.execute(
            "SELECT * FROM timeline_clips WHERE id = ?", (int(clip_id),)
        ).fetchone()
        source = connection.execute(
            "SELECT * FROM rendered_clip_sources WHERE clip_id = ?", (int(clip_id),)
        ).fetchone()
        if clip is None:
            raise ValueError("Timeline clip was not found.")
        if clip["locked"]:
            raise ValueError("Unlock this clip before unfreezing it.")
        if source is None or source["render_mode"] != "freeze" or not source["original_clip_json"]:
            raise ValueError("Only a frozen source clip can be unfrozen.")
        original = json.loads(source["original_clip_json"])
        project_id = int(clip["project_id"])
        _record_history(connection, project_id, "clip_unfrozen")
        fields = [field for field in ORIGINAL_SOURCE_FIELDS if field in original]
        connection.execute(
            f"UPDATE timeline_clips SET {', '.join(f'{field} = ?' for field in fields)}, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            tuple(original[field] for field in fields) + (int(clip_id),),
        )
        connection.execute(
            "DELETE FROM rendered_clip_sources WHERE clip_id = ?", (int(clip_id),)
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = int(clip_id)
        return result


def bounce_timeline_clip(
    database: Database, clip_id: int, destination_directory: str | Path
) -> dict[str, Any]:
    """Create a stable rendered copy immediately after the selected source clip."""
    database.initialize()
    render = _prepared_render(database, int(clip_id))
    destination = _publish_source(render, destination_directory, label="bounce")
    if _prepared_render(database, int(clip_id))["signature"] != render["signature"]:
        destination.unlink(missing_ok=True)
        raise ValueError("The clip changed while it was being bounced. Try again with the current edit.")
    with database.connect() as connection:
        clip = connection.execute(
            "SELECT * FROM timeline_clips WHERE id = ?", (int(clip_id),)
        ).fetchone()
        if clip is None:
            destination.unlink(missing_ok=True)
            raise ValueError("Timeline clip was not found.")
        if clip["locked"]:
            destination.unlink(missing_ok=True)
            raise ValueError("Unlock this clip before bouncing it.")
        project_id = int(clip["project_id"])
        track = connection.execute(
            "SELECT title FROM tracks WHERE id = ?", (int(clip["track_id"]),)
        ).fetchone()
        bpm, musical_key = _source_metadata(connection, clip)
        _record_history(connection, project_id, "clip_bounced")
        values = dict(clip)
        values.pop("id", None)
        values.pop("created_at", None)
        values.pop("updated_at", None)
        values.update({
            "parent_clip_id": None,
            "clip_kind": "rendered",
            "channel": int(clip["channel"]),
            "start_seconds": round(
                float(clip["start_seconds"]) + float(clip["duration_seconds"]), 3
            ),
            "source_in_seconds": 0,
            "pitch_semitones": 0,
            "tempo_percent": 100,
            "expanded": 0,
            "locked": 0,
            "reversed": 0,
            "color": CHANNEL_COLORS[int(clip["channel"])],
        })
        columns = list(values)
        cursor = connection.execute(
            f"INSERT INTO timeline_clips({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
        new_clip_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO rendered_clip_sources(
                clip_id, render_mode, path, title, file_size, duration_seconds,
                bpm, musical_key, original_clip_json
            ) VALUES (?, 'bounce', ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                new_clip_id, str(destination), f"{track['title']} · Bounce",
                destination.stat().st_size, float(clip["duration_seconds"]), bpm,
                musical_key,
            ),
        )
        connection.execute(
            "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        result = _project_result(connection, project_id)
        result["selected_clip_id"] = new_clip_id
        return result
