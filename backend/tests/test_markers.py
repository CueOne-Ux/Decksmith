from __future__ import annotations

import base64
import struct
import tempfile
import unittest
from pathlib import Path

from mutagen.id3 import GEOB, ID3

from decksmith.database import Database
from decksmith.markers import (
    cue_points_for_paths,
    decode_markers2,
    marker_coverage,
    saved_loops_for_paths,
    scan_track_markers,
)


def marker_record(tag: str, payload: bytes) -> bytes:
    return tag.encode("ascii") + b"\0" + struct.pack(">I", len(payload)) + payload


def cue_payload(slot: int, position_ms: int, name: str, color: bytes = b"\x00\xcc\x00\xcc") -> bytes:
    return b"\0" + bytes([slot]) + struct.pack(">I", position_ms) + color + b"\0\0" + name.encode("utf-8") + b"\0"


def loop_payload(slot: int, start_ms: int, end_ms: int, color: bytes = b"\x00\x33\xff\x33") -> bytes:
    return (
        b"\0" + bytes([slot]) + struct.pack(">II", start_ms, end_ms)
        + b"\xff\xff\xff\xff" + color + b"\0\0\0"
    )


def markers2_data(*records: bytes) -> bytes:
    decoded = b"\x01\x01" + b"".join(records) + b"\0"
    return b"\x01\x01" + base64.b64encode(decoded) + b"\0" * 8


class MarkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.database = Database(self.root / "decksmith.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_tagged_track(self, data: bytes, name: str = "Markers.mp3") -> tuple[int, Path]:
        path = self.root / name
        tags = ID3()
        tags.add(GEOB(encoding=3, mime="application/octet-stream", filename="", desc="Serato Markers2", data=data))
        tags.save(path)
        modified_ns = path.stat().st_mtime_ns
        self.database.initialize()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tracks(
                    path, filename, extension, file_size, modified_ns, title, metadata_status
                ) VALUES (?, ?, '.mp3', ?, ?, 'Markers', 'complete')
                """,
                (str(path), path.name, path.stat().st_size, modified_ns),
            )
            return int(cursor.lastrowid), path

    def test_markers2_decoder_reads_named_cues_and_reports_loop_records(self) -> None:
        data = markers2_data(
            marker_record("COLOR", b"\0\xff\xff\xff"),
            marker_record("CUE", cue_payload(5, 112_978, "Energy 4")),
            marker_record("LOOP", loop_payload(1, 112_978, 116_978)),
            marker_record("BPMLOCK", b"\0"),
        )

        result = decode_markers2(data)

        self.assertEqual(len(result.cues), 1)
        self.assertEqual(result.cues[0].slot, 5)
        self.assertEqual(result.cues[0].position_seconds, 112.978)
        self.assertEqual(result.cues[0].name, "Energy 4")
        self.assertEqual(result.cues[0].color, "#cc00cc")
        self.assertEqual(result.loop_record_count, 1)
        self.assertEqual(result.loops[0].slot, 1)
        self.assertEqual(result.loops[0].start_seconds, 112.978)
        self.assertEqual(result.loops[0].end_seconds, 116.978)
        self.assertEqual(result.loops[0].color, "#33ff33")

    def test_markers2_decoder_accepts_serato_base64_line_wrapping(self) -> None:
        data = markers2_data(marker_record("CUE", cue_payload(1, 2_500, "Start")))
        encoded = data[2:].split(b"\0", 1)[0]
        wrapped = b"\x01\x01" + encoded[:24] + b"\n" + encoded[24:] + b"\0"

        result = decode_markers2(wrapped)

        self.assertEqual(result.cues[0].position_seconds, 2.5)

    def test_markers2_decoder_rejects_truncated_records(self) -> None:
        decoded = b"\x01\x01CUE\0" + struct.pack(">I", 50) + b"short"
        data = b"\x01\x01" + base64.b64encode(decoded)

        with self.assertRaisesRegex(ValueError, "Truncated"):
            decode_markers2(data)

    def test_marker_scan_is_cached_and_persists_cues(self) -> None:
        track_id, path = self.create_tagged_track(
            markers2_data(
                marker_record("CUE", cue_payload(2, 64_250, "Drop", b"\0\xcc\0\0")),
                marker_record("LOOP", loop_payload(0, 64_250, 72_250)),
            )
        )

        first = scan_track_markers(self.database, [track_id])
        second = scan_track_markers(self.database, [track_id])
        cues = cue_points_for_paths(self.database, [str(path)])
        loops = saved_loops_for_paths(self.database, [str(path)])
        coverage = marker_coverage(self.database, [str(path)])

        self.assertEqual(first["scanned"], 1)
        self.assertEqual(first["cues"], 1)
        self.assertEqual(first["loop_records"], 1)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(cues[str(path)][0]["name"], "Drop")
        self.assertEqual(cues[str(path)][0]["slot"], 2)
        self.assertEqual(loops[str(path)][0]["start_seconds"], 64.25)
        self.assertEqual(loops[str(path)][0]["end_seconds"], 72.25)
        self.assertEqual(coverage["cue_tracks"], 1)
        self.assertEqual(coverage["cue_points"], 1)
        self.assertEqual(coverage["marker_failures"], 0)

    def test_marker_scan_isolates_invalid_payloads_per_track(self) -> None:
        good_id, good_path = self.create_tagged_track(
            markers2_data(marker_record("CUE", cue_payload(0, 1_000, "Start"))), "Good.mp3"
        )
        bad_id, _ = self.create_tagged_track(b"\x01\x01not-base64\0", "Bad.mp3")

        result = scan_track_markers(self.database, [good_id, bad_id])
        cues = cue_points_for_paths(self.database, [str(good_path)])

        self.assertEqual(result["scanned"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["cues"], 1)
        self.assertEqual(cues[str(good_path)][0]["position_seconds"], 1.0)


if __name__ == "__main__":
    unittest.main()
