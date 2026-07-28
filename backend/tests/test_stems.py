from __future__ import annotations

import shutil
import tempfile
import unittest
import wave
from pathlib import Path

from decksmith.database import Database, SCHEMA_VERSION
from decksmith.library import list_tracks
from decksmith.scanner import scan_library
from decksmith.stems import (
    STEM_KINDS,
    _runtime_candidates,
    separate_track_stems,
    stem_capability,
    stem_status,
)


class StemEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.music = self.root / "Music"
        self.cache = self.root / "Cache" / "stems"
        self.music.mkdir()
        self.database = Database(self.root / "decksmith.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_wave(self, name: str, seconds: float = 1.0) -> Path:
        path = self.music / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(44_100)
            audio.writeframes(b"\0\0" * round(44_100 * seconds))
        return path

    @staticmethod
    def fake_separator(source: Path, working: Path, model: str, should_cancel):
        outputs = {}
        for stem_kind in STEM_KINDS:
            path = working / f"{stem_kind}.wav"
            shutil.copy2(source, path)
            outputs[stem_kind] = path
        return outputs

    def test_four_stems_are_cached_atomically_without_modifying_source(self) -> None:
        source = self.create_wave("Stem source.wav")
        source_bytes = source.read_bytes()
        scan_library(self.database, self.music)
        track = list_tracks(self.database)[0]
        progress = []

        result = separate_track_stems(
            self.database,
            track["id"],
            self.cache,
            separator=self.fake_separator,
            progress=lambda state: progress.append(state.to_dict()),
        )
        status = stem_status(self.database, [track["id"]])

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.stem_count, 4)
        self.assertEqual(status["ready_track_ids"], [track["id"]])
        self.assertEqual({item["stem_kind"] for item in status["stems"]}, set(STEM_KINDS))
        self.assertTrue(all(Path(item["path"]).is_relative_to(self.cache) for item in status["stems"]))
        self.assertTrue(all(Path(item["path"]).is_file() for item in status["stems"]))
        self.assertEqual(status["jobs"][0]["status"], "completed")
        self.assertEqual([item["phase"] for item in progress], ["queued", "separating", "validating", "completed"])
        self.assertEqual(source.read_bytes(), source_bytes)
        with self.database.connect() as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_info").fetchone()[0], SCHEMA_VERSION)

        def must_not_run(source, working, model, should_cancel):
            raise AssertionError("A valid cache should not run separation again")

        cached = separate_track_stems(
            self.database, track["id"], self.cache, separator=must_not_run
        )
        self.assertTrue(cached.cached)
        self.assertEqual(cached.stem_count, 4)
        self.assertEqual(source.read_bytes(), source_bytes)

    def test_cancellation_and_invalid_outputs_never_publish_partial_cache(self) -> None:
        source = self.create_wave("Cancelled source.wav")
        source_bytes = source.read_bytes()
        scan_library(self.database, self.music)
        track = list_tracks(self.database)[0]

        cancelled = separate_track_stems(
            self.database,
            track["id"],
            self.cache,
            separator=self.fake_separator,
            should_cancel=lambda: True,
        )
        status = stem_status(self.database, [track["id"]])
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(status["stems"], [])
        self.assertEqual(status["jobs"][0]["status"], "cancelled")

        outside = self.root / "outside.wav"
        shutil.copy2(source, outside)

        def unsafe_separator(source, working, model, should_cancel):
            return {stem_kind: outside for stem_kind in STEM_KINDS}

        with self.assertRaisesRegex(RuntimeError, "outside Decksmith's cache"):
            separate_track_stems(
                self.database,
                track["id"],
                self.cache,
                force=True,
                separator=unsafe_separator,
            )
        failed = stem_status(self.database, [track["id"]])
        self.assertEqual(failed["stems"], [])
        self.assertEqual(failed["jobs"][0]["status"], "failed")
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertFalse(any((self.cache / ".working").iterdir()))

    def test_capability_is_explicit_when_optional_engine_is_absent(self) -> None:
        capability = stem_capability()
        self.assertEqual(capability["engine"], "Demucs")
        self.assertIn("available", capability)
        self.assertIn("message", capability)
        self.assertIn("runtime", capability)
        self.assertIn("python_version", capability)
        if capability["available"]:
            self.assertIn(
                capability["runtime"],
                {"bundled", "configured", "isolated", "application"},
            )
            self.assertTrue(capability["version"])
            self.assertTrue(capability["python_version"])

    def test_isolated_runtime_keeps_the_virtual_environment_interpreter_path(self) -> None:
        candidates = dict(_runtime_candidates())
        isolated = candidates["isolated"]
        self.assertTrue(isolated.is_absolute())
        self.assertIn(".venv-stems", isolated.parts)
        if isolated.is_symlink():
            self.assertNotEqual(isolated, isolated.resolve())


if __name__ == "__main__":
    unittest.main()
