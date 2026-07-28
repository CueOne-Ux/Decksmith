from __future__ import annotations

import json
import math
from typing import Any

from .database import Database
from .library import list_tracks
from .projects import add_track_to_project, create_project


MINOR_CAMELOT = [8, 3, 10, 5, 0, 7, 2, 9, 4, 11, 6, 1]
MAJOR_CAMELOT = [11, 6, 1, 8, 3, 10, 5, 0, 7, 2, 9, 4]
NOTE_PITCHES = {
    "C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4,
    "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
    "A#": 10, "BB": 10, "B": 11,
}


def _track_map(database: Database) -> dict[int, dict[str, Any]]:
    return {int(track["id"]): track for track in list_tracks(database)}


def _parse_key(value: Any) -> tuple[int, str] | None:
    text = str(value or "").strip().upper().replace("♯", "#").replace("♭", "B")
    if len(text) in {2, 3} and text[-1:] in {"A", "B"} and text[:-1].isdigit():
        number = int(text[:-1])
        if 1 <= number <= 12:
            mode = "minor" if text[-1] == "A" else "major"
            pitches = MINOR_CAMELOT if mode == "minor" else MAJOR_CAMELOT
            return pitches[number - 1], mode
    mode = "minor" if text.endswith("M") and not text.endswith("MAJ") else "major"
    note = text.removesuffix("MINOR").removesuffix("MIN").removesuffix("MAJOR").removesuffix("MAJ")
    if mode == "minor":
        note = note.removesuffix("M")
    note = note.strip()
    pitch = NOTE_PITCHES.get(note)
    return (pitch, mode) if pitch is not None else None


def _tempo_pair(left: Any, right: Any) -> tuple[float, float | None]:
    try:
        left_bpm = float(left)
        right_bpm = float(right)
    except (TypeError, ValueError):
        return 0.35, None
    if left_bpm <= 0 or right_bpm <= 0:
        return 0.35, None
    variants = [right_bpm * factor for factor in (0.5, 1.0, 2.0)]
    matched = min(variants, key=lambda value: abs(value - left_bpm))
    delta = abs(matched - left_bpm)
    score = max(0.0, 1.0 - delta / 12.0)
    return score, round((left_bpm + matched) / 2.0, 3)


def _key_pair(left: Any, right: Any) -> tuple[float, int, str]:
    first = _parse_key(left)
    second = _parse_key(right)
    if first is None or second is None:
        return 0.35, 0, "Key data is incomplete, so harmonic confidence is limited."
    pitch_delta = ((first[0] - second[0] + 18) % 12) - 6
    if first == second:
        return 1.0, 0, "The tracks share the same harmonic centre and mode."
    if first[0] == second[0]:
        return 0.94, 0, "The tracks share a tonal centre with contrasting major/minor colour."
    if abs(pitch_delta) <= 1 and first[1] == second[1]:
        return 0.86, pitch_delta, "A one-semitone adjustment creates a close harmonic match."
    if first[1] != second[1] and ((first[0] - second[0]) % 12 in {3, 9}):
        return 0.92, 0, "The keys form a relative major/minor pairing."
    return max(0.2, 0.72 - abs(pitch_delta) * 0.08), pitch_delta, (
        f"Shift the overlay {pitch_delta:+d} semitone{'s' if abs(pitch_delta) != 1 else ''} "
        "for the nearest tonal centre."
    )


def _energy(track: dict[str, Any]) -> float:
    value = track.get("energy_score")
    if value is not None:
        return max(0.0, min(1.0, float(value)))
    mood = str(track.get("mood") or "").casefold()
    if any(word in mood for word in ("peak", "euphoric", "driving")):
        return 0.85
    if any(word in mood for word in ("warm", "melodic")):
        return 0.55
    return 0.45


