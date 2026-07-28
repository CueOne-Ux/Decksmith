from __future__ import annotations

import tempfile
import unittest
import wave
import math
import struct
from pathlib import Path

from decksmith.database import Database
from decksmith.library import list_tracks
from decksmith.mixdown import (
    audit_project_mixdown,
    build_mixdown_command,
    build_smart_render_issues,
    export_project_mixdown,
    list_project_exports,
    load_latest_project_audit,
    parse_loudnorm_measurement,
    parse_silence_intervals,
)
from decksmith.projects import (
    add_track_to_project,
    create_project,
    load_project,
    update_project,
    update_timeline_clip,
)
from decksmith.rendering import _ffmpeg_runtime, render_clip, render_status
from decksmith.scanner import scan_library


class MixdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.music = self.root / "Music"
        self.cache = self.root / "Renders"
        self.music.mkdir()
        self.database = Database(self.root / "decksmith.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_wave(self, name: str, seconds: float = 1.0) -> Path:
        path = self.music / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(44_100)
            audio.writeframes(b"\0\0\0\0" * round(44_100 * seconds))
        return path

    @staticmethod
    def fake_renderer(clip, source, output, executable, should_cancel) -> None:
        frame_count = round(44_100 * clip["duration_seconds"])
        frames = bytearray()
        for index in range(frame_count):
            sample = round(math.sin(2 * math.pi * 440 * index / 44_100) * 3200)
            frames.extend(struct.pack("<hh", sample, sample))
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(2)
            audio.setsampwidth(2)
            audio.setframerate(44_100)
            audio.writeframes(frames)

    def prepared_project(self) -> tuple[int, list[int]]:
        self.create_wave("First.wav")
        self.create_wave("Second.wav")
        scan_library(self.database, self.music)
        tracks = list_tracks(self.database)
        project = create_project(self.database, "Mixdown", 120)
        project_id = project["project"]["id"]
        first = add_track_to_project(self.database, project_id, tracks[0]["id"], 1, 0)
        second = add_track_to_project(self.database, project_id, tracks[1]["id"], 2, 0.5)
        first_id = first["selected_clip_id"]
        second_id = second["selected_clip_id"]
        update_timeline_clip(
            self.database,
            first_id,
            {
                "gain_db": -3,
                "pan": -0.5,
                "fade_out_seconds": 0.2,
                "eq_low_db": 2,
                "eq_mid_db": -1,
                "eq_high_db": 1.5,
                "highpass_hz": 80,
                "lowpass_hz": 16000,
                "compressor_enabled": True,
                "compressor_threshold_db": -20,
                "compressor_ratio": 5,
            },
        )
        update_timeline_clip(
            self.database,
            second_id,
            {"gain_db": -6, "pan": 0.5, "fade_in_seconds": 0.2},
        )
        update_project(
            self.database,
            project_id,
            master_low_eq_db=1,
            master_mid_eq_db=-0.5,
            master_high_eq_db=1.5,
            master_stereo_width=1.25,
        )
        for clip_id in (first_id, second_id):
            render_clip(
                self.database, clip_id, self.cache, renderer=self.fake_renderer
            )
        return project_id, [first_id, second_id]

    def test_mixdown_command_uses_timeline_and_mix_controls(self) -> None:
        project_id, clip_ids = self.prepared_project()
        payload = load_project(self.database, project_id)
        status = render_status(self.database, clip_ids)
        paths = {int(item["clip_id"]): item["path"] for item in status["renders"]}
        command = build_mixdown_command(
            "ffmpeg", payload, paths, self.root / "Mix.wav", "wav"
        )
        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("volume=-3.0000dB", filter_graph)
        self.assertIn("pan=stereo", filter_graph)
        self.assertIn("afade=t=out", filter_graph)
        self.assertIn("adelay=delays=500:all=1", filter_graph)
        self.assertIn("amix=inputs=2", filter_graph)
        self.assertIn("bass=g=2.0000", filter_graph)
        self.assertIn("equalizer=f=1000", filter_graph)
        self.assertIn("treble=g=1.5000", filter_graph)
        self.assertIn("highpass=f=80.000", filter_graph)
        self.assertIn("lowpass=f=16000.000", filter_graph)
        self.assertIn("acompressor=threshold=-20.000dB", filter_graph)
        self.assertIn("stereotools=mlev=1:slev=1.2500", filter_graph)
        self.assertIn("alimiter", filter_graph)
        self.assertIn("pcm_s24le", command)

    def test_loudness_and_silence_parsers_are_stable(self) -> None:
        loudness = parse_loudnorm_measurement(
            'summary\n{\n"input_i" : "-12.34",\n"input_tp" : "-0.81",\n'
            '"input_lra" : "5.20",\n"input_thresh" : "-22.10",\n'
            '"target_offset" : "-0.12"\n}\n'
        )
        self.assertEqual(loudness["integrated_lufs"], -12.34)
        self.assertEqual(loudness["true_peak_dbfs"], -0.81)
        self.assertEqual(loudness["normalization_offset_db"], -0.12)
        silences = parse_silence_intervals(
            "silence_start: 0\nsilence_end: 1.25 | silence_duration: 1.25\n"
            "silence_start: 4.5\n",
            6,
        )
        self.assertEqual(silences, [
            {"start_seconds": 0.0, "end_seconds": 1.25, "duration_seconds": 1.25},
            {"start_seconds": 4.5, "end_seconds": 6, "duration_seconds": 1.5},
        ])

    def test_smart_render_flags_signal_and_timeline_risks(self) -> None:
        project_id, clip_ids = self.prepared_project()
        payload = load_project(self.database, project_id)
        payload["project"]["target_lufs"] = -14
        payload["clips"][0]["clip_kind"] = "vocals"
        payload["clips"][1]["clip_kind"] = "vocals"
        payload["clips"][0]["duration_seconds"] = 6
        payload["clips"][1]["duration_seconds"] = 6
        issues = build_smart_render_issues(
            payload,
            {"integrated_lufs": -20, "true_peak_dbfs": 0.4},
            [{"start_seconds": 8, "end_seconds": 10, "duration_seconds": 2}],
        )
        codes = {issue["code"] for issue in issues}
        self.assertTrue({"clipping", "loudness_target", "silence", "vocal_collision"} <= codes)

    @unittest.skipUnless(_ffmpeg_runtime() is not None, "FFmpeg is not installed")
    def test_real_wav_mixdown_is_atomic_and_has_project_duration(self) -> None:
        project_id, clip_ids = self.prepared_project()
        destination = self.root / "Finished mix.wav"
        result = export_project_mixdown(
            self.database, project_id, destination, "wav"
        )
        self.assertEqual(result["path"], str(destination))
        self.assertEqual(result["clip_count"], 2)
        self.assertTrue(destination.is_file())
        self.assertEqual(list(self.root.glob(".*.decksmith-*.wav")), [])
        with wave.open(str(destination), "rb") as audio:
            self.assertEqual(audio.getnchannels(), 2)
            self.assertEqual(audio.getframerate(), 44_100)
            self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 1.5, places=2)
        mp3 = self.root / "Finished mix.mp3"
        mp3_result = export_project_mixdown(
            self.database, project_id, mp3, "mp3"
        )
        self.assertEqual(mp3_result["format"], "mp3")
        self.assertTrue(mp3.is_file())
        self.assertGreater(mp3.stat().st_size, 1000)

        audit = audit_project_mixdown(self.database, project_id)
        self.assertEqual(audit["project_id"], project_id)
        self.assertEqual(audit["clip_count"], 2)
        self.assertEqual(audit["metrics"]["target_lufs"], -14)
        self.assertIsNotNone(audit["metrics"]["integrated_lufs"])
        self.assertIsNotNone(audit["metrics"]["true_peak_dbfs"])
        saved_audit = load_latest_project_audit(self.database, project_id)
        self.assertTrue(saved_audit["fresh"])
        self.assertEqual(saved_audit["audit_id"], audit["audit_id"])

        targeted = self.root / "Targeted mix.wav"
        targeted_result = export_project_mixdown(
            self.database, project_id, targeted, "wav", loudness_targeted=True
        )
        self.assertEqual(targeted_result["export_mode"], "loudness_targeted")
        self.assertAlmostEqual(targeted_result["integrated_lufs"], -14, delta=0.5)
        self.assertLessEqual(targeted_result["true_peak_dbfs"], -0.8)
        history = list_project_exports(self.database, project_id)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["export_mode"], "loudness_targeted")
        self.assertTrue(all(item["exists"] for item in history))

        update_timeline_clip(self.database, clip_ids[0], {"gain_db": -9})
        self.assertFalse(load_latest_project_audit(self.database, project_id)["fresh"])


if __name__ == "__main__":
    unittest.main()
