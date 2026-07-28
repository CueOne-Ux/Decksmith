from __future__ import annotations

import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from decksmith.database import Database
from decksmith.scanner import scan_library
from decksmith.serato import crate_track_ids, decode_records, list_crates, parse_crate, sync_serato_crates
from decksmith.waveform import generate_waveform


def record(tag: str, value: bytes) -> bytes:
    return tag.encode("ascii") + struct.pack(">I", len(value)) + value


def text_record(tag: str, value: str) -> bytes:
    return record(tag, value.encode("utf-16-be"))


class SeratoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.music = self.root / "Music"
        self.music.mkdir()
        self.serato = self.music / "_Serato_"
        (self.serato / "Subcrates").mkdir(parents=True)
        self.database = Database(self.root / "decksmith.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_wave(self, name: str, seconds: float = 0.1) -> Path:
        path = self.music / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(44_100)
            audio.writeframes(b"\0\0" * round(44_100 * seconds))
        return path

    def create_crate(self, name: str, tracks: list[str]) -> Path:
        payload = text_record("vrsn", "1.0/Serato ScratchLive Crate")
        payload += record("ovct", text_record("tvcn", "song") + text_record("tvcw", "250"))
        for track in tracks:
            payload += record("otrk", text_record("ptrk", track))
        path = self.serato / "Subcrates" / f"{name}.crate"
        path.write_bytes(payload)
        return path

    def test_record_decoder_rejects_truncated_data(self) -> None:
        with self.assertRaises(ValueError):
            decode_records(b"otrk\0\0\0\x10short")

    def test_crate_parser_preserves_hierarchy_and_track_order(self) -> None:
        crate_file = self.create_crate("Wedding%%Dinner", ["First.wav", "Second.wav"])

        crate = parse_crate(crate_file, self.serato)

        self.assertEqual(crate.hierarchy, ["Wedding", "Dinner"])
        self.assertEqual(crate.name, "Dinner")
        self.assertEqual(crate.tracks, [self.music / "First.wav", self.music / "Second.wav"])

    def test_serato_sync_matches_indexed_tracks_without_writing_crate(self) -> None:
        first = self.create_wave("First.wav")
        second = self.create_wave("Second.wav")
        crate_file = self.create_crate("Set", [first.name, second.name])
        original = crate_file.read_bytes()
        scan_library(self.database, self.music)

        result = sync_serato_crates(self.database, [self.serato])
        crates = list_crates(self.database)
        ids = crate_track_ids(self.database, crates[0]["id"])

        self.assertEqual(result, {"libraries": 1, "crates": 1, "tracks": 2, "errors": 0})
        self.assertEqual(crates[0]["matched_count"], 2)
        self.assertEqual(len(ids), 2)
        self.assertEqual(crate_file.read_bytes(), original)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
    def test_waveform_generation_is_cached(self) -> None:
        source = self.create_wave("Preview.wav", 1)
        source_bytes = source.read_bytes()
        scan_library(self.database, self.music)
        with self.database.connect() as connection:
            track_id = connection.execute("SELECT id FROM tracks").fetchone()[0]

        first = generate_waveform(self.database, track_id, self.root / "cache")
        second = generate_waveform(self.database, track_id, self.root / "cache")

        self.assertEqual(first, second)
        self.assertTrue(first.is_file())
        self.assertGreater(first.stat().st_size, 0)
        width, height = struct.unpack(">II", first.read_bytes()[16:24])
        self.assertEqual((width, height), (16384, 256))
        self.assertEqual(source.read_bytes(), source_bytes)


if __name__ == "__main__":
    unittest.main()
