from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from decksmith.analysis import (
    _tempo_near_reference,
    analysis_summary,
    analyze_tracks,
    camelot_key,
)
from decksmith.database import Database
from decksmith.library import list_tracks
from decksmith.scanner import scan_library


class AnalysisTests(unittest.TestCase):
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

    @staticmethod
    def fake_analyzer(_path: Path) -> dict[str, float | str]:
        return {
            "bpm": 123.45,
            "key": "8A",
            "scale": "minor",
            "strength": 0.88,
            "rhythm_confidence": 1.0,
            "energy_score": 0.72,
        }

    def test_camelot_mapping_is_stable(self) -> None:
        self.assertEqual(camelot_key("A", "minor"), "8A")
        self.assertEqual(camelot_key("C", "major"), "8B")

    def test_tempo_uses_library_bpm_to_resolve_half_time(self) -> None:
        self.assertAlmostEqual(_tempo_near_reference(160.7, 80.0), 80.35)
        self.assertAlmostEqual(_tempo_near_reference(128.0, 126.0), 128.0)

    def test_analysis_persists_results_and_skips_unchanged_track(self) -> None:
        self.create_wave("Analysed.wav")
        scan_library(self.database, self.music)

        first = analyze_tracks(self.database, analyzer=self.fake_analyzer)
        second = analyze_tracks(self.database, analyzer=self.fake_analyzer)
        track = list_tracks(self.database)[0]

        self.assertEqual(first.completed, 1)
        self.assertEqual(second.total, 0)
        self.assertEqual(track["bpm"], 123.45)
        self.assertEqual(track["musical_key"], "8A")
        self.assertEqual(track["analysis_status"], "completed")
        self.assertEqual(analysis_summary(self.database)["completed"], 1)

    def test_analysis_failure_isolated_per_track(self) -> None:
        self.create_wave("Broken.wav")
        self.create_wave("Good.wav")
        scan_library(self.database, self.music)

        def analyzer(path: Path) -> dict[str, float | str]:
            if path.name == "Broken.wav":
                raise ValueError("test failure")
            return self.fake_analyzer(path)

        result = analyze_tracks(self.database, analyzer=analyzer)

        self.assertEqual(result.completed, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(analysis_summary(self.database)["failed"], 1)

    def test_cancelled_analysis_leaves_remaining_tracks_resumable(self) -> None:
        self.create_wave("First.wav")
        self.create_wave("Second.wav")
        scan_library(self.database, self.music)
        calls = 0

        def should_cancel() -> bool:
            nonlocal calls
            calls += 1
            return calls > 1

        result = analyze_tracks(
            self.database,
            analyzer=self.fake_analyzer,
            should_cancel=should_cancel,
        )

        self.assertTrue(result.cancelled)
        self.assertEqual(result.completed, 1)
        self.assertEqual(analysis_summary(self.database)["pending"], 1)


if __name__ == "__main__":
    unittest.main()
