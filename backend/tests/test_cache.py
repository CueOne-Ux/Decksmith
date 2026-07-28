from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from decksmith.cache import cache_status, prune_cache
from decksmith.database import Database
from decksmith.library import list_tracks
from decksmith.projects import add_track_to_project, create_project, load_project
from decksmith.scanner import scan_library


class CacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.music = self.root / "Music"
        self.cache = self.root / "Cache"
        self.music.mkdir()
        self.cache.mkdir()
        self.source = self.music / "Source.mp3"
        self.source.write_bytes(b"source-audio-that-must-survive")
        self.database = Database(self.root / "decksmith.db")
        scan_library(self.database, self.music)
        self.track = list_tracks(self.database)[0]
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE tracks SET duration_seconds = 60 WHERE id = ?", (self.track["id"],)
            )
        project = create_project(self.database, "Cache safety", 120)
        state = add_track_to_project(
            self.database, project["project"]["id"], self.track["id"], 1
        )
        self.project_id = project["project"]["id"]
        self.clip_id = state["selected_clip_id"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_prune_removes_only_unreferenced_app_owned_derivatives(self) -> None:
        renders = self.cache / "renders"
        stems = self.cache / "stems" / "active"
        orphan_stems = self.cache / "stems" / "orphan"
        renders.mkdir(parents=True)
        stems.mkdir(parents=True)
        orphan_stems.mkdir(parents=True)
        active_render = renders / "active.wav"
        active_waveform = renders / "active.waveform.png"
        orphan_render = renders / "orphan.wav"
        active_stem = stems / "vocals.wav"
        orphan_stem = orphan_stems / "vocals.wav"
        for path, content in (
            (active_render, b"active-render"), (active_waveform, b"waveform"),
            (orphan_render, b"orphan-render"), (active_stem, b"active-stem"),
            (orphan_stem, b"orphan-stem"),
        ):
            path.write_bytes(content)
        with self.database.connect() as connection:
            modified_ns = connection.execute(
                "SELECT modified_ns FROM tracks WHERE id = ?", (self.track["id"],)
            ).fetchone()["modified_ns"]
            connection.execute(
                """
                INSERT INTO render_cache(
                    clip_id, signature, source_modified_ns, path, file_size, duration_seconds
                ) VALUES (?, 'signature', ?, ?, ?, 1)
                """,
                (self.clip_id, modified_ns, str(active_render), active_render.stat().st_size),
            )
            connection.execute(
                """
                INSERT INTO stem_cache(
                    track_id, stem_kind, model, source_modified_ns, path, file_size
                ) VALUES (?, 'vocals', 'htdemucs', ?, ?, ?)
                """,
                (self.track["id"], modified_ns, str(active_stem), active_stem.stat().st_size),
            )
        before = cache_status(self.database, self.cache)
        self.assertEqual(before["categories"]["renders"]["reclaimable_files"], 1)
        self.assertEqual(before["categories"]["stems"]["reclaimable_files"], 1)
        source_bytes = self.source.read_bytes()

        result = prune_cache(self.database, self.cache)
        self.assertEqual(result["removed_files"], 2)
        self.assertTrue(active_render.is_file())
        self.assertTrue(active_waveform.is_file())
        self.assertTrue(active_stem.is_file())
        self.assertFalse(orphan_render.exists())
        self.assertFalse(orphan_stem.exists())
        self.assertEqual(self.source.read_bytes(), source_bytes)
        self.assertEqual(len(load_project(self.database, self.project_id)["clips"]), 1)


if __name__ == "__main__":
    unittest.main()
