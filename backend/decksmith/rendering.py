from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .database import Database


OUTPUT_SAMPLE_RATE = 44_100


class RenderCancelled(RuntimeError):
    pass


@dataclass
class RenderProgress:
    clip_id: int
    status: str = "queued"
    phase: str = "queued"
    progress: float = 0.0
    cached: bool = False
    path: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CancellationCallback = Callable[[], bool]
ProgressCallback = Callable[[RenderProgress], None]
Renderer = Callable[[dict[str, Any], Path, Path, str, CancellationCallback | None], None]


def _ffmpeg_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("DECKSMITH_FFMPEG", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    discovered = shutil.which("ffmpeg")
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend((
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
    ))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        absolute = Path(os.path.abspath(candidate))
        if absolute not in seen:
            seen.add(absolute)
            unique.append(absolute)
    return unique


def _ffmpeg_runtime() -> dict[str, str] | None:
    for executable in _ffmpeg_candidates():
        if not executable.is_file():
            continue
        try:
            result = subprocess.run(
                [str(executable), "-hide_banner", "-version"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        values = first_line.split()
        version = values[2] if len(values) >= 3 else "available"
        return {"path": str(executable), "version": version}
    return None


def render_capability() -> dict[str, Any]:
    runtime = _ffmpeg_runtime()
    return {
        "available": runtime is not None,
        "engine": "FFmpeg",
        "version": runtime["version"] if runtime else "",
        "message": (
            f"Local FFmpeg {runtime['version']} rendering is ready."
            if runtime
            else "FFmpeg is not installed, so processed clip previews are unavailable."
        ),
    }


def _clip_rows(database: Database, clip_ids: list[int] | None = None) -> list[dict[str, Any]]:
    ids = list(dict.fromkeys(int(value) for value in (clip_ids or [])))
    where = ""
    parameters: list[Any] = []
    if clip_ids is not None:
        if ids:
            where = f" WHERE timeline_clips.id IN ({','.join('?' for _ in ids)})"
            parameters.extend(ids)
        else:
            where = " WHERE 0"
    with database.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT timeline_clips.*,
                CASE
                    WHEN timeline_clips.clip_kind = 'rendered'
                        THEN rendered_clip_sources.path
                    WHEN timeline_clips.clip_kind IN ('vocals', 'drums', 'bass', 'other')
                        THEN stem_cache.path
                    ELSE tracks.path
                END AS source_path,
                CASE WHEN timeline_clips.clip_kind = 'rendered'
                    THEN rendered_clip_sources.duration_seconds
                    ELSE tracks.duration_seconds END AS source_duration_seconds,
                tracks.modified_ns AS track_modified_ns,
                CASE
                    WHEN timeline_clips.clip_kind = 'rendered'
                        THEN CASE WHEN rendered_clip_sources.path IS NULL THEN 1 ELSE 0 END
                    WHEN timeline_clips.clip_kind IN ('vocals', 'drums', 'bass', 'other')
                        THEN CASE WHEN stem_cache.path IS NULL THEN 1 ELSE 0 END
                    ELSE tracks.missing
                END AS missing,
                tracks.title, tracks.filename
            FROM timeline_clips
            JOIN tracks ON tracks.id = timeline_clips.track_id
            LEFT JOIN rendered_clip_sources
              ON rendered_clip_sources.clip_id = timeline_clips.id
            LEFT JOIN stem_cache
              ON stem_cache.track_id = timeline_clips.track_id
             AND stem_cache.stem_kind = timeline_clips.clip_kind
             AND stem_cache.model = 'htdemucs'
             AND stem_cache.source_modified_ns = tracks.modified_ns
            {where}
            ORDER BY timeline_clips.id
            """,
            parameters,
        ).fetchall()
    clips = [dict(row) for row in rows]
    clip_ids_for_states = [int(clip["id"]) for clip in clips]
    state_map: dict[int, dict[str, dict[str, int]]] = {}
    stem_paths: dict[tuple[int, str], str] = {}
    if clip_ids_for_states:
        placeholders = ",".join("?" for _ in clip_ids_for_states)
        track_ids = sorted({int(clip["track_id"]) for clip in clips})
        track_placeholders = ",".join("?" for _ in track_ids)
        with database.connect() as connection:
            for state in connection.execute(
                f"SELECT * FROM clip_stem_states WHERE clip_id IN ({placeholders})",
                clip_ids_for_states,
            ).fetchall():
                state_map.setdefault(int(state["clip_id"]), {})[str(state["stem_kind"])] = {
                    "muted": int(state["muted"]), "solo": int(state["solo"]),
                }
            for stem in connection.execute(
                f"""
                SELECT stem_cache.track_id, stem_cache.stem_kind, stem_cache.path
                FROM stem_cache
                JOIN tracks ON tracks.id = stem_cache.track_id
                WHERE stem_cache.track_id IN ({track_placeholders})
                  AND stem_cache.model = 'htdemucs'
                  AND stem_cache.source_modified_ns = tracks.modified_ns
                """,
                track_ids,
            ).fetchall():
                stem_paths[(int(stem["track_id"]), str(stem["stem_kind"]))] = str(stem["path"])
    for clip in clips:
        states = state_map.get(int(clip["id"]), {})
        clip["stem_states"] = states
        if str(clip["clip_kind"]) == "song" and states:
            solo_active = any(state["solo"] for state in states.values())
            active_kinds = [
                kind for kind in ("vocals", "drums", "bass", "other")
                if (
                    states.get(kind, {}).get("solo", 0)
                    if solo_active else not states.get(kind, {}).get("muted", 0)
                )
            ]
            if set(active_kinds) != {"vocals", "drums", "bass", "other"}:
                sources = [stem_paths.get((int(clip["track_id"]), kind), "") for kind in active_kinds]
                clip["stem_mix_kinds"] = active_kinds
                clip["stem_mix_sources"] = sources
                clip["stem_mix_silence"] = not active_kinds
                if sources:
                    clip["source_path"] = sources[0]
                clip["missing"] = int(any(not Path(path).is_file() for path in sources))
        source_value = clip.get("source_path")
        source = Path(source_value) if source_value else None
        clip["source_modified_ns"] = (
            source.stat().st_mtime_ns if source and source.is_file() else int(clip["track_modified_ns"])
        )
    return clips


def _render_signature(clip: dict[str, Any]) -> str:
    mix_sources = [str(path) for path in clip.get("stem_mix_sources", [])]
    mix_source_states = [
        {"path": path, "modified_ns": Path(path).stat().st_mtime_ns if Path(path).is_file() else 0}
        for path in mix_sources
    ]
    payload = {
        "clip_id": int(clip["id"]),
        "source_path": str(clip["source_path"]),
        "source_modified_ns": int(clip["source_modified_ns"]),
        "stem_mix_sources": mix_source_states,
        "stem_mix_kinds": clip.get("stem_mix_kinds", []),
        "stem_mix_silence": bool(clip.get("stem_mix_silence")),
        "stem_states": clip.get("stem_states", {}),
        "source_in_seconds": round(float(clip["source_in_seconds"]), 6),
        "duration_seconds": round(float(clip["duration_seconds"]), 6),
        "tempo_percent": round(float(clip["tempo_percent"]), 6),
        "pitch_semitones": round(float(clip["pitch_semitones"]), 6),
        "reversed": int(bool(clip["reversed"])),
        "sample_rate": OUTPUT_SAMPLE_RATE,
        "format": "pcm_s16le_stereo_sample_accurate_waveform_v3",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _valid_cached_render(
    database: Database, clip: dict[str, Any], signature: str
) -> dict[str, Any] | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM render_cache WHERE clip_id = ? AND signature = ?",
            (int(clip["id"]), signature),
        ).fetchone()
    if row is None:
        return None
    item = dict(row)
    path = Path(item["path"])
    if not path.is_file() or path.stat().st_size != int(item["file_size"]):
        return None
    return item


def _update_job(
    database: Database,
    clip_id: int,
    signature: str,
    *,
    status: str,
    phase: str,
    progress: float,
    output_path: str | None = None,
    error: str | None = None,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO render_jobs(
                clip_id, signature, status, phase, progress, output_path,
                queued_at, started_at, completed_at, error
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP,
                CASE WHEN ? = 'running' THEN CURRENT_TIMESTAMP ELSE NULL END,
                CASE WHEN ? IN ('completed', 'failed', 'cancelled') THEN CURRENT_TIMESTAMP ELSE NULL END,
                ?)
            ON CONFLICT(clip_id) DO UPDATE SET
                signature = excluded.signature,
                status = excluded.status,
                phase = excluded.phase,
                progress = excluded.progress,
                output_path = COALESCE(excluded.output_path, render_jobs.output_path),
                queued_at = CASE WHEN excluded.status = 'queued' THEN CURRENT_TIMESTAMP ELSE render_jobs.queued_at END,
                started_at = CASE WHEN excluded.status = 'running' THEN CURRENT_TIMESTAMP ELSE render_jobs.started_at END,
                completed_at = CASE
                    WHEN excluded.status IN ('completed', 'failed', 'cancelled') THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END,
                error = excluded.error
            """,
            (
                int(clip_id), signature, status, phase,
                max(0.0, min(1.0, float(progress))), output_path,
                status, status, error,
            ),
        )


def render_status(database: Database, clip_ids: list[int] | None = None) -> dict[str, Any]:
    database.initialize()
    clips = _clip_rows(database, clip_ids)
    ids = [int(clip["id"]) for clip in clips]
    jobs: list[dict[str, Any]] = []
    cache_rows: dict[int, dict[str, Any]] = {}
    if ids:
        placeholders = ",".join("?" for _ in ids)
        with database.connect() as connection:
            jobs = [dict(row) for row in connection.execute(
                f"SELECT * FROM render_jobs WHERE clip_id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()]
            cache_rows = {
                int(row["clip_id"]): dict(row)
                for row in connection.execute(
                    f"SELECT * FROM render_cache WHERE clip_id IN ({placeholders})", ids
                ).fetchall()
            }
    signatures = {int(clip["id"]): _render_signature(clip) for clip in clips}
    for job in jobs:
        job["stale"] = int(job["signature"] != signatures.get(int(job["clip_id"])))
    renders: list[dict[str, Any]] = []
    for clip in clips:
        clip_id = int(clip["id"])
        cached = cache_rows.get(clip_id)
        if cached is None or cached["signature"] != signatures[clip_id]:
            continue
        path = Path(cached["path"])
        if path.is_file() and path.stat().st_size == int(cached["file_size"]):
            waveform_path = path.with_suffix(".waveform.png")
            cached["waveform_path"] = str(waveform_path) if waveform_path.is_file() else ""
            renders.append(cached)
    return {
        "capability": render_capability(),
        "jobs": jobs,
        "renders": renders,
        "ready_clip_ids": sorted(int(item["clip_id"]) for item in renders),
    }


def _atempo_filters(factor: float) -> list[str]:
    filters: list[str] = []
    remaining = float(factor)
    while remaining < 0.5 - 1e-9:
        filters.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2.0 + 1e-9:
        filters.append("atempo=2")
        remaining /= 2.0
    if abs(remaining - 1.0) > 1e-9:
        if abs(remaining - 0.5) <= 1e-9:
            filters.append("atempo=0.5")
        elif abs(remaining - 2.0) <= 1e-9:
            filters.append("atempo=2")
        else:
            filters.append(f"atempo={remaining:.10f}")
    return filters


def run_ffmpeg(
    clip: dict[str, Any],
    source: Path,
    output: Path,
    executable: str,
    should_cancel: CancellationCallback | None = None,
) -> None:
    duration = float(clip["duration_seconds"])
    if clip.get("stem_mix_silence"):
        result = subprocess.run(
            [
                executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"anullsrc=r={OUTPUT_SAMPLE_RATE}:cl=stereo",
                "-t", f"{duration:.6f}", "-c:a", "pcm_s16le", str(output),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "FFmpeg could not render the muted stem mix.")
        return
    tempo_factor = float(clip["tempo_percent"]) / 100.0
    source_span = duration * tempo_factor
    pitch_factor = 2 ** (float(clip["pitch_semitones"]) / 12.0)
    source_start = float(clip["source_in_seconds"])
    source_end = source_start + source_span
    filters = [
        f"atrim=start={source_start:.9f}:end={source_end:.9f}",
        "asetpts=PTS-STARTPTS",
        f"aresample={OUTPUT_SAMPLE_RATE}",
    ]
    if clip["reversed"]:
        filters.append("areverse")
    if abs(pitch_factor - 1.0) > 1e-9:
        filters.extend((
            f"asetrate={OUTPUT_SAMPLE_RATE * pitch_factor:.8f}",
            f"aresample={OUTPUT_SAMPLE_RATE}",
        ))
    filters.extend(_atempo_filters(tempo_factor / pitch_factor))
    filters.extend((
        f"apad=whole_dur={duration:.6f}",
        f"atrim=duration={duration:.6f}",
    ))
    mix_sources = [Path(path) for path in clip.get("stem_mix_sources", [])]
    log_path = output.parent / "ffmpeg.log"
    with log_path.open("wb") as log:
        input_arguments: list[str] = []
        for path in (mix_sources or [source]):
            input_arguments.extend(["-i", str(path)])
        if mix_sources:
            labels = "".join(f"[{index}:a]" for index in range(len(mix_sources)))
            filter_arguments = [
                "-filter_complex",
                f"{labels}amix=inputs={len(mix_sources)}:duration=longest:"
                f"dropout_transition=0:normalize=0,{','.join(filters)}[out]",
                "-map", "[out]",
            ]
        else:
            filter_arguments = ["-af", ",".join(filters)]
        process = subprocess.Popen(
            [
                executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                *input_arguments, "-vn", *filter_arguments,
                "-ar", str(OUTPUT_SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_s16le",
                str(output),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        while process.poll() is None:
            if should_cancel and should_cancel():
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise RenderCancelled("Clip rendering was cancelled.")
            time.sleep(0.1)
    if process.returncode != 0:
        detail = log_path.read_text(errors="replace")[-4000:].strip()
        raise RuntimeError(detail or f"FFmpeg exited with status {process.returncode}.")


def _validate_wave(path: Path, duration_seconds: float) -> None:
    if not path.is_file() or path.stat().st_size <= 44:
        raise RuntimeError("The rendered clip is missing or empty.")
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_rate = audio.getframerate()
            frames = audio.getnframes()
    except (OSError, wave.Error) as error:
        raise RuntimeError(f"The rendered clip is not a valid WAV file: {error}") from error
    actual_duration = frames / sample_rate if sample_rate else 0
    if channels != 2 or sample_rate != OUTPUT_SAMPLE_RATE:
        raise RuntimeError("The rendered clip must be 44.1 kHz stereo audio.")
    if abs(actual_duration - duration_seconds) > 0.06:
        raise RuntimeError("The rendered clip duration does not match its timeline duration.")


def _generate_render_waveform(source: Path, destination: Path, executable: str) -> None:
    process = subprocess.run(
        [
            executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-filter_complex",
            "aformat=channel_layouts=mono,showwavespic=s=16384x256:colors=#9a7cff",
            "-frames:v", "1", str(destination),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if process.returncode != 0 or not destination.is_file():
        raise RuntimeError(
            process.stderr.strip() or "FFmpeg could not generate the prepared waveform."
        )


def render_clip(
    database: Database,
    clip_id: int,
    cache_directory: str | Path,
    *,
    force: bool = False,
    renderer: Renderer | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancellationCallback | None = None,
) -> RenderProgress:
    database.initialize()
    clips = _clip_rows(database, [int(clip_id)])
    if not clips:
        raise ValueError("Timeline clip was not found.")
    clip = clips[0]
    source = Path(clip["source_path"])
    sources = [Path(path) for path in clip.get("stem_mix_sources", [])] or [source]
    if clip["missing"] or any(not path.is_file() for path in sources):
        raise ValueError("This clip's source track is missing from disk.")
    source_stats = {path: path.stat() for path in sources}
    source_stat = source_stats[source]
    if not clip.get("stem_mix_sources") and source_stat.st_mtime_ns != int(clip["source_modified_ns"]):
        raise ValueError("The source track changed on disk. Rescan its music folder first.")
    source_span = float(clip["duration_seconds"]) * float(clip["tempo_percent"]) / 100.0
    if float(clip["source_in_seconds"]) + source_span > float(clip["source_duration_seconds"]) + 0.001:
        raise ValueError("The processed clip exceeds its source track duration.")
    signature = _render_signature(clip)
    cached = _valid_cached_render(database, clip, signature)
    if cached and not force:
        state = RenderProgress(
            clip_id=int(clip_id), status="completed", phase="cached", progress=1.0,
            cached=True, path=str(cached["path"]),
        )
        if progress:
            progress(state)
        return state

    runtime = _ffmpeg_runtime()
    if renderer is None and runtime is None:
        raise RuntimeError("FFmpeg is not installed, so this clip cannot be rendered.")
    executable = runtime["path"] if runtime else "test-renderer"
    active_renderer = renderer or run_ffmpeg
    cache_root = Path(cache_directory).expanduser().resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    working_root = cache_root / ".working"
    working_root.mkdir(parents=True, exist_ok=True)
    working = working_root / uuid.uuid4().hex
    working.mkdir()
    output = working / "render.wav"
    # Every publication gets a distinct cache path. A forced re-render can then
    # fail after publication without deleting the last known-good cached file.
    final_path = cache_root / (
        f"clip-{int(clip_id)}-{signature[:16]}-{uuid.uuid4().hex[:10]}.wav"
    )
    state = RenderProgress(clip_id=int(clip_id))

    def emit() -> None:
        if progress:
            progress(state)

    _update_job(
        database, int(clip_id), signature, status="queued", phase="queued", progress=0,
        error=None,
    )
    emit()
    published = False
    try:
        if should_cancel and should_cancel():
            raise RenderCancelled("Clip rendering was cancelled.")
        state.status = "running"
        state.phase = "rendering"
        state.progress = 0.1
        _update_job(
            database, int(clip_id), signature, status=state.status, phase=state.phase,
            progress=state.progress, error=None,
        )
        emit()
        active_renderer(clip, source, output, executable, should_cancel)
        if should_cancel and should_cancel():
            raise RenderCancelled("Clip rendering was cancelled.")
        state.phase = "validating"
        state.progress = 0.85
        _update_job(
            database, int(clip_id), signature, status=state.status, phase=state.phase,
            progress=state.progress, error=None,
        )
        emit()
        _validate_wave(output, float(clip["duration_seconds"]))
        if any(
            path.stat().st_size != source_stats[path].st_size
            or path.stat().st_mtime_ns != source_stats[path].st_mtime_ns
            for path in sources
        ):
            raise RuntimeError("The source track changed during rendering. Output was discarded.")
        os.replace(output, final_path)
        published = True
        if runtime is not None:
            _generate_render_waveform(
                final_path,
                final_path.with_suffix(".waveform.png"),
                runtime["path"],
            )
        old_path: Path | None = None
        with database.connect() as connection:
            previous = connection.execute(
                "SELECT path FROM render_cache WHERE clip_id = ?", (int(clip_id),)
            ).fetchone()
            if previous:
                old_path = Path(previous["path"])
            connection.execute(
                """
                INSERT INTO render_cache(
                    clip_id, signature, source_modified_ns, path, file_size, duration_seconds
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(clip_id) DO UPDATE SET
                    signature = excluded.signature,
                    source_modified_ns = excluded.source_modified_ns,
                    path = excluded.path,
                    file_size = excluded.file_size,
                    duration_seconds = excluded.duration_seconds,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    int(clip_id), signature, int(clip["source_modified_ns"]),
                    str(final_path), final_path.stat().st_size,
                    float(clip["duration_seconds"]),
                ),
            )
        if old_path and old_path != final_path and old_path.is_relative_to(cache_root):
            old_path.unlink(missing_ok=True)
            old_path.with_suffix(".waveform.png").unlink(missing_ok=True)
        state.status = "completed"
        state.phase = "completed"
        state.progress = 1.0
        state.path = str(final_path)
        _update_job(
            database, int(clip_id), signature, status=state.status, phase=state.phase,
            progress=state.progress, output_path=state.path, error=None,
        )
        emit()
        return state
    except RenderCancelled as error:
        state.status = "cancelled"
        state.phase = "cancelled"
        state.error = str(error)
        _update_job(
            database, int(clip_id), signature, status=state.status, phase=state.phase,
            progress=state.progress, error=state.error,
        )
        emit()
        return state
    except Exception as error:
        if published and final_path.is_relative_to(cache_root):
            final_path.unlink(missing_ok=True)
            final_path.with_suffix(".waveform.png").unlink(missing_ok=True)
        state.status = "failed"
        state.phase = "failed"
        state.error = f"{type(error).__name__}: {error}"
        _update_job(
            database, int(clip_id), signature, status=state.status, phase=state.phase,
            progress=state.progress, error=state.error,
        )
        emit()
        raise
    finally:
        shutil.rmtree(working, ignore_errors=True)
