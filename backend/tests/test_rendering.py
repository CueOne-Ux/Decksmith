from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from decksmith.database import Database, SCHEMA_VERSION
from decksmith.consolidation import (
    bounce_timeline_clip,
    freeze_timeline_clip,
    unfreeze_timeline_clip,
)
from decksmith.library import list_tracks
from decksmith.projects import (
    add_track_to_project,
    create_project,
    duplicate_timeline_clip,
    redo_project,
    set_timeline_clip_source,
    split_timeline_clip,
    undo_project,
    update_clip_stem_state,
    update_timeline_clip,
)
from decksmith.rendering import (
    _atempo_filters,
    _clip_rows,
    render_capability,
    render_clip,
    render_status,
)
from decksmith.scanner import scan_library


class RenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.music = self.root / "Music"
        self.cache = self.root / "Cache" / "renders"
        self.music.mkdir()
        self.database = Database(self.root / "decksmith.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_wave(self, name: str, seconds: float = 4.0) -> Path:
        path = self.music / name
        sample_rate = 44_100
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            frames = bytearray()
            for index in range(round(sample_rate * seconds)):
                left = round(8_000 * math.sin(2 * math.pi * 220 * index / sample_rate))
                right = round(8_000 * math.sin(2 * math.pi * 330 * index / sample_rate))
                frames.extend(struct.pack("<hh", left, right))
            audio.writeframes(frames)
        return path

    @staticmethod
    def fake_renderer(clip, source, output, executable, should_cancel) -> None:
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(44_100)
            audio.writeframes(b"\0\0\0\0" * round(44_100 * clip["duration_seconds"]))

    def prepared_clip(self) -> tuple[Path, int]:
        source = self.create_wave("Render source.wav")
        scan_library(self.database, self.music)
        track = list_tracks(self.database)[0]
        project = create_project(self.database, "Render study", 120)
        state = add_track_to_project(self.database, project["project"]["id"], track["id"], 1)
        clip_id = state["selected_clip_id"]
        update_timeline_clip(
            self.database,
            clip_id,
            {
                "source_in_seconds": 0.5,
                "duration_seconds": 2,
                "tempo_percent": 150,
                "pitch_semitones": 3,
                "reversed": True,
            },
        )
        return source, clip_id

    def test_render_is_cached_atomically_and_source_safe(self) -> None:
        source, clip_id = self.prepared_clip()
        source_bytes = source.read_bytes()
        progress = []
        rendered = render_clip(
            self.database,
            clip_id,
            self.cache,
            renderer=self.fake_renderer,
            progress=lambda state: progress.append(state.to_dict()),
        )
        status = render_status(self.database, [clip_id])

        self.assertEqual(rendered.status, "completed")
        self.assertEqual(status["ready_clip_ids"], [clip_id])
        self.assertEqual(len(status["renders"]), 1)
        output = Path(status["renders"][0]["path"])
        self.assertTrue(output.is_relative_to(self.cache))
        self.assertTrue(output.is_file())
        self.assertEqual([item["phase"] for item in progress], [
            "queued", "rendering", "validating", "completed",
        ])
        self.assertEqual(source.read_bytes(), source_bytes)
        with self.database.connect() as connection:
            self.assertEqual(connection.execute("SELECT version FROM schema_info").fetchone()[0], SCHEMA_VERSION)

        def must_not_run(*args):
            raise AssertionError("A valid render cache should be reused")

        cached = render_clip(
            self.database, clip_id, self.cache, renderer=must_not_run
        )
        self.assertTrue(cached.cached)
        self.assertEqual(cached.path, str(output))

        update_timeline_clip(self.database, clip_id, {"pitch_semitones": 5})
        stale = render_status(self.database, [clip_id])
        self.assertEqual(stale["ready_clip_ids"], [])
        self.assertEqual(stale["jobs"][0]["stale"], 1)
        self.assertEqual(source.read_bytes(), source_bytes)

    def test_cancellation_never_publishes_a_partial_render(self) -> None:
        source, clip_id = self.prepared_clip()
        source_bytes = source.read_bytes()
        cancelled = render_clip(
            self.database,
            clip_id,
            self.cache,
            renderer=self.fake_renderer,
            should_cancel=lambda: True,
        )
        status = render_status(self.database, [clip_id])
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(status["renders"], [])
        self.assertEqual(status["jobs"][0]["status"], "cancelled")
        self.assertEqual(source.read_bytes(), source_bytes)

    def test_stem_clip_render_reads_the_isolated_cached_file(self) -> None:
        source, clip_id = self.prepared_clip()
        stem = self.root / "vocals.wav"
        stem.write_bytes(source.read_bytes())
        with self.database.connect() as connection:
            clip = connection.execute(
                "SELECT track_id FROM timeline_clips WHERE id = ?", (clip_id,)
            ).fetchone()
            modified_ns = connection.execute(
                "SELECT modified_ns FROM tracks WHERE id = ?", (clip["track_id"],)
            ).fetchone()["modified_ns"]
            connection.execute(
                """
                INSERT INTO stem_cache(
                    track_id, stem_kind, model, source_modified_ns, path, file_size
                ) VALUES (?, 'vocals', 'htdemucs', ?, ?, ?)
                """,
                (clip["track_id"], modified_ns, str(stem), stem.stat().st_size),
            )
        set_timeline_clip_source(self.database, clip_id, "vocals")
        rendered_source: list[Path] = []

        def capture_source(clip, source_path, output, executable, should_cancel) -> None:
            rendered_source.append(source_path)
            self.fake_renderer(clip, source_path, output, executable, should_cancel)

        result = render_clip(
            self.database, clip_id, self.cache, renderer=capture_source
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(rendered_source, [stem])

    def test_parent_song_render_follows_persistent_stem_mute_and_solo(self) -> None:
        source, clip_id = self.prepared_clip()
        stem_paths: dict[str, Path] = {}
        with self.database.connect() as connection:
            clip = connection.execute(
                "SELECT track_id FROM timeline_clips WHERE id = ?", (clip_id,)
            ).fetchone()
            modified_ns = connection.execute(
                "SELECT modified_ns FROM tracks WHERE id = ?", (clip["track_id"],)
            ).fetchone()["modified_ns"]
            for kind in ("vocals", "drums", "bass", "other"):
                stem = self.root / f"{kind}.wav"
                stem.write_bytes(source.read_bytes())
                stem_paths[kind] = stem
                connection.execute(
                    """
                    INSERT INTO stem_cache(
                        track_id, stem_kind, model, source_modified_ns, path, file_size
                    ) VALUES (?, ?, 'htdemucs', ?, ?, ?)
                    """,
                    (clip["track_id"], kind, modified_ns, str(stem), stem.stat().st_size),
                )

        update_clip_stem_state(self.database, clip_id, "vocals", muted=True)
        instrumental = _clip_rows(self.database, [clip_id])[0]
        self.assertEqual(instrumental["stem_mix_kinds"], ["drums", "bass", "other"])
        self.assertEqual(
            instrumental["stem_mix_sources"],
            [str(stem_paths[kind]) for kind in ("drums", "bass", "other")],
        )
        first = render_clip(self.database, clip_id, self.cache, renderer=self.fake_renderer)

        update_clip_stem_state(self.database, clip_id, "vocals", solo=True)
        acapella = _clip_rows(self.database, [clip_id])[0]
        self.assertEqual(acapella["stem_mix_kinds"], ["vocals"])
        self.assertEqual(acapella["stem_mix_sources"], [str(stem_paths["vocals"])])
        self.assertEqual(render_status(self.database, [clip_id])["ready_clip_ids"], [])
        second = render_clip(self.database, clip_id, self.cache, renderer=self.fake_renderer)
        self.assertNotEqual(first.path, second.path)

        update_clip_stem_state(self.database, clip_id, "vocals", solo=False)
        for kind in ("vocals", "drums", "bass", "other"):
            update_clip_stem_state(self.database, clip_id, kind, muted=True)
        silence = _clip_rows(self.database, [clip_id])[0]
        self.assertTrue(silence["stem_mix_silence"])
        self.assertEqual(silence["stem_mix_kinds"], [])

        if render_capability()["available"]:
            for kind in ("vocals", "drums", "bass", "other"):
                update_clip_stem_state(self.database, clip_id, kind, muted=False)
            update_clip_stem_state(self.database, clip_id, "vocals", muted=True)
            mixed = render_clip(self.database, clip_id, self.cache, force=True)
            with wave.open(mixed.path, "rb") as audio:
                self.assertEqual(audio.getnchannels(), 2)
                self.assertEqual(audio.getframerate(), 44_100)
                self.assertAlmostEqual(
                    audio.getnframes() / audio.getframerate(), 2.0, places=2
                )

    def test_atempo_chain_covers_the_full_safe_edit_range(self) -> None:
        self.assertEqual(_atempo_filters(1), [])
        self.assertEqual(_atempo_filters(0.25), ["atempo=0.5", "atempo=0.5"])
        self.assertEqual(_atempo_filters(4), ["atempo=2", "atempo=2"])

    def test_freeze_unfreeze_and_bounce_publish_stable_editable_sources(self) -> None:
        source, clip_id = self.prepared_clip()
        source_bytes = source.read_bytes()
        rendered = render_clip(
            self.database, clip_id, self.cache, renderer=self.fake_renderer
        )
        consolidated = self.root / "Cache" / "consolidated"

        frozen = freeze_timeline_clip(self.database, clip_id, consolidated)
        frozen_clip = next(clip for clip in frozen["clips"] if clip["id"] == clip_id)
        frozen_path = Path(frozen_clip["path"])
        self.assertEqual(frozen_clip["clip_kind"], "rendered")
        self.assertEqual(frozen_clip["rendered_mode"], "freeze")
        self.assertEqual(frozen_clip["source_in_seconds"], 0)
        self.assertEqual(frozen_clip["tempo_percent"], 100)
        self.assertEqual(frozen_clip["pitch_semitones"], 0)
        self.assertEqual(frozen_clip["reversed"], 0)
        self.assertTrue(frozen_path.is_relative_to(consolidated))
        self.assertEqual(frozen_path.read_bytes(), Path(rendered.path).read_bytes())

        restored = unfreeze_timeline_clip(self.database, clip_id)
        restored_clip = next(clip for clip in restored["clips"] if clip["id"] == clip_id)
        self.assertEqual(restored_clip["clip_kind"], "song")
        self.assertEqual(restored_clip["source_in_seconds"], 0.5)
        self.assertEqual(restored_clip["tempo_percent"], 150)
        self.assertEqual(restored_clip["pitch_semitones"], 3)
        self.assertEqual(restored_clip["reversed"], 1)

        bounced = bounce_timeline_clip(self.database, clip_id, consolidated)
        bounce_id = bounced["selected_clip_id"]
        bounced_clip = next(clip for clip in bounced["clips"] if clip["id"] == bounce_id)
        self.assertEqual(bounced_clip["clip_kind"], "rendered")
        self.assertEqual(bounced_clip["rendered_mode"], "bounce")
        self.assertEqual(bounced_clip["start_seconds"], 2)
        self.assertEqual(bounced_clip["duration_seconds"], 2)
        self.assertTrue(Path(bounced_clip["path"]).is_file())
        self.assertEqual(source.read_bytes(), source_bytes)

        project_id = int(bounced["project"]["id"])
        undone = undo_project(self.database, project_id)
        self.assertEqual(len(undone["clips"]), 1)
        redone = redo_project(self.database, project_id)
        restored_bounce = next(clip for clip in redone["clips"] if clip["id"] == bounce_id)
        self.assertEqual(restored_bounce["rendered_mode"], "bounce")
        self.assertEqual(restored_bounce["path"], bounced_clip["path"])

        duplicated = duplicate_timeline_clip(self.database, bounce_id)
        duplicate_id = duplicated["selected_clip_id"]
        duplicate = next(clip for clip in duplicated["clips"] if clip["id"] == duplicate_id)
        self.assertEqual(duplicate["rendered_mode"], "bounce")
        self.assertEqual(duplicate["path"], bounced_clip["path"])
        split = split_timeline_clip(self.database, duplicate_id, 1)
        split_copy = next(
            clip for clip in split["clips"]
            if clip["id"] not in {clip_id, bounce_id, duplicate_id}
        )
        self.assertEqual(split_copy["rendered_mode"], "bounce")
        self.assertEqual(split_copy["path"], bounced_clip["path"])

    @unittest.skipUnless(render_capability()["available"], "FFmpeg is not installed")
    def test_real_ffmpeg_render_has_exact_timeline_duration(self) -> None:
        source, clip_id = self.prepared_clip()
        source_bytes = source.read_bytes()
        rendered = render_clip(self.database, clip_id, self.cache)
        with wave.open(rendered.path, "rb") as audio:
            self.assertEqual(audio.getnchannels(), 2)
            self.assertEqual(audio.getframerate(), 44_100)
            self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 2.0, places=2)
        self.assertEqual(source.read_bytes(), source_bytes)


if __name__ == "__main__":
    unittest.main()
