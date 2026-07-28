from __future__ import annotations

import json
import base64
import struct
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

from mutagen.id3 import GEOB, ID3

from decksmith.database import Database
from decksmith.scanner import scan_library
from decksmith.transfer import (
    capture_transfer_snapshot,
    create_rekordbox_package,
    latest_transfer_plan,
    list_transfer_exports,
    validate_rekordbox_xml,
    verify_transfer_package,
)


def record(tag: str, value: bytes) -> bytes:
    return tag.encode("ascii") + struct.pack(">I", len(value)) + value


def text_record(tag: str, value: str) -> bytes:
    return record(tag, value.encode("utf-16-be"))


def marker_record(tag: str, payload: bytes) -> bytes:
    return tag.encode("ascii") + b"\0" + struct.pack(">I", len(payload)) + payload


def cue_payload(slot: int, position_ms: int, name: str) -> bytes:
    return b"\0" + bytes([slot]) + struct.pack(">I", position_ms) + b"\0\xcc\0\xcc" + b"\0\0" + name.encode() + b"\0"


def loop_payload(slot: int, start_ms: int, end_ms: int) -> bytes:
    return (
        b"\0" + bytes([slot]) + struct.pack(">II", start_ms, end_ms)
        + b"\xff\xff\xff\xff\0\x33\xff\x33\0\0\0"
    )


def markers2_data(*records: bytes) -> bytes:
    return b"\x01\x01" + base64.b64encode(b"\x01\x01" + b"".join(records) + b"\0") + b"\0" * 8