def compatibility(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    tempo_score, suggested_tempo = _tempo_pair(left.get("bpm"), right.get("bpm"))
    key_score, pitch, key_reason = _key_pair(left.get("musical_key"), right.get("musical_key"))
    energy_delta = abs(_energy(left) - _energy(right))
    energy_score = max(0.0, 1.0 - energy_delta)
    left_genre = str(left.get("genre") or "").strip().casefold()
    right_genre = str(right.get("genre") or "").strip().casefold()
    genre_score = 1.0 if left_genre and left_genre == right_genre else 0.55
    analysis_score = (
        int(left.get("analysis_status") == "completed")
        + int(right.get("analysis_status") == "completed")
    ) / 2
    score = round(
        100 * (
            tempo_score * 0.35 + key_score * 0.30 + energy_score * 0.17
            + genre_score * 0.10 + analysis_score * 0.08
        )
    )
    tempo_reason = (
        f"A shared working tempo around {suggested_tempo:.2f} BPM needs only a small retime."
        if suggested_tempo is not None and tempo_score >= 0.75
        else "The tempo gap needs a deliberate retime before phrase alignment."
    )
    energy_reason = (
        "Their energy profiles are close enough for a stable blend."
        if energy_delta <= 0.2
        else "The energy contrast can work as a lift or breakdown, but needs arrangement care."
    )
    balance_reason = (
        "Shared genre language suggests compatible groove and instrumentation."
        if genre_score == 1.0
        else "Different genre profiles may create a distinctive mashup if the drums are kept clean."
    )
    return {
        "score": score,
        "suggested_tempo": suggested_tempo,
        "suggested_pitch_semitones": pitch,
        "explanations": [tempo_reason, key_reason, energy_reason, balance_reason],
        "components": {
            "tempo": round(tempo_score * 100),
            "key": round(key_score * 100),
            "energy": round(energy_score * 100),
            "groove": round(genre_score * 100),
        },
    }


def compatible_tracks(database: Database, anchor_track_id: int, limit: int = 12) -> dict[str, Any]:
    database.initialize()
    tracks = _track_map(database)
    anchor = tracks.get(int(anchor_track_id))
    if anchor is None:
        raise ValueError("The anchor track is not available in the local library.")
    suggestions = []
    for track_id, track in tracks.items():
        if track_id == int(anchor_track_id):
            continue
        suggestions.append({"track": track, **compatibility(anchor, track)})
    suggestions.sort(key=lambda item: (-int(item["score"]), str(item["track"]["artist"]).casefold()))
    return {"anchor": anchor, "suggestions": suggestions[: max(1, min(50, int(limit)))]}


def _draft_result(connection: Any, draft_id: int) -> dict[str, Any]:
    draft = connection.execute(
        "SELECT * FROM assistant_drafts WHERE id = ?", (int(draft_id),)
    ).fetchone()
    if draft is None:
        raise ValueError("Assistant draft was not found.")
    rows = connection.execute(
        """
        SELECT assistant_draft_tracks.*, tracks.title, tracks.artist, tracks.genre,
               tracks.duration_seconds, COALESCE(tracks.analysis_bpm, tracks.bpm) AS bpm,
               CASE WHEN tracks.analysis_key != '' THEN tracks.analysis_key
                    ELSE tracks.musical_key END AS musical_key,
               tracks.energy_score, tracks.rating, tracks.mood
        FROM assistant_draft_tracks
        JOIN tracks ON tracks.id = assistant_draft_tracks.track_id
        WHERE assistant_draft_tracks.draft_id = ?
        ORDER BY assistant_draft_tracks.position
        """,
        (int(draft_id),),
    ).fetchall()
    result = dict(draft)
    result["brief"] = json.loads(result.pop("brief_json"))
    result["tracks"] = []
    for row in rows:
        item = dict(row)
        item["explanations"] = json.loads(item.pop("explanation_json"))
        result["tracks"].append(item)
    return result


def list_drafts(database: Database) -> list[dict[str, Any]]:
    database.initialize()
    with database.connect() as connection:
        ids = [int(row["id"]) for row in connection.execute(
            "SELECT id FROM assistant_drafts ORDER BY updated_at DESC, id DESC"
        ).fetchall()]
        return [_draft_result(connection, draft_id) for draft_id in ids]


def create_mashup_draft(
    database: Database, anchor_track_id: int, partner_track_id: int, name: str = ""
) -> dict[str, Any]:
    database.initialize()
    tracks = _track_map(database)
    anchor = tracks.get(int(anchor_track_id))
    partner = tracks.get(int(partner_track_id))
    if anchor is None or partner is None or anchor["id"] == partner["id"]:
        raise ValueError("Choose two different available tracks for a mashup draft.")
    match = compatibility(anchor, partner)
    draft_name = name.strip() or f"{anchor['title']} × {partner['title']}"
    status = "ready" if match["score"] >= 72 else "needs_review"
    brief = {
        "anchor_track_id": int(anchor["id"]),
        "working_tempo": match["suggested_tempo"],
        "compatibility_score": match["score"],
        "components": match["components"],
    }
    with database.connect() as connection:
        cursor = connection.execute(
            "INSERT INTO assistant_drafts(draft_kind, name, status, brief_json) VALUES ('mashup', ?, ?, ?)",
            (draft_name[:120], status, json.dumps(brief, separators=(",", ":"))),
        )
        draft_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO assistant_draft_tracks(
                draft_id, track_id, position, role, compatibility_score,
                explanation_json, suggested_tempo, suggested_pitch_semitones
            ) VALUES (?, ?, 0, 'foundation', 100, ?, ?, 0)
            """,
            (draft_id, anchor["id"], json.dumps(["Foundation track for timing and structure."]), match["suggested_tempo"]),
        )
        connection.execute(
            """
            INSERT INTO assistant_draft_tracks(
                draft_id, track_id, position, role, compatibility_score,
                explanation_json, suggested_tempo, suggested_pitch_semitones
            ) VALUES (?, ?, 1, 'overlay', ?, ?, ?, ?)
            """,
            (
                draft_id, partner["id"], match["score"],
                json.dumps(match["explanations"], separators=(",", ":")),
                match["suggested_tempo"], match["suggested_pitch_semitones"],
            ),
        )
        return _draft_result(connection, draft_id)


def create_setlist_draft(
    database: Database,
    name: str,
    duration_minutes: int,
    genre: str = "",
    energy_curve: str = "rise",
    must_play_track_ids: list[int] | None = None,
    avoid_tags: list[str] | None = None,
) -> dict[str, Any]:
    database.initialize()
    minutes = max(15, min(720, int(duration_minutes)))
    curve = str(energy_curve).strip().casefold()
    if curve not in {"rise", "steady", "wave"}:
        raise ValueError("Energy curve must be rise, steady or wave.")
    must_ids = list(dict.fromkeys(int(value) for value in (must_play_track_ids or [])))
    avoided = {str(value).strip().casefold() for value in (avoid_tags or []) if str(value).strip()}
    candidates = list(_track_map(database).values())
    if genre.strip():
        genre_key = genre.strip().casefold()
        candidates = [track for track in candidates if genre_key in str(track.get("genre") or "").casefold()]
    candidates = [
        track for track in candidates
        if not avoided.intersection(str(track.get("tags") or "").casefold().split(","))
    ]
    by_id = {int(track["id"]): track for track in candidates}
    missing_must = [track_id for track_id in must_ids if track_id not in by_id]
    if missing_must:
        raise ValueError("A must-play track is missing or excluded by the current filters.")
    if not candidates:
        raise ValueError("No local tracks match this setlist brief.")
    target_seconds = minutes * 60
    estimated_slots = max(1, math.ceil(target_seconds / max(180, sum(float(t.get("duration_seconds") or 300) for t in candidates) / len(candidates))))

    def target_energy(index: int) -> float:
        progress = index / max(1, estimated_slots - 1)
        if curve == "rise":
            return 0.28 + progress * 0.68
        if curve == "wave":
            return 0.55 + 0.28 * math.sin(progress * math.pi * 3 - math.pi / 2)
        return 0.62

    chosen: list[dict[str, Any]] = []
    remaining = {int(track["id"]): track for track in candidates}
    elapsed = 0.0
    position = 0
    while remaining and elapsed < target_seconds:
        target = target_energy(position)
        next_track = min(
            remaining.values(),
            key=lambda track: (
                0 if int(track["id"]) in must_ids else 1,
                abs(_energy(track) - target) - float(track.get("rating") or 0) * 0.015,
                int(track["id"]),
            ),
        )
        chosen.append(next_track)
        remaining.pop(int(next_track["id"]), None)
        elapsed += float(next_track.get("duration_seconds") or 300)
        position += 1
    brief = {
        "duration_minutes": minutes,
        "genre": genre.strip(),
        "energy_curve": curve,
        "must_play_track_ids": must_ids,
        "avoid_tags": sorted(avoided),
        "estimated_duration_seconds": round(elapsed),
    }
    with database.connect() as connection:
        cursor = connection.execute(
            "INSERT INTO assistant_drafts(draft_kind, name, status, brief_json) VALUES ('setlist', ?, 'ready', ?)",
            ((name.strip() or f"{minutes}-minute {genre.strip() or 'library'} set")[:120], json.dumps(brief, separators=(",", ":"))),
        )
        draft_id = int(cursor.lastrowid)
        previous: dict[str, Any] | None = None
        for index, track in enumerate(chosen):
            match = compatibility(previous, track) if previous is not None else None
            explanations = (
                match["explanations"][:2]
                if match else [f"Starts near {round(_energy(track) * 100)}% of the library energy range."]
            )
            connection.execute(
                """
                INSERT INTO assistant_draft_tracks(
                    draft_id, track_id, position, role, compatibility_score,
                    explanation_json, suggested_tempo, suggested_pitch_semitones
                ) VALUES (?, ?, ?, 'set track', ?, ?, ?, ?)
                """,
                (
                    draft_id, track["id"], index, match["score"] if match else 100,
                    json.dumps(explanations, separators=(",", ":")),
                    match["suggested_tempo"] if match else track.get("bpm"),
                    match["suggested_pitch_semitones"] if match else 0,
                ),
            )
            previous = track
        return _draft_result(connection, draft_id)


def create_project_from_mashup_draft(database: Database, draft_id: int) -> dict[str, Any]:
    database.initialize()
    with database.connect() as connection:
        draft = _draft_result(connection, int(draft_id))
    if draft["draft_kind"] != "mashup":
        raise ValueError("Only a mashup draft can become an arrangement project.")
    if draft.get("project_id"):
        from .projects import load_project
        return load_project(database, int(draft["project_id"]))
    tempo = float(draft["brief"].get("working_tempo") or draft["tracks"][0].get("bpm") or 120)
    project = create_project(database, draft["name"], max(40, min(240, tempo)))
    project_id = int(project["project"]["id"])
    for index, item in enumerate(draft["tracks"][:4]):
        add_track_to_project(database, project_id, int(item["track_id"]), index + 1, 0)
    with database.connect() as connection:
        connection.execute(
            "UPDATE assistant_drafts SET project_id = ?, status = 'finished', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (project_id, int(draft_id)),
        )
    from .projects import load_project
    return load_project(database, project_id)
