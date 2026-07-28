from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from decksmith.artwork import extract_artwork
from decksmith.database import Database
from decksmith.library import list_tracks, record_playback, update_track
from decksmith.scanner import scan_library
from decksmith.smart_playlists import (
    create_smart_playlist,
    delete_smart_playlist,
    list_smart_playlists,
    smart_playlist_track_ids,
    validate_rules,
)


class SmartPlaylistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.music = self.root / "Music"
        self.music.mkdir()
        self.database = Database(self.root / "decksmith.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_wave(self, name: str) -> Path:
        path = self.music / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(44_100)
            audio.writeframes(b"\0\0" * 4_410)
        return path

    def test_smart_playlist_rules_match_and_persist(self) -> None:
        self.create_wave("Played.wav")
        self.create_wave("Unplayed.wav")
        scan_library(self.database, self.music)
        tracks = list_tracks(self.database)
        played = next(track for track in tracks if track["title"] == "Played")
        unplayed = next(track for track in tracks if track["title"] == "Unplayed")
        update_track(
            self.database, played["id"], rating=5, tags=["peak"], mood="Driving"
        )
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE tracks SET energy_score = 0.86 WHERE id = ?", (played["id"],)
            )
        update_track(self.database, unplayed["id"], rating=2, tags=["warm"])
        record_playback(self.database, played["id"])

        favourite = create_smart_playlist(
            self.database,
            "Peak favourites",
            {
                "min_rating": 4,
                "tag": "peak",
                "mood": "Driving",
                "energy_min": 0.78,
            },
        )
        unheard = create_smart_playlist(self.database, "Unheard", {"unplayed": True})

        self.assertEqual(smart_playlist_track_ids(self.database, favourite["id"]), [played["id"]])
        self.assertEqual(smart_playlist_track_ids(self.database, unheard["id"]), [unplayed["id"]])
        self.assertEqual(len(list_smart_playlists(self.database)), 2)
        self.assertTrue(delete_smart_playlist(self.database, favourite["id"]))

    def test_smart_playlist_rejects_unknown_or_empty_rules(self) -> None:
        with self.assertRaises(ValueError):
            validate_rules({})
        with self.assertRaises(ValueError):
            validate_rules({"sql": "DROP TABLE tracks"})

    def test_embedded_artwork_is_cached_without_modifying_audio(self) -> None:
        from mutagen.id3 import APIC, ID3

        path = self.music / "Artwork.mp3"
        tags = ID3()
        tags.add(APIC(mime="image/jpeg", type=3, desc="Cover", data=b"\xff\xd8\xffmock-jpeg"))
        tags.save(path)
        original = path.read_bytes()
        scan_library(self.database, self.music)
        track_id = list_tracks(self.database)[0]["id"]

        first = extract_artwork(self.database, track_id, self.root / "artwork-cache")
        second = extract_artwork(self.database, track_id, self.root / "artwork-cache")

        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(first.read_bytes(), b"\xff\xd8\xffmock-jpeg")
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