class TransferTests(unittest.TestCase):
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

    def create_wave(self, name: str) -> Path:
        path = self.music / name
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(44_100)
            audio.writeframes(b"\0\0" * 4_410)
        return path

    def create_tagged_mp3(self, name: str, *records: bytes) -> Path:
        path = self.music / name
        tags = ID3()
        tags.add(GEOB(encoding=3, mime="application/octet-stream", filename="", desc="Serato Markers2", data=markers2_data(*records)))
        tags.save(path)
        return path

    def create_crate(self, name: str, tracks: list[str]) -> Path:
        payload = text_record("vrsn", "1.0/Serato ScratchLive Crate")
        for track in tracks:
            payload += record("otrk", text_record("ptrk", track))
        path = self.serato / "Subcrates" / f"{name}.crate"
        path.write_bytes(payload)
        return path

    def test_snapshot_requires_a_discovered_serato_library(self) -> None:
        with self.assertRaisesRegex(ValueError, "No Serato library"):
            capture_transfer_snapshot(self.database, [])

    def test_snapshots_detect_added_reordered_and_removed_crates(self) -> None:
        first = self.create_wave("First.wav")
        second = self.create_wave("Second.wav")
        crate = self.create_crate("Wedding%%Dinner", [first.name, second.name])
        scan_library(self.database, self.music)

        initial = capture_transfer_snapshot(self.database, [self.serato])
        self.assertEqual(initial["summary"], {"added": 1, "modified": 0, "unchanged": 0, "removed": 0})
        self.assertEqual(initial["changes"][0]["matched_count"], 2)

        self.create_crate("Wedding%%Dinner", [second.name, first.name])
        reordered = capture_transfer_snapshot(self.database, [self.serato])
        self.assertEqual(reordered["summary"]["modified"], 1)
        self.assertTrue(reordered["changes"][0]["reordered"])
        self.assertEqual(reordered["changes"][0]["added_tracks"], 0)
        self.assertEqual(reordered["changes"][0]["removed_tracks"], 0)

        crate.unlink()
        removed = capture_transfer_snapshot(self.database, [self.serato])
        self.assertEqual(removed["summary"]["removed"], 1)
        self.assertEqual(removed["changes"][0]["crate_id"], None)

    def test_rekordbox_package_preserves_hierarchy_order_and_safe_metadata(self) -> None:
        first = self.create_wave("First song.wav")
        second = self.create_wave("Second.wav")
        crate_file = self.create_crate("Wedding%%Dinner", [second.name, first.name])
        crate_bytes = crate_file.read_bytes()
        first_bytes = first.read_bytes()
        scan_library(self.database, self.music)
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE tracks SET rating = 5, color_tag = 'violet', user_comment = 'Decksmith note',
                                  analysis_bpm = 120.5, analysis_key = '8A'
                WHERE path = ?
                """,
                (str(first),),
            )

        snapshot = capture_transfer_snapshot(self.database, [self.serato])
        crate_id = snapshot["changes"][0]["crate_id"]
        result = create_rekordbox_package(self.database, self.root / "Exports", [crate_id])

        package = Path(result["destination_path"])
        xml_path = Path(result["xml_path"])
        report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
        manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        xml_root = ET.parse(xml_path).getroot()
        collection = xml_root.find("COLLECTION")
        playlist_root = xml_root.find("PLAYLISTS/NODE")
        folder = playlist_root.find("NODE") if playlist_root is not None else None
        playlist = folder.find("NODE") if folder is not None else None

        self.assertTrue(package.is_dir())
        self.assertEqual(xml_root.tag, "DJ_PLAYLISTS")
        self.assertEqual(xml_root.attrib["Version"], "1.0.0")
        self.assertEqual(collection.attrib["Entries"], "2")
        self.assertEqual(folder.attrib["Name"], "Wedding")
        self.assertEqual(playlist.attrib["Name"], "Dinner")
        self.assertEqual([track.attrib["Key"] for track in playlist.findall("TRACK")], ["1", "2"])
        exported_tracks = collection.findall("TRACK")
        self.assertTrue(exported_tracks[1].attrib["Location"].startswith("file://"))
        self.assertEqual(exported_tracks[1].attrib["Rating"], "255")
        self.assertEqual(exported_tracks[1].attrib["Comments"], "Decksmith note")
        self.assertEqual(exported_tracks[1].attrib["AverageBpm"], "120.5")
        self.assertEqual(exported_tracks[1].attrib["Tonality"], "8A")
        self.assertFalse(report["source_safety"]["serato_database_modified"])
        self.assertFalse(report["source_safety"]["audio_files_modified"])
        self.assertEqual(report["xml_validation"]["status"], "passed")
        self.assertEqual(manifest["validation_status"], "passed")
        self.assertIn("decksmith-rekordbox.xml", manifest["files"])
        self.assertEqual(crate_file.read_bytes(), crate_bytes)
        self.assertEqual(first.read_bytes(), first_bytes)
        self.assertEqual(len(list_transfer_exports(self.database)), 1)
        self.assertEqual(latest_transfer_plan(self.database)["snapshot_id"], snapshot["snapshot_id"])

    def test_rekordbox_package_exports_validated_cues_without_writing_id3(self) -> None:
        track = self.create_tagged_mp3(
            "Cue track.mp3",
            marker_record("CUE", cue_payload(1, 12_500, "Intro")),
            marker_record("CUE", cue_payload(5, 64_250, "Energy")),
        )
        original = track.read_bytes()
        self.create_crate("Prepared", [track.name])
        scan_library(self.database, self.music)

        snapshot = capture_transfer_snapshot(self.database, [self.serato])
        result = create_rekordbox_package(
            self.database, self.root / "Exports", [snapshot["changes"][0]["crate_id"]]
        )
        root = ET.parse(result["xml_path"]).getroot()
        marks = root.findall("COLLECTION/TRACK/POSITION_MARK")
        validation = validate_rekordbox_xml(Path(result["xml_path"]).read_bytes())
        package_validation = verify_transfer_package(self.database, result["destination_path"])

        self.assertEqual(result["cue_count"], 2)
        self.assertEqual(validation["cue_points"], 2)
        self.assertEqual(package_validation["status"], "passed")
        self.assertEqual(marks[0].attrib, {"Name": "Intro", "Type": "0", "Start": "12.500", "Num": "1"})
        self.assertEqual(marks[1].attrib, {"Name": "Energy", "Type": "0", "Start": "64.250", "Num": "-1"})
        self.assertTrue(any(warning["code"] == "hot_cue_slot_downgraded" for warning in result["warnings"]))
        self.assertEqual(track.read_bytes(), original)
        readme = Path(result["destination_path"]) / "README.txt"
        readme.write_text(readme.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity check failed"):
            verify_transfer_package(self.database, result["destination_path"])

    def test_unindexed_serato_track_exports_file_metadata_and_cues_directly(self) -> None:
        track = self.create_tagged_mp3(
            "Unindexed cue.mp3",
            marker_record("CUE", cue_payload(0, 3_250, "Start")),
            marker_record("LOOP", loop_payload(0, 5_000, 9_000)),
        )
        original = track.read_bytes()
        self.create_crate("Direct read", [track.name])

        snapshot = capture_transfer_snapshot(self.database, [self.serato])
        change = snapshot["changes"][0]
        result = create_rekordbox_package(
            self.database, self.root / "Exports", [change["crate_id"]]
        )
        root = ET.parse(result["xml_path"]).getroot()
        exported = root.find("COLLECTION/TRACK")
        markers = exported.findall("POSITION_MARK")

        self.assertEqual(change["matched_count"], 0)
        self.assertEqual(result["cue_count"], 1)
        self.assertEqual(result["loop_count"], 1)
        self.assertEqual(exported.attrib["Name"], "Unindexed cue")
        self.assertTrue(exported.attrib["Location"].startswith("file://localhost/"))
        self.assertEqual(markers[0].attrib["Start"], "3.250")
        self.assertEqual(markers[1].attrib, {
            "Name": "Serato Saved Loop 1",
            "Type": "4",
            "Start": "5.000",
            "End": "9.000",
            "Num": "-1",
        })
        self.assertFalse(any(warning["code"] == "minimal_metadata" for warning in result["warnings"]))
        self.assertEqual(track.read_bytes(), original)

    def test_rekordbox_validator_rejects_unknown_playlist_keys(self) -> None:
        xml = b'''<?xml version="1.0" encoding="UTF-8"?>
        <DJ_PLAYLISTS Version="1.0.0"><PRODUCT Name="Decksmith" Version="0.1.0" Company="CueRated Concepts"/>
        <COLLECTION Entries="1"><TRACK TrackID="1" Name="Track" Location="file://localhost/Music/Track.mp3"/></COLLECTION>
        <PLAYLISTS><NODE Name="ROOT" Type="0" Count="1"><NODE Name="Set" Type="1" Entries="1" KeyType="0"><TRACK Key="99"/></NODE></NODE></PLAYLISTS></DJ_PLAYLISTS>'''

        with self.assertRaisesRegex(ValueError, "unknown track"):
            validate_rekordbox_xml(xml)


if __name__ == "__main__":
    unittest.main()
