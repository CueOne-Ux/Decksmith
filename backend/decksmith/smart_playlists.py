from __future__ import annotations

import json
from typing import Any

from .database import Database


RULE_KEYS = {
    "genre", "mood", "tag", "min_rating", "bpm_min", "bpm_max",
    "energy_min", "energy_max",
    "added_within_days", "played_within_days", "unplayed",
}


def validate_rules(rules: dict[str, Any]) -> dict[str, Any]:
    unknown = set(rules) - RULE_KEYS
    if unknown:
        raise ValueError(f"Unsupported smart-playlist rules: {', '.join(sorted(unknown))}")
    clean: dict[str, Any] = {}
    for key in ("genre", "mood", "tag"):
        if key in rules and str(rules[key]).strip():
            value = str(rules[key]).strip()
            if len(value) > 200:
                raise ValueError(f"{key} is too long")
            clean[key] = value
    if "min_rating" in rules:
        rating = int(rules["min_rating"])
        if not 0 <= rating <= 5:
            raise ValueError("Minimum rating must be between 0 and 5")
        if rating:
            clean["min_rating"] = rating
    for key in ("bpm_min", "bpm_max"):
        if key in rules and rules[key] not in (None, ""):
            value = float(rules[key])
            if not 0 <= value <= 400:
                raise ValueError("BPM rules must be between 0 and 400")
            clean[key] = value
    for key in ("energy_min", "energy_max"):
        if key in rules and rules[key] not in (None, ""):
            value = float(rules[key])
            if not 0 <= value <= 1:
                raise ValueError("Energy rules must be between 0 and 1")
            clean[key] = value
    if clean.get("bpm_min", 0) > clean.get("bpm_max", 400):
        raise ValueError("Minimum BPM cannot exceed maximum BPM")
    if clean.get("energy_min", 0) > clean.get("energy_max", 1):
        raise ValueError("Minimum energy cannot exceed maximum energy")
    for key in ("added_within_days", "played_within_days"):
        if key in rules and rules[key] not in (None, ""):
            value = int(rules[key])
            if not 1 <= value <= 3650:
                raise ValueError("Day ranges must be between 1 and 3650")
            clean[key] = value
    if bool(rules.get("unplayed")):
        clean["unplayed"] = True
        clean.pop("played_within_days", None)
    if not clean:
        raise ValueError("A smart playlist needs at least one rule")
    return clean


def _rule_query(rules: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = ["tracks.missing = 0"]
    parameters: list[Any] = []
    bpm = "COALESCE(tracks.analysis_bpm, tracks.bpm)"
    if "genre" in rules:
        clauses.append("tracks.genre = ? COLLATE NOCASE")
        parameters.append(rules["genre"])
    if "mood" in rules:
        clauses.append("tracks.mood = ? COLLATE NOCASE")
        parameters.append(rules["mood"])
    if "tag" in rules:
        clauses.append(
            "EXISTS (SELECT 1 FROM track_tags WHERE track_tags.track_id = tracks.id AND track_tags.tag = ? COLLATE NOCASE)"
        )
        parameters.append(rules["tag"])
    if "min_rating" in rules:
        clauses.append("tracks.rating >= ?")
        parameters.append(rules["min_rating"])
    if "bpm_min" in rules:
        clauses.append(f"{bpm} >= ?")
        parameters.append(rules["bpm_min"])
    if "bpm_max" in rules:
        clauses.append(f"{bpm} <= ?")
        parameters.append(rules["bpm_max"])
    if "energy_min" in rules:
        clauses.append("tracks.energy_score >= ?")
        parameters.append(rules["energy_min"])
    if "energy_max" in rules:
        clauses.append("tracks.energy_score <= ?")
        parameters.append(rules["energy_max"])
    if "added_within_days" in rules:
        clauses.append("tracks.discovered_at >= datetime('now', ?)")
        parameters.append(f"-{rules['added_within_days']} days")
    if rules.get("unplayed"):
        clauses.append("tracks.last_played_at IS NULL")
    elif "played_within_days" in rules:
        clauses.append("tracks.last_played_at >= datetime('now', ?)")
        parameters.append(f"-{rules['played_within_days']} days")
    return " AND ".join(clauses), parameters


def create_smart_playlist(database: Database, name: str, rules: dict[str, Any]) -> dict[str, Any]:
    database.initialize()
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 120:
        raise ValueError("Playlist name must contain 1 to 120 characters")
    clean_rules = validate_rules(rules)
    with database.connect() as connection:
        playlist_id = connection.execute(
            "INSERT INTO smart_playlists(name, rules_json) VALUES (?, ?) RETURNING id",
            (clean_name, json.dumps(clean_rules, separators=(",", ":"), sort_keys=True)),
        ).fetchone()[0]
    return next(item for item in list_smart_playlists(database) if item["id"] == playlist_id)


def delete_smart_playlist(database: Database, playlist_id: int) -> bool:
    database.initialize()
    with database.connect() as connection:
        deleted = connection.execute(
            "DELETE FROM smart_playlists WHERE id = ?", (playlist_id,)
        ).rowcount
    return deleted > 0


def smart_playlist_track_ids(database: Database, playlist_id: int) -> list[int]:
    database.initialize()
    with database.connect() as connection:
        row = connection.execute(
            "SELECT rules_json FROM smart_playlists WHERE id = ?", (playlist_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Smart playlist {playlist_id} does not exist")
        rules = validate_rules(json.loads(row["rules_json"]))
        where, parameters = _rule_query(rules)
        rows = connection.execute(
            f"SELECT tracks.id FROM tracks WHERE {where} ORDER BY tracks.artist COLLATE NOCASE, tracks.title COLLATE NOCASE",
            parameters,
        ).fetchall()
    return [row["id"] for row in rows]


def list_smart_playlists(database: Database) -> list[dict[str, Any]]:
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT id, name, rules_json, created_at, updated_at FROM smart_playlists ORDER BY name COLLATE NOCASE"
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            rules = validate_rules(json.loads(row["rules_json"]))
            where, parameters = _rule_query(rules)
            count = connection.execute(
                f"SELECT COUNT(*) FROM tracks WHERE {where}", parameters
            ).fetchone()[0]
            item = dict(row)
            item["rules"] = rules
            item["track_count"] = count
            del item["rules_json"]
            items.append(item)
    return items
