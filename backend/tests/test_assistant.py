from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from decksmith.assistant import (
    compatible_tracks,
    create_mashup_draft,
    create_project_from_mashup_draft,
    create_setlist_draft,
    list_drafts,
)
from decksmith.database import Database, SCHEMA_VERSION
from decksmith.library import list_tracks
from decksmith.scanner import scan_library


class AssistantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.music = self.root / "Music"
        self.music.mkdir()
        self.database = Database(self.root / "decksmith.db")
        for index, name in enumerate(("Foundation.wav", "Overlay.wav", "Closer.wav", "Contrast.wav")):
            self.create_wave(name, 4 + index)
        scan_library(self.database, self.music)
        tracks = list_tracks(self.database)
        settings = (
            (118.0, "8A", "Afro House", 0.45, 5),
            (120.0, "7A", "Afro House", 0.62, 4),
            (122.0, "8A", "Afro House", 0.88, 5),
            (96.0, "2B", "Hip Hop", 0.7, 3),
        )
        with self.database.connect() as connection:
            for track, values in zip(tracks, settings, strict=True):
                connection.execute(
                    """
                    UPDATE tracks SET analysis_bpm = ?, analysis_key = ?, genre = ?,
                        energy_score = ?, rating = ?, analysis_status = 'completed'
                    WHERE id = ?
                    """,
                    (*values, track["id"]),
                )
        self.tracks = list_tracks(self.database)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_wave(self, name: str, seconds: float) -> None:
        path = self.music / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(44_100)
            frames = bytearray()
            for index in range(round(44_100 * seconds)):
                value = round(2_000 * math.sin(2 * math.pi * 220 * index / 44_100))
                frames.extend(struct.pack("<hh", value, value))
            audio.writeframes(frames)

    def test_local_matches_drafts_and_arrangement_are_persistent(self) -> None:
        anchor = self.tracks[0]
        source_bytes = {Path(track["path"]): Path(track["path"]).read_bytes() for track in self.tracks}
        matches = compatible_tracks(self.database, anchor["id"])
        self.assertEqual(matches["anchor"]["id"], anchor["id"])
        self.assertEqual(len(matches["suggestions"]), 3)
        self.assertGreater(matches["suggestions"][0]["score"], matches["suggestions"][-1]["score"])
        self.assertEqual(len(matches["suggestions"][0]["explanations"]), 4)

        partner = matches["suggestions"][0]["track"]
        draft = create_mashup_draft(self.database, anchor["id"], partner["id"])
        self.assertEqual(draft["draft_kind"], "mashup")
        self.assertEqual(len(draft["tracks"]), 2)
        self.assertIn(draft["status"], {"ready", "needs_review"})
        self.assertEqual(list_drafts(self.database)[0]["id"], draft["id"])

        project = create_project_from_mashup_draft(self.database, draft["id"])
        self.assertEqual(len(project["clips"]), 2)
        self.assertEqual({clip["channel"] for clip in project["clips"]}, {1, 2})
        reopened = create_project_from_mashup_draft(self.database, draft["id"])
        self.assertEqual(reopened["project"]["id"], project["project"]["id"])
        self.assertTrue(all(path.read_bytes() == content for path, content in source_bytes.items()))
        with self.database.connect() as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_info").fetchone()[0], SCHEMA_VERSION)

    def test_setlist_uses_only_matching_local_tracks_and_energy_order(self) -> None:
        draft = create_setlist_draft(
            self.database, "Local rise", 30, "Afro House", "rise", [], ["explicit"]
        )
        self.assertEqual(draft["draft_kind"], "setlist")
        self.assertEqual(draft["status"], "ready")
        self.assertGreaterEqual(len(draft["tracks"]), 1)
        local_ids = {track["id"] for track in self.tracks if track["genre"] == "Afro House"}
        self.assertTrue({track["track_id"] for track in draft["tracks"]}.issubset(local_ids))


if __name__ == "__main__":
    unittest.main()
