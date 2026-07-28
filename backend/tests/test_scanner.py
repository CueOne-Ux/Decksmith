from __future__ import annotations

import sqlite3
import shutil
import tempfile
import unittest
import wave
from contextlib import closing
from pathlib import Path

from decksmith.database import SCHEMA_VERSION, Database
from decksmith.library import (
    find_duplicates,
    list_roots,
    list_tracks,
    record_playback,
    update_track,
    update_tracks,
)
from decksmith.scanner import discover_audio_files, scan_library


class ScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.music = self.root / "Music"
        self.music.mkdir()
        self.database_path = self.root / "decksmith.db"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_wave(self, name: str = "Test Track.wav") -> Path:
        path = self.music / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(44_100)
            audio.writeframes(b"\0\0\0\0" * 441)
        return path

    def test_discovery_ignores_non_audio_and_hidden_files(self) -> None:
        track = self.create_wave()
        (self.music / "notes.txt").write_text("not audio", encoding="utf-8")
        (self.music / ".hidden.mp3").write_bytes(b"")
        self.assertEqual(list(discover_audio_files(self.music)), [track])

    def test_scan_adds_then_skips_unchanged_track(self) -> None:
        track = self.create_wave()
        database = Database(self.database_path)

        first = scan_library(database, self.music)
        second = scan_library(database, self.music)

        self.assertEqual(first.tracks_added, 1)
        self.assertEqual(second.files_skipped, 1)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            row = connection.execute(
                "SELECT path, title, missing FROM tracks"
            ).fetchone()
        self.assertEqual(row, (str(track.resolve()), "Test Track", 0))

    def test_scan_marks_removed_track_missing_without_deleting_record(self) -> None:
        track = self.create_wave()
        database = Database(self.database_path)
        scan_library(database, self.music)
        track.unlink()

        scan_library(database, self.music)

        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            missing = connection.execute("SELECT missing FROM tracks").fetchone()[0]
        self.assertEqual(missing, 1)

    def test_cancelled_scan_does_not_mark_unvisited_tracks_missing(self) -> None:
        first = self.create_wave("A Track.wav")
        second = self.create_wave("B Track.wav")
        database = Database(self.database_path)
        scan_library(database, self.music)

        calls = 0
        def cancel_after_first_file() -> bool:
            nonlocal calls
            calls += 1
            return calls > 1

        result = scan_library(database, self.music, should_cancel=cancel_after_first_file)

        self.assertTrue(result.cancelled)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            rows = connection.execute(
                "SELECT path, missing FROM tracks ORDER BY path"
            ).fetchall()
        self.assertEqual(rows, [(str(first.resolve()), 0), (str(second.resolve()), 0)])

    def test_library_metadata_and_roots_are_persistent(self) -> None:
        audio_path = self.create_wave()
        database = Database(self.database_path)
        scan_library(database, self.music)
        track_id = list_tracks(database)[0]["id"]

        update_track(
            database,
            track_id,
            rating=4,
            tags=["sunset", "warm", "sunset"],
            color_tag="amber",
            mood="Uplifting",
            comment="Decksmith note",
        )

        track = list_tracks(database)[0]
        self.assertEqual(track["rating"], 4)
        self.assertEqual(track["tags"], "sunset,warm")
        self.assertEqual(track["color_tag"], "amber")
        self.assertEqual(track["mood"], "Uplifting")
        self.assertEqual(track["comment"], "Decksmith note")
        self.assertEqual(list_roots(database)[0]["track_count"], 1)

        audio_path.write_bytes(audio_path.read_bytes() + b"\0")
        scan_library(database, self.music)
        rescanned = list_tracks(database)[0]
        self.assertEqual(rescanned["mood"], "Uplifting")
        self.assertEqual(rescanned["comment"], "Decksmith note")

    def test_duplicates_require_identical_file_content(self) -> None:
        original = self.create_wave("Original.wav")
        shutil.copyfile(original, self.music / "Copy.wav")
        database = Database(self.database_path)
        scan_library(database, self.music)

        duplicates = find_duplicates(database)

        self.assertEqual(len(duplicates), 1)
        self.assertEqual(len(duplicates[0]["tracks"]), 2)

    def test_bulk_metadata_and_play_history_are_persistent(self) -> None:
        self.create_wave("First.wav")
        self.create_wave("Second.wav")
        database = Database(self.database_path)
        scan_library(database, self.music)
        ids = [track["id"] for track in list_tracks(database)]

        updated = update_tracks(
            database, ids, rating=5, tags=["peak", "tested"], color_tag="rose"
        )
        with database.connect() as connection:
            connection.execute(
                "UPDATE tracks SET updated_at = '2000-01-01 00:00:00' WHERE id = ?",
                (ids[0],),
            )
        record_playback(database, ids[0])
        tracks = list_tracks(database)

        self.assertEqual(updated, 2)
        self.assertTrue(all(track["rating"] == 5 for track in tracks))
        self.assertTrue(all(track["tags"] == "peak,tested" for track in tracks))
        played = next(track for track in tracks if track["id"] == ids[0])
        self.assertEqual(played["play_count"], 1)
        self.assertIsNotNone(played["last_played_at"])
        self.assertEqual(played["updated_at"], "2000-01-01 00:00:00")

    def test_version_two_database_migrates_without_losing_tracks(self) -> None:
        self.create_wave()
        database = Database(self.database_path)
        scan_library(database, self.music)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute("DROP INDEX IF EXISTS idx_tracks_content_hash")
            connection.execute("ALTER TABLE tracks DROP COLUMN content_hash")
            connection.execute("ALTER TABLE tracks DROP COLUMN color_tag")
            connection.execute("ALTER TABLE tracks DROP COLUMN rating")
            connection.execute("UPDATE schema_info SET version = 2")

        database.initialize()

        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(tracks)")}
            version = connection.execute("SELECT version FROM schema_info").fetchone()[0]
            count = connection.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        self.assertTrue({
            "rating", "color_tag", "content_hash", "analysis_bpm", "analysis_key",
            "analysis_status", "analysis_modified_ns", "last_played_at", "play_count",
            "mood", "user_comment",
        }.issubset(columns))
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
