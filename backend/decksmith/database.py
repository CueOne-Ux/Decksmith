from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 25


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS library_roots (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_scanned_at TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    root_id INTEGER REFERENCES library_roots(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL DEFAULT '',
    album TEXT NOT NULL DEFAULT '',
    album_artist TEXT NOT NULL DEFAULT '',
    genre TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    duration_seconds REAL,
    bpm REAL,
    musical_key TEXT NOT NULL DEFAULT '',
    sample_rate INTEGER,
    channels INTEGER,
    bitrate INTEGER,
    metadata_status TEXT NOT NULL DEFAULT 'pending',
    metadata_error TEXT,
    missing INTEGER NOT NULL DEFAULT 0 CHECK (missing IN (0, 1)),
    last_seen_scan_id INTEGER,
    rating INTEGER NOT NULL DEFAULT 0 CHECK (rating BETWEEN 0 AND 5),
    color_tag TEXT NOT NULL DEFAULT '',
    content_hash TEXT,
    analysis_bpm REAL,
    analysis_key TEXT NOT NULL DEFAULT '',
    analysis_scale TEXT NOT NULL DEFAULT '',
    analysis_strength REAL,
    energy_score REAL,
    analysis_status TEXT NOT NULL DEFAULT 'pending',
    analysis_error TEXT,
    analysis_modified_ns INTEGER,
    last_played_at TEXT,
    play_count INTEGER NOT NULL DEFAULT 0,
    mood TEXT NOT NULL DEFAULT '',
    user_comment TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_tracks_genre ON tracks(genre COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_tracks_bpm ON tracks(bpm);
CREATE INDEX IF NOT EXISTS idx_tracks_missing ON tracks(missing);
CREATE TABLE IF NOT EXISTS track_tags (
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    tag TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (track_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_track_tags_tag ON track_tags(tag COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY,
    root_id INTEGER NOT NULL REFERENCES library_roots(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    files_seen INTEGER NOT NULL DEFAULT 0,
    tracks_added INTEGER NOT NULL DEFAULT 0,
    tracks_updated INTEGER NOT NULL DEFAULT 0,
    files_skipped INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS serato_libraries (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    last_read_at TEXT
);

CREATE TABLE IF NOT EXISTS crates (
    id INTEGER PRIMARY KEY,
    library_id INTEGER NOT NULL REFERENCES serato_libraries(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    hierarchy_path TEXT NOT NULL,
    source_path TEXT NOT NULL UNIQUE,
    source_modified_ns INTEGER NOT NULL,
    track_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crate_tracks (
    crate_id INTEGER NOT NULL REFERENCES crates(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    path TEXT NOT NULL,
    track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    PRIMARY KEY (crate_id, position)
);

CREATE INDEX IF NOT EXISTS idx_crate_tracks_track ON crate_tracks(track_id);

CREATE TABLE IF NOT EXISTS audio_analysis_jobs (
    id INTEGER PRIMARY KEY,
    track_id INTEGER NOT NULL UNIQUE REFERENCES tracks(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_audio_analysis_jobs_status ON audio_analysis_jobs(status);

CREATE TABLE IF NOT EXISTS stem_jobs (
    id INTEGER PRIMARY KEY,
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    model TEXT NOT NULL DEFAULT 'htdemucs',
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    phase TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 1),
    source_modified_ns INTEGER NOT NULL,
    output_directory TEXT,
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    error TEXT,
    UNIQUE (track_id, model)
);

CREATE INDEX IF NOT EXISTS idx_stem_jobs_status ON stem_jobs(status);

CREATE TABLE IF NOT EXISTS stem_cache (
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    stem_kind TEXT NOT NULL CHECK (stem_kind IN ('vocals', 'drums', 'bass', 'other')),
    model TEXT NOT NULL DEFAULT 'htdemucs',
    source_modified_ns INTEGER NOT NULL,
    path TEXT NOT NULL UNIQUE,
    file_size INTEGER NOT NULL CHECK (file_size > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (track_id, stem_kind, model)
);

CREATE INDEX IF NOT EXISTS idx_stem_cache_track ON stem_cache(track_id, model);

CREATE TABLE IF NOT EXISTS smart_playlists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    rules_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transfer_snapshots (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    library_count INTEGER NOT NULL DEFAULT 0,
    crate_count INTEGER NOT NULL DEFAULT 0,
    track_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transfer_snapshot_crates (
    snapshot_id INTEGER NOT NULL REFERENCES transfer_snapshots(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    name TEXT NOT NULL,
    hierarchy_path TEXT NOT NULL,
    source_modified_ns INTEGER NOT NULL,
    track_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    digest TEXT NOT NULL,
    tracks_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, source_path)
);

CREATE INDEX IF NOT EXISTS idx_transfer_snapshot_crates_source
    ON transfer_snapshot_crates(source_path);

CREATE TABLE IF NOT EXISTS transfer_exports (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES transfer_snapshots(id),
    destination_path TEXT NOT NULL UNIQUE,
    xml_path TEXT NOT NULL,
    report_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed'
        CHECK (status IN ('completed', 'failed')),
    crate_count INTEGER NOT NULL DEFAULT 0,
    track_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    cue_count INTEGER NOT NULL DEFAULT 0,
    loop_count INTEGER NOT NULL DEFAULT 0,
    validation_status TEXT NOT NULL DEFAULT 'passed',
    manifest_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS marker_scans (
    track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    source_modified_ns INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    source_format TEXT,
    cue_count INTEGER NOT NULL DEFAULT 0,
    loop_record_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cue_points (
    id INTEGER PRIMARY KEY,
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    slot INTEGER NOT NULL CHECK (slot BETWEEN 0 AND 255),
    name TEXT NOT NULL DEFAULT '',
    position_seconds REAL NOT NULL CHECK (position_seconds >= 0),
    color TEXT NOT NULL DEFAULT '',
    source_modified_ns INTEGER NOT NULL,
    UNIQUE (track_id, source, slot)
);

CREATE INDEX IF NOT EXISTS idx_cue_points_track ON cue_points(track_id);

CREATE TABLE IF NOT EXISTS saved_loops (
    id INTEGER PRIMARY KEY,
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    slot INTEGER NOT NULL CHECK (slot BETWEEN 0 AND 255),
    start_seconds REAL NOT NULL CHECK (start_seconds >= 0),
    end_seconds REAL NOT NULL CHECK (end_seconds > start_seconds),
    color TEXT NOT NULL DEFAULT '',
    source_modified_ns INTEGER NOT NULL,
    UNIQUE (track_id, source, slot)
);

CREATE INDEX IF NOT EXISTS idx_saved_loops_track ON saved_loops(track_id);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    tempo REAL NOT NULL DEFAULT 120 CHECK (tempo BETWEEN 40 AND 240),
    musical_key TEXT NOT NULL DEFAULT '',
    time_signature_numerator INTEGER NOT NULL DEFAULT 4,
    time_signature_denominator INTEGER NOT NULL DEFAULT 4,
    snap_enabled INTEGER NOT NULL DEFAULT 1 CHECK (snap_enabled IN (0, 1)),
    snap_beats REAL NOT NULL DEFAULT 1 CHECK (snap_beats BETWEEN 0.125 AND 16),
    selection_start_seconds REAL,
    selection_end_seconds REAL,
    selection_loop_enabled INTEGER NOT NULL DEFAULT 0 CHECK (selection_loop_enabled IN (0, 1)),
    master_gain_db REAL NOT NULL DEFAULT 0 CHECK (master_gain_db BETWEEN -24 AND 12),
    master_limiter_enabled INTEGER NOT NULL DEFAULT 1 CHECK (master_limiter_enabled IN (0, 1)),
    master_low_eq_db REAL NOT NULL DEFAULT 0 CHECK (master_low_eq_db BETWEEN -12 AND 12),
    master_mid_eq_db REAL NOT NULL DEFAULT 0 CHECK (master_mid_eq_db BETWEEN -12 AND 12),
    master_high_eq_db REAL NOT NULL DEFAULT 0 CHECK (master_high_eq_db BETWEEN -12 AND 12),
    master_stereo_width REAL NOT NULL DEFAULT 1 CHECK (master_stereo_width BETWEEN 0 AND 2),
    target_lufs REAL NOT NULL DEFAULT -14 CHECK (target_lufs BETWEEN -24 AND -6),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS timeline_clips (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL REFERENCES tracks(id),
    parent_clip_id INTEGER REFERENCES timeline_clips(id) ON DELETE CASCADE,
    clip_kind TEXT NOT NULL DEFAULT 'song'
        CHECK (clip_kind IN ('song', 'vocals', 'drums', 'bass', 'other', 'rendered')),
    channel INTEGER NOT NULL CHECK (channel BETWEEN 1 AND 4),
    start_seconds REAL NOT NULL DEFAULT 0 CHECK (start_seconds >= 0),
    source_in_seconds REAL NOT NULL DEFAULT 0 CHECK (source_in_seconds >= 0),
    duration_seconds REAL NOT NULL CHECK (duration_seconds > 0),
    gain_db REAL NOT NULL DEFAULT 0 CHECK (gain_db BETWEEN -60 AND 12),
    pan REAL NOT NULL DEFAULT 0 CHECK (pan BETWEEN -1 AND 1),
    pitch_semitones REAL NOT NULL DEFAULT 0 CHECK (pitch_semitones BETWEEN -24 AND 24),
    tempo_percent REAL NOT NULL DEFAULT 100 CHECK (tempo_percent BETWEEN 25 AND 400),
    color TEXT NOT NULL DEFAULT 'violet',
    expanded INTEGER NOT NULL DEFAULT 0 CHECK (expanded IN (0, 1)),
    locked INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0, 1)),
    muted INTEGER NOT NULL DEFAULT 0 CHECK (muted IN (0, 1)),
    solo INTEGER NOT NULL DEFAULT 0 CHECK (solo IN (0, 1)),
    loop_enabled INTEGER NOT NULL DEFAULT 0 CHECK (loop_enabled IN (0, 1)),
    reversed INTEGER NOT NULL DEFAULT 0 CHECK (reversed IN (0, 1)),
    fade_in_seconds REAL NOT NULL DEFAULT 0 CHECK (fade_in_seconds >= 0),
    fade_out_seconds REAL NOT NULL DEFAULT 0 CHECK (fade_out_seconds >= 0),
    eq_low_db REAL NOT NULL DEFAULT 0 CHECK (eq_low_db BETWEEN -12 AND 12),
    eq_mid_db REAL NOT NULL DEFAULT 0 CHECK (eq_mid_db BETWEEN -12 AND 12),
    eq_high_db REAL NOT NULL DEFAULT 0 CHECK (eq_high_db BETWEEN -12 AND 12),
    highpass_hz REAL NOT NULL DEFAULT 20 CHECK (highpass_hz BETWEEN 20 AND 20000),
    lowpass_hz REAL NOT NULL DEFAULT 20000 CHECK (lowpass_hz BETWEEN 20 AND 20000),
    compressor_enabled INTEGER NOT NULL DEFAULT 0 CHECK (compressor_enabled IN (0, 1)),
    compressor_threshold_db REAL NOT NULL DEFAULT -18 CHECK (compressor_threshold_db BETWEEN -60 AND 0),
    compressor_ratio REAL NOT NULL DEFAULT 4 CHECK (compressor_ratio BETWEEN 1 AND 20),
    group_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_timeline_clips_project
    ON timeline_clips(project_id, channel, start_seconds);

CREATE TABLE IF NOT EXISTS clip_stem_states (
    clip_id INTEGER NOT NULL REFERENCES timeline_clips(id) ON DELETE CASCADE,
    stem_kind TEXT NOT NULL CHECK (stem_kind IN ('vocals', 'drums', 'bass', 'other')),
    muted INTEGER NOT NULL DEFAULT 0 CHECK (muted IN (0, 1)),
    solo INTEGER NOT NULL DEFAULT 0 CHECK (solo IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (clip_id, stem_kind)
);

CREATE TABLE IF NOT EXISTS render_jobs (
    id INTEGER PRIMARY KEY,
    clip_id INTEGER NOT NULL UNIQUE REFERENCES timeline_clips(id) ON DELETE CASCADE,
    signature TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    phase TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 1),
    output_path TEXT,
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_render_jobs_status ON render_jobs(status);

CREATE TABLE IF NOT EXISTS render_cache (
    clip_id INTEGER PRIMARY KEY REFERENCES timeline_clips(id) ON DELETE CASCADE,
    signature TEXT NOT NULL,
    source_modified_ns INTEGER NOT NULL,
    path TEXT NOT NULL UNIQUE,
    file_size INTEGER NOT NULL CHECK (file_size > 0),
    duration_seconds REAL NOT NULL CHECK (duration_seconds > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rendered_clip_sources (
    clip_id INTEGER PRIMARY KEY REFERENCES timeline_clips(id) ON DELETE CASCADE,
    render_mode TEXT NOT NULL CHECK (render_mode IN ('freeze', 'bounce')),
    path TEXT NOT NULL,
    title TEXT NOT NULL,
    file_size INTEGER NOT NULL CHECK (file_size > 0),
    duration_seconds REAL NOT NULL CHECK (duration_seconds > 0),
    bpm REAL,
    musical_key TEXT NOT NULL DEFAULT '',
    original_clip_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS project_markers (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    marker_kind TEXT NOT NULL DEFAULT 'marker'
        CHECK (marker_kind IN ('marker', 'section')),
    name TEXT NOT NULL,
    start_seconds REAL NOT NULL CHECK (start_seconds >= 0),
    end_seconds REAL,
    color TEXT NOT NULL DEFAULT 'violet',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (marker_kind = 'marker' AND end_seconds IS NULL) OR
        (marker_kind = 'section' AND end_seconds > start_seconds)
    )
);

CREATE INDEX IF NOT EXISTS idx_project_markers_project
    ON project_markers(project_id, start_seconds, id);

CREATE TABLE IF NOT EXISTS project_history (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_project_history_project
    ON project_history(project_id, id DESC);

CREATE TABLE IF NOT EXISTS project_redo_history (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_project_redo_history_project
    ON project_redo_history(project_id, id DESC);

CREATE TABLE IF NOT EXISTS project_audits (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_signature TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ready', 'warning', 'blocked')),
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_project_audits_project
    ON project_audits(project_id, id DESC);

CREATE TABLE IF NOT EXISTS project_exports (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    audit_id INTEGER REFERENCES project_audits(id) ON DELETE SET NULL,
    project_signature TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('wav', 'mp3')),
    export_mode TEXT NOT NULL DEFAULT 'original'
        CHECK (export_mode IN ('original', 'loudness_targeted')),
    target_lufs REAL,
    destination_path TEXT NOT NULL,
    file_size INTEGER NOT NULL CHECK (file_size > 0),
    duration_seconds REAL NOT NULL CHECK (duration_seconds > 0),
    clip_count INTEGER NOT NULL CHECK (clip_count > 0),
    sha256 TEXT NOT NULL,
    integrated_lufs REAL,
    true_peak_dbfs REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_project_exports_project
    ON project_exports(project_id, id DESC);

CREATE TABLE IF NOT EXISTS assistant_drafts (
    id INTEGER PRIMARY KEY,
    draft_kind TEXT NOT NULL CHECK (draft_kind IN ('mashup', 'setlist')),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idea'
        CHECK (status IN ('idea', 'ready', 'needs_review', 'finished')),
    brief_json TEXT NOT NULL DEFAULT '{}',
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS assistant_draft_tracks (
    draft_id INTEGER NOT NULL REFERENCES assistant_drafts(id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL REFERENCES tracks(id),
    position INTEGER NOT NULL CHECK (position >= 0),
    role TEXT NOT NULL DEFAULT 'track',
    compatibility_score REAL NOT NULL DEFAULT 0 CHECK (compatibility_score BETWEEN 0 AND 100),
    explanation_json TEXT NOT NULL DEFAULT '[]',
    suggested_tempo REAL,
    suggested_pitch_semitones REAL,
    PRIMARY KEY (draft_id, position)
);

CREATE INDEX IF NOT EXISTS idx_assistant_drafts_updated
    ON assistant_drafts(updated_at DESC, id DESC);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            row = connection.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
            elif row[0] > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported database version {row[0]}; expected {SCHEMA_VERSION}"
                )
            else:
                version = row[0]
                columns = {
                    column["name"] for column in connection.execute("PRAGMA table_info(tracks)")
                }
                if version < 2:
                    if "last_seen_scan_id" not in columns:
                        connection.execute("ALTER TABLE tracks ADD COLUMN last_seen_scan_id INTEGER")
                        columns.add("last_seen_scan_id")
                    version = 2
                if version < 3:
                    if "rating" not in columns:
                        connection.execute(
                            "ALTER TABLE tracks ADD COLUMN rating INTEGER NOT NULL DEFAULT 0 CHECK (rating BETWEEN 0 AND 5)"
                        )
                        columns.add("rating")
                    if "color_tag" not in columns:
                        connection.execute("ALTER TABLE tracks ADD COLUMN color_tag TEXT NOT NULL DEFAULT ''")
                        columns.add("color_tag")
                    if "content_hash" not in columns:
                        connection.execute("ALTER TABLE tracks ADD COLUMN content_hash TEXT")
                        columns.add("content_hash")
                    version = 3
                if version < 4:
                    version = 4
                if version < 5:
                    analysis_columns = {
                        "analysis_bpm": "REAL",
                        "analysis_key": "TEXT NOT NULL DEFAULT ''",
                        "analysis_scale": "TEXT NOT NULL DEFAULT ''",
                        "analysis_strength": "REAL",
                        "energy_score": "REAL",
                        "analysis_status": "TEXT NOT NULL DEFAULT 'pending'",
                        "analysis_error": "TEXT",
                        "analysis_modified_ns": "INTEGER",
                    }
                    for name, definition in analysis_columns.items():
                        if name not in columns:
                            connection.execute(
                                f"ALTER TABLE tracks ADD COLUMN {name} {definition}"
                            )
                            columns.add(name)
                    version = 5
                if version < 6:
                    history_columns = {
                        "last_played_at": "TEXT",
                        "play_count": "INTEGER NOT NULL DEFAULT 0",
                    }
                    for name, definition in history_columns.items():
                        if name not in columns:
                            connection.execute(
                                f"ALTER TABLE tracks ADD COLUMN {name} {definition}"
                            )
                            columns.add(name)
                    version = 6
                if version < 7:
                    library_columns = {
                        "mood": "TEXT NOT NULL DEFAULT ''",
                        "user_comment": "TEXT",
                    }
                    for name, definition in library_columns.items():
                        if name not in columns:
                            connection.execute(
                                f"ALTER TABLE tracks ADD COLUMN {name} {definition}"
                            )
                            columns.add(name)
                    version = 7
                if version < 8:
                    version = 8
                if version < 9:
                    export_columns = {
                        column["name"] for column in connection.execute("PRAGMA table_info(transfer_exports)")
                    }
                    transfer_export_columns = {
                        "cue_count": "INTEGER NOT NULL DEFAULT 0",
                        "validation_status": "TEXT NOT NULL DEFAULT 'passed'",
                        "manifest_path": "TEXT NOT NULL DEFAULT ''",
                    }
                    for name, definition in transfer_export_columns.items():
                        if name not in export_columns:
                            connection.execute(
                                f"ALTER TABLE transfer_exports ADD COLUMN {name} {definition}"
                            )
                    version = 9
                if version < 10:
                    export_columns = {
                        column["name"] for column in connection.execute("PRAGMA table_info(transfer_exports)")
                    }
                    if "loop_count" not in export_columns:
                        connection.execute(
                            "ALTER TABLE transfer_exports ADD COLUMN loop_count INTEGER NOT NULL DEFAULT 0"
                        )
                    version = 10
                if version < 11:
                    connection.execute("DELETE FROM marker_scans")
                    version = 11
                if version < 12:
                    version = 12
                if version < 13:
                    clip_columns = {
                        column["name"]
                        for column in connection.execute("PRAGMA table_info(timeline_clips)")
                    }
                    editing_columns = {
                        "loop_enabled": "INTEGER NOT NULL DEFAULT 0 CHECK (loop_enabled IN (0, 1))",
                        "reversed": "INTEGER NOT NULL DEFAULT 0 CHECK (reversed IN (0, 1))",
                        "fade_in_seconds": "REAL NOT NULL DEFAULT 0 CHECK (fade_in_seconds >= 0)",
                        "fade_out_seconds": "REAL NOT NULL DEFAULT 0 CHECK (fade_out_seconds >= 0)",
                    }
                    for name, definition in editing_columns.items():
                        if name not in clip_columns:
                            connection.execute(
                                f"ALTER TABLE timeline_clips ADD COLUMN {name} {definition}"
                            )
                    version = 13
                if version < 14:
                    project_columns = {
                        column["name"]
                        for column in connection.execute("PRAGMA table_info(projects)")
                    }
                    project_editing_columns = {
                        "snap_enabled": "INTEGER NOT NULL DEFAULT 1 CHECK (snap_enabled IN (0, 1))",
                        "snap_beats": "REAL NOT NULL DEFAULT 1 CHECK (snap_beats BETWEEN 0.125 AND 16)",
                    }
                    for name, definition in project_editing_columns.items():
                        if name not in project_columns:
                            connection.execute(
                                f"ALTER TABLE projects ADD COLUMN {name} {definition}"
                            )
                    version = 14
                if version < 15:
                    project_columns = {
                        column["name"]
                        for column in connection.execute("PRAGMA table_info(projects)")
                    }
                    selection_columns = {
                        "selection_start_seconds": "REAL",
                        "selection_end_seconds": "REAL",
                        "selection_loop_enabled": "INTEGER NOT NULL DEFAULT 0 CHECK (selection_loop_enabled IN (0, 1))",
                    }
                    for name, definition in selection_columns.items():
                        if name not in project_columns:
                            connection.execute(f"ALTER TABLE projects ADD COLUMN {name} {definition}")
                    version = 15
                if version < 16:
                    project_columns = {column["name"] for column in connection.execute("PRAGMA table_info(projects)")}
                    master_columns = {
                        "master_gain_db": "REAL NOT NULL DEFAULT 0 CHECK (master_gain_db BETWEEN -24 AND 12)",
                        "master_limiter_enabled": "INTEGER NOT NULL DEFAULT 1 CHECK (master_limiter_enabled IN (0, 1))",
                    }
                    for name, definition in master_columns.items():
                        if name not in project_columns:
                            connection.execute(f"ALTER TABLE projects ADD COLUMN {name} {definition}")
                    clip_columns = {column["name"] for column in connection.execute("PRAGMA table_info(timeline_clips)")}
                    if "group_id" not in clip_columns:
                        connection.execute("ALTER TABLE timeline_clips ADD COLUMN group_id INTEGER")
                    version = 16
                if version < 17:
                    version = 17
                if version < 18:
                    # Before render schema v18, tempo edits changed playback speed
                    # without changing the stored timeline duration. Preserve the
                    # same consumed source span while adopting the v18 contract:
                    # duration_seconds is always the duration on the timeline.
                    connection.execute(
                        """
                        UPDATE timeline_clips
                        SET duration_seconds = ROUND(
                            duration_seconds / (tempo_percent / 100.0),
                            3
                        )
                        WHERE ABS(tempo_percent - 100.0) > 0.001
                        """
                    )
                    version = 18
                if version < 19:
                    project_columns = {
                        column["name"] for column in connection.execute("PRAGMA table_info(projects)")
                    }
                    phase_five_project_columns = {
                        "master_low_eq_db": "REAL NOT NULL DEFAULT 0 CHECK (master_low_eq_db BETWEEN -12 AND 12)",
                        "master_mid_eq_db": "REAL NOT NULL DEFAULT 0 CHECK (master_mid_eq_db BETWEEN -12 AND 12)",
                        "master_high_eq_db": "REAL NOT NULL DEFAULT 0 CHECK (master_high_eq_db BETWEEN -12 AND 12)",
                        "master_stereo_width": "REAL NOT NULL DEFAULT 1 CHECK (master_stereo_width BETWEEN 0 AND 2)",
                    }
                    for name, definition in phase_five_project_columns.items():
                        if name not in project_columns:
                            connection.execute(f"ALTER TABLE projects ADD COLUMN {name} {definition}")
                    clip_columns = {
                        column["name"] for column in connection.execute("PRAGMA table_info(timeline_clips)")
                    }
                    phase_five_clip_columns = {
                        "eq_low_db": "REAL NOT NULL DEFAULT 0 CHECK (eq_low_db BETWEEN -12 AND 12)",
                        "eq_mid_db": "REAL NOT NULL DEFAULT 0 CHECK (eq_mid_db BETWEEN -12 AND 12)",
                        "eq_high_db": "REAL NOT NULL DEFAULT 0 CHECK (eq_high_db BETWEEN -12 AND 12)",
                        "highpass_hz": "REAL NOT NULL DEFAULT 20 CHECK (highpass_hz BETWEEN 20 AND 20000)",
                        "lowpass_hz": "REAL NOT NULL DEFAULT 20000 CHECK (lowpass_hz BETWEEN 20 AND 20000)",
                        "compressor_enabled": "INTEGER NOT NULL DEFAULT 0 CHECK (compressor_enabled IN (0, 1))",
                        "compressor_threshold_db": "REAL NOT NULL DEFAULT -18 CHECK (compressor_threshold_db BETWEEN -60 AND 0)",
                        "compressor_ratio": "REAL NOT NULL DEFAULT 4 CHECK (compressor_ratio BETWEEN 1 AND 20)",
                    }
                    for name, definition in phase_five_clip_columns.items():
                        if name not in clip_columns:
                            connection.execute(f"ALTER TABLE timeline_clips ADD COLUMN {name} {definition}")
                    version = 19
                if version < 20:
                    project_columns = {
                        column["name"] for column in connection.execute("PRAGMA table_info(projects)")
                    }
                    if "target_lufs" not in project_columns:
                        connection.execute(
                            "ALTER TABLE projects ADD COLUMN target_lufs "
                            "REAL NOT NULL DEFAULT -14 CHECK (target_lufs BETWEEN -24 AND -6)"
                        )
                    version = 20
                if version < 21:
                    # The phase-six audit/export tables are created by SCHEMA above.
                    version = 21
                if version < 22:
                    # Per-clip stem mixer state is created by SCHEMA above.
                    version = 22
                if version < 23:
                    # Stable frozen and bounced clip sources are created by SCHEMA above.
                    version = 23
                if version < 24:
                    # Multiple edits can safely reference the same immutable consolidated WAV.
                    connection.execute(
                        """
                        CREATE TABLE rendered_clip_sources_v24 (
                            clip_id INTEGER PRIMARY KEY REFERENCES timeline_clips(id) ON DELETE CASCADE,
                            render_mode TEXT NOT NULL CHECK (render_mode IN ('freeze', 'bounce')),
                            path TEXT NOT NULL,
                            title TEXT NOT NULL,
                            file_size INTEGER NOT NULL CHECK (file_size > 0),
                            duration_seconds REAL NOT NULL CHECK (duration_seconds > 0),
                            bpm REAL,
                            musical_key TEXT NOT NULL DEFAULT '',
                            original_clip_json TEXT,
                            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    connection.execute(
                        """
                        INSERT INTO rendered_clip_sources_v24(
                            clip_id, render_mode, path, title, file_size, duration_seconds,
                            bpm, musical_key, original_clip_json, created_at
                        )
                        SELECT clip_id, render_mode, path, title, file_size, duration_seconds,
                               bpm, musical_key, original_clip_json, created_at
                        FROM rendered_clip_sources
                        """
                    )
                    connection.execute("DROP TABLE rendered_clip_sources")
                    connection.execute(
                        "ALTER TABLE rendered_clip_sources_v24 RENAME TO rendered_clip_sources"
                    )
                    version = 24
                if version < 25:
                    # Offline mashup and setlist drafts are created by SCHEMA above.
                    version = 25
                connection.execute("UPDATE schema_info SET version = ?", (version,))
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracks_content_hash ON tracks(content_hash)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracks_last_played ON tracks(last_played_at)"
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
