from __future__ import annotations

import sqlite3
import tempfile
import unittest
import wave
from contextlib import closing
from pathlib import Path

from decksmith.database import Database
from decksmith.library import list_tracks
from decksmith.projects import (
    add_stem_to_project,
    add_track_to_project,
    batch_update_timeline_clips,
    create_project_marker,
    create_project,
    crossfade_timeline_clips,
    delete_project_marker,
    delete_timeline_clips,
    duplicate_timeline_clip,
    group_timeline_clips,
    list_project_history,
    list_projects,
    load_project,
    quantize_timeline_clip,
    redo_project,
    resize_timeline_clip,
    split_timeline_clip,
    set_timeline_clip_source,
    shift_timeline_group_channels,
    trim_timeline_clips_to_selection,
    undo_project,
    ungroup_timeline_clips,
    update_project,
    update_project_marker,
    update_project_selection,
    update_clip_stem_state,
    update_timeline_clip,
)
from decksmith.scanner import scan_library


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.music = self.root / "Music"
        self.music.mkdir()
        self.database = Database(self.root / "decksmith.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_wave(self, name: str, seconds: float = 2.0) -> Path:
        path = self.music / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(44_100)
            audio.writeframes(b"\0\0" * round(44_100 * seconds))
        return path

    def test_project_persists_four_channels_without_copying_source_audio(self) -> None:
        sources = [self.create_wave(f"Track {index}.wav", 2 + index) for index in range(1, 5)]
        original_bytes = {path: path.read_bytes() for path in sources}
        scan_library(self.database, self.music)
        tracks = list_tracks(self.database)

        created = create_project(self.database, "First arrangement", 118.5)
        project_id = created["project"]["id"]
        for channel, track in enumerate(tracks, 1):
            add_track_to_project(self.database, project_id, track["id"], channel)

        reopened = load_project(Database(self.database.path), project_id)
        summaries = list_projects(self.database)

        self.assertEqual(reopened["project"]["name"], "First arrangement")
        self.assertEqual(reopened["project"]["tempo"], 118.5)
        self.assertEqual(len(reopened["clips"]), 4)
        self.assertEqual({clip["channel"] for clip in reopened["clips"]}, {1, 2, 3, 4})
        self.assertEqual({clip["path"] for clip in reopened["clips"]}, {str(path) for path in sources})
        self.assertEqual(summaries[0]["clip_count"], 4)
        self.assertEqual(set(self.root.rglob("*.wav")), set(sources))
        for path, data in original_bytes.items():
            self.assertEqual(path.read_bytes(), data)

    def test_clip_updates_are_validated_locked_and_snapshotted(self) -> None:
        source = self.create_wave("Movable.wav", 8)
        source_bytes = source.read_bytes()
        scan_library(self.database, self.music)
        track = list_tracks(self.database)[0]
        project = create_project(self.database, "Movement", 120)
        project_id = project["project"]["id"]
        state = add_track_to_project(self.database, project_id, track["id"], 1, 4)
        clip_id = state["selected_clip_id"]

        moved = update_timeline_clip(
            self.database,
            clip_id,
            {"channel": 3, "start_seconds": 12.5, "gain_db": -3, "expanded": True},
        )
        clip = moved["clips"][0]
        self.assertEqual(clip["channel"], 3)
        self.assertEqual(clip["start_seconds"], 12.5)
        self.assertEqual(clip["gain_db"], -3)
        self.assertEqual(clip["expanded"], 1)

        update_timeline_clip(self.database, clip_id, {"locked": True})
        with self.assertRaisesRegex(ValueError, "Unlock"):
            update_timeline_clip(self.database, clip_id, {"start_seconds": 14})

        renamed = update_project(self.database, project_id, "Movement study", 122)
        history = list_project_history(self.database, project_id)
        self.assertEqual(renamed["project"]["name"], "Movement study")
        self.assertGreaterEqual(len(history), 5)
        self.assertEqual(source.read_bytes(), source_bytes)

    def test_cached_stems_become_independent_editable_timeline_clips(self) -> None:
        source = self.create_wave("Stem source.wav", 8)
        scan_library(self.database, self.music)
        track = list_tracks(self.database)[0]
        project = create_project(self.database, "Stem arrangement", 120)
        state = add_track_to_project(
            self.database, project["project"]["id"], track["id"], 1, 6
        )
        clip_id = state["selected_clip_id"]
        update_timeline_clip(
            self.database,
            clip_id,
            {
                "source_in_seconds": 1,
                "duration_seconds": 5,
                "gain_db": -2,
                "eq_high_db": 2.5,
                "lowpass_hz": 15000,
                "compressor_ratio": 6,
            },
        )
        stem_root = self.root / "Stem Cache"
        stem_root.mkdir()
        with self.database.connect() as connection:
            modified_ns = connection.execute(
                "SELECT modified_ns FROM tracks WHERE id = ?", (track["id"],)
            ).fetchone()["modified_ns"]
            for kind in ("vocals", "drums", "bass", "other"):
                stem_path = stem_root / f"{kind}.wav"
                stem_path.write_bytes(source.read_bytes())
                connection.execute(
                    """
                    INSERT INTO stem_cache(
                        track_id, stem_kind, model, source_modified_ns, path, file_size
                    ) VALUES (?, ?, 'htdemucs', ?, ?, ?)
                    """,
                    (track["id"], kind, modified_ns, str(stem_path), stem_path.stat().st_size),
                )

        isolated = set_timeline_clip_source(self.database, clip_id, "vocals")
        isolated_clip = isolated["clips"][0]
        self.assertEqual(isolated_clip["clip_kind"], "vocals")
        self.assertEqual(isolated_clip["path"], str(stem_root / "vocals.wav"))

        added = add_stem_to_project(self.database, clip_id, "drums", 3, 9.25)
        drum_clip = next(clip for clip in added["clips"] if clip["id"] == added["selected_clip_id"])
        self.assertEqual(drum_clip["clip_kind"], "drums")
        self.assertEqual(drum_clip["channel"], 3)
        self.assertEqual(drum_clip["start_seconds"], 9.25)
        self.assertEqual(drum_clip["source_in_seconds"], 1)
        self.assertEqual(drum_clip["duration_seconds"], 5)
        self.assertEqual(drum_clip["gain_db"], -2)
        self.assertEqual(drum_clip["eq_high_db"], 2.5)
        self.assertEqual(drum_clip["lowpass_hz"], 15000)
        self.assertEqual(drum_clip["compressor_ratio"], 6)
        moved = update_timeline_clip(
            self.database, drum_clip["id"], {"start_seconds": 12, "gain_db": -6}
        )
        moved_drum = next(clip for clip in moved["clips"] if clip["id"] == drum_clip["id"])
        original = next(clip for clip in moved["clips"] if clip["id"] == clip_id)
        self.assertEqual((moved_drum["start_seconds"], moved_drum["gain_db"]), (12, -6))
        self.assertEqual((original["start_seconds"], original["gain_db"]), (6, -2))

        restored = set_timeline_clip_source(self.database, clip_id, "song")
        restored_clip = next(clip for clip in restored["clips"] if clip["id"] == clip_id)
        self.assertEqual(restored_clip["clip_kind"], "song")
        self.assertEqual(restored_clip["path"], str(source))

        instrumental = update_clip_stem_state(
            self.database, clip_id, "vocals", muted=True
        )
        original = next(clip for clip in instrumental["clips"] if clip["id"] == clip_id)
        self.assertEqual(original["stem_states"]["vocals"], {"muted": 1, "solo": 0})

        acapella = update_clip_stem_state(
            self.database, clip_id, "vocals", solo=True
        )
        original = next(clip for clip in acapella["clips"] if clip["id"] == clip_id)
        self.assertEqual(original["stem_states"]["vocals"], {"muted": 0, "solo": 1})

        two_stems = update_clip_stem_state(
            self.database, clip_id, "drums", solo=True
        )
        original = next(clip for clip in two_stems["clips"] if clip["id"] == clip_id)
        self.assertEqual(original["stem_states"]["drums"]["solo"], 1)
        duplicated = duplicate_timeline_clip(self.database, clip_id)
        duplicate = next(
            clip for clip in duplicated["clips"] if clip["id"] == duplicated["selected_clip_id"]
        )
        self.assertEqual(duplicate["stem_states"], original["stem_states"])
        split = split_timeline_clip(self.database, clip_id, 2)
        split_clip = next(
            clip for clip in split["clips"]
            if clip["id"] not in {clip_id, duplicate["id"]} and clip["clip_kind"] == "song"
        )
        self.assertEqual(split_clip["stem_states"], original["stem_states"])

    def test_tempo_preserves_source_span_and_updates_timeline_mapping(self) -> None:
        source = self.create_wave("Tempo source.wav", 12)
        source_bytes = source.read_bytes()
        scan_library(self.database, self.music)
        track = list_tracks(self.database)[0]
        project = create_project(self.database, "Tempo study", 120)
        state = add_track_to_project(
            self.database, project["project"]["id"], track["id"], 1
        )
        clip_id = state["selected_clip_id"]

        faster = update_timeline_clip(
            self.database, clip_id, {"tempo_percent": 200}
        )
        clip = faster["clips"][0]
        self.assertEqual(clip["duration_seconds"], 6)
        self.assertEqual(clip["tempo_percent"], 200)

        precise = update_timeline_clip(
            self.database, clip_id, {"tempo_percent": 101.5625}
        )
        clip = precise["clips"][0]
        self.assertEqual(clip["tempo_percent"], 101.5625)
        self.assertAlmostEqual(clip["duration_seconds"] * 1.015625, 12, places=5)
        update_timeline_clip(self.database, clip_id, {"tempo_percent": 200})

        split = split_timeline_clip(self.database, clip_id, 2)
        left = next(item for item in split["clips"] if item["id"] == clip_id)
        right = next(item for item in split["clips"] if item["id"] != clip_id)
        self.assertEqual((left["source_in_seconds"], left["duration_seconds"]), (0, 2))
        self.assertEqual((right["source_in_seconds"], right["duration_seconds"]), (4, 4))
        restored = batch_update_timeline_clips(
            self.database, [left["id"], right["id"]], {"tempo_percent": 100}
        )
        self.assertEqual(
            [clip["duration_seconds"] for clip in restored["clips"]], [4, 8]
        )
        self.assertEqual(source.read_bytes(), source_bytes)

    def test_v18_migration_converts_legacy_tempo_duration_to_timeline_time(self) -> None:
        self.create_wave("Legacy tempo.wav", 12)
        scan_library(self.database, self.music)
        track = list_tracks(self.database)[0]
        project = create_project(self.database, "Legacy tempo", 120)
        state = add_track_to_project(
            self.database, project["project"]["id"], track["id"], 1
        )
        clip_id = state["selected_clip_id"]
        with closing(sqlite3.connect(self.database.path)) as connection, connection:
            connection.execute(
                "UPDATE timeline_clips SET duration_seconds = 12, tempo_percent = 200 WHERE id = ?",
                (clip_id,),
            )
            connection.execute("UPDATE schema_info SET version = 17")

        self.database.initialize()
        migrated = load_project(self.database, project["project"]["id"])

        self.assertEqual(migrated["clips"][0]["duration_seconds"], 6)
        with closing(sqlite3.connect(self.database.path)) as connection, connection:
            self.assertEqual(
                connection.execute("SELECT version FROM schema_info").fetchone()[0],
                25,
            )
        self.assertEqual(migrated["project"]["target_lufs"], -14)

    def test_project_rejects_unknown_tracks_and_invalid_ranges(self) -> None:
        project = create_project(self.database, "Safe project", 120)
        project_id = project["project"]["id"]
        with self.assertRaisesRegex(ValueError, "not found"):
            add_track_to_project(self.database, project_id, 999, 1)
        with self.assertRaisesRegex(ValueError, "between 1 and 4"):
            add_track_to_project(self.database, project_id, 999, 5)
        with self.assertRaisesRegex(ValueError, "between 40 and 240"):
            update_project(self.database, project_id, tempo=260)

    def test_split_duplicate_trim_loop_reverse_and_fades_are_non_destructive(self) -> None:
        source = self.create_wave("Editable.wav", 12)
        source_bytes = source.read_bytes()
        scan_library(self.database, self.music)
        track = list_tracks(self.database)[0]
        project = create_project(self.database, "Edit study", 120)
        project_id = project["project"]["id"]
        state = add_track_to_project(self.database, project_id, track["id"], 2)
        clip_id = state["selected_clip_id"]

        edited = update_timeline_clip(
            self.database,
            clip_id,
            {
                "source_in_seconds": 2,
                "duration_seconds": 8,
                "loop_enabled": True,
                "reversed": True,
                "fade_in_seconds": 1,
                "fade_out_seconds": 2,
                "eq_low_db": 3,
                "highpass_hz": 90,
                "compressor_enabled": True,
            },
        )
        self.assertEqual(edited["clips"][0]["loop_enabled"], 1)
        self.assertEqual(edited["clips"][0]["reversed"], 1)

        split = split_timeline_clip(self.database, clip_id, 3)
        self.assertEqual(len(split["clips"]), 2)
        left, right = split["clips"]
        self.assertEqual((left["source_in_seconds"], left["duration_seconds"]), (7, 3))
        self.assertEqual((right["source_in_seconds"], right["duration_seconds"]), (2, 5))
        self.assertEqual((left["loop_enabled"], right["loop_enabled"]), (0, 0))
        self.assertEqual((left["fade_out_seconds"], right["fade_in_seconds"]), (0, 0))
        self.assertEqual(right["fade_out_seconds"], 2)
        self.assertEqual((left["eq_low_db"], right["eq_low_db"]), (3, 3))
        self.assertEqual((left["highpass_hz"], right["highpass_hz"]), (90, 90))
        self.assertEqual((left["compressor_enabled"], right["compressor_enabled"]), (1, 1))

        duplicated = duplicate_timeline_clip(self.database, split["selected_clip_id"])
        self.assertEqual(len(duplicated["clips"]), 3)
        duplicate = next(
            clip for clip in duplicated["clips"] if clip["id"] == duplicated["selected_clip_id"]
        )
        self.assertEqual(duplicate["start_seconds"], 8)
        self.assertEqual(duplicate["source_in_seconds"], 2)
        self.assertEqual(duplicate["reversed"], 1)
        self.assertEqual(duplicate["eq_low_db"], 3)
        self.assertEqual(duplicate["compressor_enabled"], 1)
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertGreaterEqual(len(list_project_history(self.database, project_id)), 5)

        with self.assertRaisesRegex(ValueError, "source track duration"):
            update_timeline_clip(
                self.database,
                duplicate["id"],
                {"source_in_seconds": 10, "duration_seconds": 5},
            )
        with self.assertRaisesRegex(ValueError, "Combined fades"):
            update_timeline_clip(
                self.database,
                duplicate["id"],
                {"fade_in_seconds": 3, "fade_out_seconds": 3},
            )

    def test_clip_edges_resize_against_forward_and_reverse_source_boundaries(self) -> None:
        source = self.create_wave("Resize source.wav", 12)
        source_bytes = source.read_bytes()
        scan_library(self.database, self.music)
        track = list_tracks(self.database)[0]
        project = create_project(self.database, "Resize study", 120)
        project_id = project["project"]["id"]
        state = add_track_to_project(self.database, project_id, track["id"], 1, 5)
        clip_id = state["selected_clip_id"]
        update_timeline_clip(
            self.database,
            clip_id,
            {"source_in_seconds": 2, "duration_seconds": 8},
        )

        forward_left_in = resize_timeline_clip(self.database, clip_id, "start", 7)
        clip = forward_left_in["clips"][0]
        self.assertEqual(
            (clip["start_seconds"], clip["source_in_seconds"], clip["duration_seconds"]),
            (7, 4, 6),
        )
        forward_left_out = resize_timeline_clip(self.database, clip_id, "start", 4)
        clip = forward_left_out["clips"][0]
        self.assertEqual(
            (clip["start_seconds"], clip["source_in_seconds"], clip["duration_seconds"]),
            (4, 1, 9),
        )
        forward_right_in = resize_timeline_clip(self.database, clip_id, "end", 10)
        clip = forward_right_in["clips"][0]
        self.assertEqual((clip["source_in_seconds"], clip["duration_seconds"]), (1, 6))
        forward_right_out = resize_timeline_clip(self.database, clip_id, "end", 15)
        clip = forward_right_out["clips"][0]
        self.assertEqual((clip["source_in_seconds"], clip["duration_seconds"]), (1, 11))

        update_timeline_clip(
            self.database,
            clip_id,
            {
                "start_seconds": 5,
                "source_in_seconds": 2,
                "duration_seconds": 8,
                "reversed": True,
            },
        )
        reverse_left_in = resize_timeline_clip(self.database, clip_id, "start", 7)
        clip = reverse_left_in["clips"][0]
        self.assertEqual(
            (clip["start_seconds"], clip["source_in_seconds"], clip["duration_seconds"]),
            (7, 2, 6),
        )
        reverse_left_out = resize_timeline_clip(self.database, clip_id, "start", 4)
        clip = reverse_left_out["clips"][0]
        self.assertEqual(
            (clip["start_seconds"], clip["source_in_seconds"], clip["duration_seconds"]),
            (4, 2, 9),
        )
        reverse_right_in = resize_timeline_clip(self.database, clip_id, "end", 11)
        clip = reverse_right_in["clips"][0]
        self.assertEqual((clip["source_in_seconds"], clip["duration_seconds"]), (4, 7))
        reverse_right_out = resize_timeline_clip(self.database, clip_id, "end", 14)
        clip = reverse_right_out["clips"][0]
        self.assertEqual((clip["source_in_seconds"], clip["duration_seconds"]), (1, 10))

        with self.assertRaisesRegex(ValueError, "available source audio"):
            resize_timeline_clip(self.database, clip_id, "end", 16)
        update_timeline_clip(self.database, clip_id, {"locked": True})
        with self.assertRaisesRegex(ValueError, "Unlock"):
            resize_timeline_clip(self.database, clip_id, "start", 6)
        self.assertEqual(source.read_bytes(), source_bytes)

    def test_snap_quantize_crossfade_markers_and_sections_persist(self) -> None:
        first_source = self.create_wave("Outgoing.wav", 10)
        second_source = self.create_wave("Incoming.wav", 10)
        original_bytes = {
            first_source: first_source.read_bytes(),
            second_source: second_source.read_bytes(),
        }
        scan_library(self.database, self.music)
        tracks = list_tracks(self.database)
        project = create_project(self.database, "Structured mix", 120)
        project_id = project["project"]["id"]
        updated_project = update_project(
            self.database,
            project_id,
            snap_enabled=True,
            snap_beats=0.5,
        )
        self.assertEqual(updated_project["project"]["snap_enabled"], 1)
        self.assertEqual(updated_project["project"]["snap_beats"], 0.5)

        first_state = add_track_to_project(
            self.database, project_id, tracks[0]["id"], 1, 0.26
        )
        first_clip_id = first_state["selected_clip_id"]
        second_state = add_track_to_project(
            self.database, project_id, tracks[1]["id"], 2, 4.5
        )
        second_clip_id = second_state["selected_clip_id"]

        quantized = quantize_timeline_clip(self.database, first_clip_id)
        first_clip = next(clip for clip in quantized["clips"] if clip["id"] == first_clip_id)
        self.assertEqual(first_clip["start_seconds"], 0.25)

        crossfaded = crossfade_timeline_clips(self.database, first_clip_id, second_clip_id)
        outgoing = next(clip for clip in crossfaded["clips"] if clip["id"] == first_clip_id)
        incoming = next(clip for clip in crossfaded["clips"] if clip["id"] == second_clip_id)
        self.assertEqual(outgoing["fade_out_seconds"], 5.75)
        self.assertEqual(incoming["fade_in_seconds"], 5.75)

        marker_state = create_project_marker(
            self.database, project_id, "marker", "Drop", 2.5, color="rose"
        )
        marker_id = marker_state["selected_marker_id"]
        section_state = create_project_marker(
            self.database, project_id, "section", "Breakdown", 4, 8, "cyan"
        )
        section_id = section_state["selected_marker_id"]
        renamed = update_project_marker(
            self.database, marker_id, {"name": "First drop", "start_seconds": 2.75}
        )
        self.assertEqual(len(renamed["markers"]), 2)
        self.assertEqual(
            next(marker for marker in renamed["markers"] if marker["id"] == marker_id)["name"],
            "First drop",
        )
        remaining = delete_project_marker(self.database, section_id)
        self.assertEqual([marker["id"] for marker in remaining["markers"]], [marker_id])
        self.assertGreaterEqual(len(list_project_history(self.database, project_id)), 9)
        for source, data in original_bytes.items():
            self.assertEqual(source.read_bytes(), data)

        with self.assertRaisesRegex(ValueError, "Marker name"):
            create_project_marker(self.database, project_id, "marker", " ", 1)

    def test_selection_loop_undo_and_redo_restore_complete_project(self) -> None:
        source = self.create_wave("Undo source.wav", 12)
        source_bytes = source.read_bytes()
        scan_library(self.database, self.music)
        track = list_tracks(self.database)[0]
        project = create_project(self.database, "Undo study", 120)
        project_id = project["project"]["id"]
        state = add_track_to_project(self.database, project_id, track["id"], 1, 0)
        clip_id = state["selected_clip_id"]

        selected = update_project_selection(self.database, project_id, 2, 6, True)
        self.assertEqual(selected["project"]["selection_start_seconds"], 2)
        self.assertEqual(selected["project"]["selection_end_seconds"], 6)
        self.assertEqual(selected["project"]["selection_loop_enabled"], 1)
        moved = update_timeline_clip(self.database, clip_id, {"start_seconds": 3})
        self.assertTrue(moved["can_undo"])
        self.assertFalse(moved["can_redo"])

        undone_move = undo_project(self.database, project_id)
        self.assertEqual(undone_move["clips"][0]["start_seconds"], 0)
        self.assertTrue(undone_move["can_redo"])
        redone_move = redo_project(self.database, project_id)
        self.assertEqual(redone_move["clips"][0]["start_seconds"], 3)

        undo_project(self.database, project_id)
        undone_selection = undo_project(self.database, project_id)
        self.assertIsNone(undone_selection["project"]["selection_start_seconds"])
        self.assertEqual(undone_selection["project"]["selection_loop_enabled"], 0)
        restored_selection = redo_project(self.database, project_id)
        self.assertEqual(restored_selection["project"]["selection_end_seconds"], 6)
        self.assertEqual(source.read_bytes(), source_bytes)

        update_project_selection(self.database, project_id, None, None, False)
        with self.assertRaisesRegex(ValueError, "nothing to redo"):
            redo_project(self.database, project_id)
        with self.assertRaisesRegex(ValueError, "set together"):
            update_project_selection(self.database, project_id, 1, None, True)

    def test_clip_groups_move_together_and_master_settings_persist(self) -> None:
        sources = [self.create_wave(f"Group {index}.wav", 8) for index in range(2)]
        original = {path: path.read_bytes() for path in sources}
        scan_library(self.database, self.music)
        tracks = list_tracks(self.database)
        project = create_project(self.database, "Grouped mix", 120)
        project_id = project["project"]["id"]
        first = add_track_to_project(self.database, project_id, tracks[0]["id"], 1, 2)
        first_id = first["selected_clip_id"]
        second = add_track_to_project(self.database, project_id, tracks[1]["id"], 2, 5)
        second_id = second["selected_clip_id"]
        grouped = group_timeline_clips(self.database, [first_id, second_id])
        group_id = grouped["clips"][0]["group_id"]
        self.assertIsNotNone(group_id)
        moved = update_timeline_clip(self.database, first_id, {"start_seconds": 7})
        self.assertEqual([clip["start_seconds"] for clip in moved["clips"]], [7, 10])
        shifted = shift_timeline_group_channels(self.database, project_id, group_id, 1)
        self.assertEqual([clip["channel"] for clip in shifted["clips"]], [2, 3])
        batched = batch_update_timeline_clips(
            self.database, [first_id, second_id], {"gain_db": -4, "color": "blue", "muted": True}
        )
        self.assertTrue(all(clip["gain_db"] == -4 for clip in batched["clips"]))
        self.assertTrue(all(clip["color"] == "blue" for clip in batched["clips"]))
        self.assertTrue(all(clip["muted"] == 1 for clip in batched["clips"]))
        processed = update_timeline_clip(
            self.database,
            first_id,
            {
                "eq_low_db": 2.5,
                "eq_mid_db": -1.5,
                "eq_high_db": 1,
                "highpass_hz": 80,
                "lowpass_hz": 16000,
                "compressor_enabled": True,
                "compressor_threshold_db": -20,
                "compressor_ratio": 5,
            },
        )
        processed_clip = next(clip for clip in processed["clips"] if clip["id"] == first_id)
        self.assertEqual(processed_clip["eq_low_db"], 2.5)
        self.assertEqual(processed_clip["highpass_hz"], 80)
        self.assertEqual(processed_clip["compressor_enabled"], 1)
        with self.assertRaisesRegex(ValueError, "High-pass"):
            update_timeline_clip(
                self.database, first_id, {"highpass_hz": 17000, "lowpass_hz": 16000}
            )
        mastered = update_project(
            self.database, project_id, master_gain_db=-3.5, master_limiter_enabled=False,
            musical_key="8a", master_low_eq_db=1.5, master_mid_eq_db=-1,
            master_high_eq_db=2, master_stereo_width=1.35, target_lufs=-9,
        )
        self.assertEqual(mastered["project"]["master_gain_db"], -3.5)
        self.assertEqual(mastered["project"]["master_limiter_enabled"], 0)
        self.assertEqual(mastered["project"]["musical_key"], "8A")
        self.assertEqual(mastered["project"]["master_low_eq_db"], 1.5)
        self.assertEqual(mastered["project"]["master_mid_eq_db"], -1)
        self.assertEqual(mastered["project"]["master_high_eq_db"], 2)
        self.assertEqual(mastered["project"]["master_stereo_width"], 1.35)
        self.assertEqual(mastered["project"]["target_lufs"], -9)
        ungrouped = ungroup_timeline_clips(self.database, project_id, group_id)
        self.assertTrue(all(clip["group_id"] is None for clip in ungrouped["clips"]))
        trimmed = trim_timeline_clips_to_selection(self.database, [first_id, second_id], 8, 15)
        self.assertEqual([clip["start_seconds"] for clip in trimmed["clips"]], [8, 10])
        self.assertEqual([clip["duration_seconds"] for clip in trimmed["clips"]], [7, 5])
        deleted = delete_timeline_clips(self.database, [first_id, second_id])
        self.assertEqual(deleted["clips"], [])
        restored = undo_project(self.database, project_id)
        self.assertEqual(len(restored["clips"]), 2)
        for path, data in original.items():
            self.assertEqual(path.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
