from __future__ import annotations

import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .database import Database


CAMLOT_MINOR = {
    "Ab": "1A", "G#": "1A", "Eb": "2A", "D#": "2A", "Bb": "3A", "A#": "3A",
    "F": "4A", "C": "5A", "G": "6A", "D": "7A", "A": "8A", "E": "9A",
    "B": "10A", "F#": "11A", "Gb": "11A", "C#": "12A", "Db": "12A",
}
CAMLOT_MAJOR = {
    "B": "1B", "F#": "2B", "Gb": "2B", "C#": "3B", "Db": "3B",
    "Ab": "4B", "G#": "4B", "Eb": "5B", "D#": "5B", "Bb": "6B", "A#": "6B",
    "F": "7B", "C": "8B", "G": "9B", "D": "10B", "A": "11B", "E": "12B",
}


@dataclass
class AnalysisProgress:
    total: int = 0
    processed: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: bool = False
    current_file: str = ""


AnalysisResult = dict[str, float | str]
Analyzer = Callable[[Path], AnalysisResult]
ProgressCallback = Callable[[AnalysisProgress], None]
CancellationCallback = Callable[[], bool]


def camelot_key(key: str, scale: str) -> str:
    table = CAMLOT_MINOR if scale.casefold() == "minor" else CAMLOT_MAJOR
    return table.get(key, f"{key} {scale}".strip())


