from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .database import Database


def generate_waveform(database: Database, track_id: int, cache_dir: str | Path) -> Path:
    database.initialize()
    with database.connect() as connection:
        row = connection.execute(
            "SELECT path, modified_ns, missing FROM tracks WHERE id = ?", (track_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"Track {track_id} does not exist")
    if row["missing"]:
        raise FileNotFoundError(row["path"])
    source = Path(row["path"])
    if not source.is_file():
        raise FileNotFoundError(source)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not installed")

    destination_dir = Path(cache_dir).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{track_id}-{row['modified_ns']}-precision-v3.png"
    if destination.is_file():
        return destination
    for stale in destination_dir.glob(f"{track_id}-*.png"):
        stale.unlink(missing_ok=True)

    process = subprocess.run(
        [
            ffmpeg, "-v", "error", "-y", "-i", str(source),
            "-filter_complex", "aformat=channel_layouts=mono,showwavespic=s=16384x256:colors=#9a7cff",
            "-frames:v", "1", str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "FFmpeg could not generate a waveform")
    return destination