def _ffmpeg_executable() -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("DECKSMITH_FFMPEG", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    discovered = shutil.which("ffmpeg")
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend((Path("/opt/homebrew/bin/ffmpeg"), Path("/usr/local/bin/ffmpeg")))
    for candidate in candidates:
        absolute = Path(os.path.abspath(candidate))
        if absolute.is_file() and os.access(absolute, os.X_OK):
            return absolute
    raise RuntimeError("FFmpeg is not installed, so Decksmith cannot decode audio for analysis.")


def _decode_mono(path: Path, sample_rate: int = 22_050) -> Any:
    """Decode at most twelve minutes without opening an audio output device."""
    command = [
        str(_ffmpeg_executable()), "-v", "error", "-nostdin", "-i", str(path),
        "-map", "0:a:0", "-t", "720", "-ac", "1", "-ar", str(sample_rate),
        "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"FFmpeg could not decode {path.name}: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"FFmpeg could not decode {path.name}.")

    import numpy as np

    return np.frombuffer(result.stdout, dtype="<f4").astype(np.float32, copy=True)


def _spectral_descriptors(audio: Any, sample_rate: int = 22_050) -> tuple[Any, Any]:
    """Return a spectral-flux onset envelope and a twelve-bin chromagram."""
    import numpy as np

    window_size = 2_048
    hop_size = 512
    if audio.size < window_size:
        audio = np.pad(audio, (0, window_size - audio.size))
    starts = np.arange(0, audio.size - window_size + 1, hop_size, dtype=np.int64)
    window = np.hanning(window_size).astype(np.float32)
    offsets = np.arange(window_size, dtype=np.int64)
    frequencies = np.fft.rfftfreq(window_size, 1.0 / sample_rate)
    tonal_bins = np.flatnonzero((frequencies >= 55.0) & (frequencies <= 5_000.0))
    midi = np.rint(69.0 + 12.0 * np.log2(frequencies[tonal_bins] / 440.0)).astype(int)
    pitch_classes = np.mod(midi, 12)

    onset_parts: list[Any] = []
    chroma = np.zeros(12, dtype=np.float64)
    previous = np.zeros(window_size // 2 + 1, dtype=np.float32)
    for offset in range(0, starts.size, 256):
        block_starts = starts[offset:offset + 256]
        frames = audio[block_starts[:, None] + offsets[None, :]] * window
        magnitude = np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)
        compressed = np.log1p(magnitude)
        preceding = np.vstack((previous[None, :], compressed[:-1]))
        onset_parts.append(np.maximum(compressed - preceding, 0.0).sum(axis=1))
        previous = compressed[-1]

        tonal = np.sqrt(magnitude[:, tonal_bins], dtype=np.float32)
        tonal /= np.maximum(tonal.sum(axis=1, keepdims=True), 1e-12)
        chroma += np.bincount(
            np.tile(pitch_classes, tonal.shape[0]),
            weights=tonal.reshape(-1),
            minlength=12,
        )

    onset = np.concatenate(onset_parts).astype(np.float64)
    onset = np.convolve(onset, np.array((0.25, 0.5, 0.25)), mode="same")
    onset = np.maximum(onset - np.median(onset), 0.0)
    return onset, chroma


def _estimate_tempo(onset: Any, sample_rate: int = 22_050, hop_size: int = 512) -> tuple[float, float]:
    import numpy as np

    if onset.size < 32 or not np.any(onset > 0):
        raise ValueError("Audio has too little rhythmic information for BPM analysis")
    centred = onset - onset.mean()
    fft_size = 1 << (2 * onset.size - 1).bit_length()
    spectrum = np.fft.rfft(centred, fft_size)
    autocorrelation = np.fft.irfft(spectrum * np.conj(spectrum), fft_size)[:onset.size]
    autocorrelation /= np.maximum(np.arange(onset.size, 0, -1), 1)
    frame_rate = sample_rate / hop_size
    minimum_lag = max(1, int(math.floor(frame_rate * 60.0 / 210.0)))
    maximum_lag = min(onset.size - 1, int(math.ceil(frame_rate * 60.0 / 55.0)))
    lags = np.arange(minimum_lag, maximum_lag + 1)
    scores = autocorrelation[lags].copy()
    for multiple, weight in ((2, 0.5), (3, 0.25), (4, 0.125)):
        indices = lags * multiple
        valid = indices < autocorrelation.size
        scores[valid] += weight * autocorrelation[indices[valid]]
    best_index = int(np.argmax(scores))
    lag = float(lags[best_index])
    if 0 < best_index < scores.size - 1:
        left, centre, right = scores[best_index - 1:best_index + 2]
        denominator = left - 2.0 * centre + right
        if abs(denominator) > 1e-12:
            lag += float(0.5 * (left - right) / denominator)
    bpm = 60.0 * frame_rate / max(lag, 1e-9)
    baseline = float(np.median(scores))
    peak = float(scores[best_index])
    confidence = max(0.0, min(1.0, (peak - baseline) / (abs(peak) + 1e-12)))
    return bpm, confidence


def _estimate_key(chroma: Any) -> tuple[str, str, float]:
    import numpy as np

    if not np.any(chroma > 0):
        raise ValueError("Audio has too little tonal information for key analysis")
    major = np.array((6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88))
    minor = np.array((6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17))
    observed = chroma.astype(np.float64)
    observed = (observed - observed.mean()) / max(observed.std(), 1e-12)
    scores: list[tuple[float, int, str]] = []
    for scale, profile in (("major", major), ("minor", minor)):
        normalised = (profile - profile.mean()) / profile.std()
        for root in range(12):
            score = float(np.dot(observed, np.roll(normalised, root)) / 12.0)
            scores.append((score, root, scale))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    names = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
    strength = max(0.0, min(1.0, 0.5 * (best[0] + 1.0) + 0.5 * (best[0] - second[0])))
    return names[best[1]], best[2], strength


def _tempo_near_reference(bpm: float, reference_bpm: float | None) -> float:
    if reference_bpm is None or reference_bpm <= 0:
        return bpm
    candidates = [candidate for candidate in (bpm * 0.5, bpm, bpm * 2.0) if 40.0 <= candidate <= 260.0]
    return min(candidates, key=lambda candidate: abs(math.log2(candidate / reference_bpm)))


def analyze_audio(path: Path, reference_bpm: float | None = None) -> AnalysisResult:
    """Read audio and return deterministic musical descriptors without modifying the file."""
    import numpy as np

    sample_rate = 22_050
    audio = _decode_mono(path, sample_rate)
    if len(audio) < sample_rate:
        raise ValueError("Audio is too short for reliable BPM and key analysis")

    onset, chroma = _spectral_descriptors(audio, sample_rate)
    bpm, confidence = _estimate_tempo(onset, sample_rate)
    bpm = _tempo_near_reference(bpm, reference_bpm)
    key, scale, strength = _estimate_key(chroma)

    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    rms_db = 20 * math.log10(max(rms, 1e-9))
    energy_score = min(1.0, max(0.0, (rms_db + 35.0) / 27.0))
    return {
        "bpm": round(bpm, 2),
        "key": camelot_key(key, scale),
        "scale": scale,
        "strength": round(strength, 4),
        "rhythm_confidence": round(confidence, 4),
        "energy_score": round(energy_score, 4),
    }


def _eligible_tracks(
    database: Database,
    track_ids: Iterable[int] | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    ids = list(dict.fromkeys(track_ids or []))
    clauses = ["missing = 0"]
    parameters: list[Any] = []
    if ids:
        clauses.append(f"id IN ({','.join('?' for _ in ids)})")
        parameters.extend(ids)
    if not force:
        clauses.append(
            "(analysis_status != 'completed' OR analysis_modified_ns IS NULL OR analysis_modified_ns != modified_ns)"
        )
    with database.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT id, path, filename, modified_ns, bpm
            FROM tracks WHERE {' AND '.join(clauses)} ORDER BY id
            """,
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def analyze_tracks(
    database: Database,
    track_ids: Iterable[int] | None = None,
    *,
    force: bool = False,
    analyzer: Analyzer = analyze_audio,
    progress: ProgressCallback | None = None,
    should_cancel: CancellationCallback | None = None,
) -> AnalysisProgress:
    database.initialize()
    tracks = _eligible_tracks(database, track_ids, force)
    result = AnalysisProgress(total=len(tracks))

    with database.connect() as connection:
        for track in tracks:
            connection.execute(
                """
                INSERT INTO audio_analysis_jobs(track_id, status, queued_at, started_at, completed_at, error)
                VALUES (?, 'queued', CURRENT_TIMESTAMP, NULL, NULL, NULL)
                ON CONFLICT(track_id) DO UPDATE SET
                    status = 'queued', queued_at = CURRENT_TIMESTAMP,
                    started_at = NULL, completed_at = NULL, error = NULL
                """,
                (track["id"],),
            )
            connection.execute(
                "UPDATE tracks SET analysis_status = 'queued', analysis_error = NULL WHERE id = ?",
                (track["id"],),
            )

    for index, track in enumerate(tracks):
        if should_cancel and should_cancel():
            result.cancelled = True
            remaining_ids = [item["id"] for item in tracks[index:]]
            with database.connect() as connection:
                if remaining_ids:
                    placeholders = ",".join("?" for _ in remaining_ids)
                    connection.execute(
                        f"UPDATE audio_analysis_jobs SET status = 'cancelled', completed_at = CURRENT_TIMESTAMP WHERE track_id IN ({placeholders})",
                        remaining_ids,
                    )
                    connection.execute(
                        f"UPDATE tracks SET analysis_status = 'pending' WHERE id IN ({placeholders})",
                        remaining_ids,
                    )
            break

        result.current_file = track["filename"]
        with database.connect() as connection:
            connection.execute(
                "UPDATE audio_analysis_jobs SET status = 'running', started_at = CURRENT_TIMESTAMP WHERE track_id = ?",
                (track["id"],),
            )
            connection.execute(
                "UPDATE tracks SET analysis_status = 'running', analysis_error = NULL WHERE id = ?",
                (track["id"],),
            )

        try:
            values = (
                analyze_audio(Path(track["path"]), track["bpm"])
                if analyzer is analyze_audio
                else analyzer(Path(track["path"]))
            )
            with database.connect() as connection:
                connection.execute(
                    """
                    UPDATE tracks SET analysis_bpm = ?, analysis_key = ?, analysis_scale = ?,
                        analysis_strength = ?, energy_score = ?, analysis_status = 'completed',
                        analysis_error = NULL, analysis_modified_ns = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        values["bpm"], values["key"], values["scale"], values["strength"],
                        values["energy_score"], track["modified_ns"], track["id"],
                    ),
                )
                connection.execute(
                    """
                    UPDATE audio_analysis_jobs SET status = 'completed', completed_at = CURRENT_TIMESTAMP,
                        error = NULL WHERE track_id = ?
                    """,
                    (track["id"],),
                )
            result.completed += 1
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            with database.connect() as connection:
                connection.execute(
                    "UPDATE tracks SET analysis_status = 'failed', analysis_error = ? WHERE id = ?",
                    (message, track["id"]),
                )
                connection.execute(
                    """
                    UPDATE audio_analysis_jobs SET status = 'failed', completed_at = CURRENT_TIMESTAMP,
                        error = ? WHERE track_id = ?
                    """,
                    (message, track["id"]),
                )
            result.failed += 1

        result.processed += 1
        if progress:
            progress(result)

    return result


def analysis_summary(database: Database) -> dict[str, int]:
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT analysis_status AS status, COUNT(*) AS count
            FROM tracks WHERE missing = 0 GROUP BY analysis_status
            """
        ).fetchall()
    summary = {"pending": 0, "queued": 0, "running": 0, "completed": 0, "failed": 0}
    summary.update({row["status"]: row["count"] for row in rows})
    return summary
