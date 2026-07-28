from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .database import Database


STEM_KINDS = ("vocals", "drums", "bass", "other")
DEFAULT_MODEL = "htdemucs"


class StemCancelled(RuntimeError):
    pass


@dataclass
class StemProgress:
    track_id: int
    status: str = "queued"
    phase: str = "queued"
    progress: float = 0.0
    stem_count: int = 0
    cached: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CancellationCallback = Callable[[], bool]
ProgressCallback = Callable[[StemProgress], None]
SeparationProgressCallback = Callable[[float], None]
Separator = Callable[[Path, Path, str, CancellationCallback | None], dict[str, Path]]


def _runtime_candidates() -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    configured = os.environ.get("DECKSMITH_STEM_PYTHON", "").strip()
    if configured:
        candidates.append(("configured", Path(configured).expanduser()))
    project_root = Path(__file__).resolve().parents[2]
    isolated = project_root / ".venv-stems" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    candidates.extend((
        ("isolated", isolated),
        ("application", Path(sys.executable)),
    ))
    unique: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for runtime, candidate in candidates:
        absolute = Path(os.path.abspath(candidate))
        # Do not resolve the virtual-environment interpreter symlink: Python uses
        # that path to discover pyvenv.cfg and activate the isolated environment.
        if absolute not in seen:
            seen.add(absolute)
            unique.append((runtime, absolute))
    return unique


def _demucs_runtime() -> dict[str, Any] | None:
    bundled = os.environ.get("DECKSMITH_DEMUCS_EXECUTABLE", "").strip()
    if bundled:
        executable = Path(bundled).expanduser()
        if executable.is_file():
            try:
                result = subprocess.run(
                    [str(executable), "--decksmith-capability"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                result = None
            if result is not None and result.returncode == 0:
                values = result.stdout.strip().split("\t", 1)
                if len(values) == 2:
                    return {
                        "executable": str(executable),
                        "runtime": "bundled",
                        "version": values[0],
                        "python_version": values[1],
                    }

    probe = (
        "import importlib.metadata, platform; "
        "import demucs; "
        "print(importlib.metadata.version('demucs') + '\\t' + platform.python_version())"
    )
    for runtime, python in _runtime_candidates():
        if not python.is_file():
            continue
        try:
            result = subprocess.run(
                [str(python), "-c", probe],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        values = result.stdout.strip().split("\t", 1)
        if len(values) != 2:
            continue
        return {
            "python": str(python),
            "runtime": runtime,
            "version": values[0],
            "python_version": values[1],
        }
    return None


def stem_capability() -> dict[str, Any]:
    runtime = _demucs_runtime()
    available = runtime is not None
    return {
        "available": available,
        "engine": "Demucs",
        "version": runtime["version"] if runtime else "",
        "python_version": runtime["python_version"] if runtime else "",
        "runtime": runtime["runtime"] if runtime else "unavailable",
        "default_model": DEFAULT_MODEL,
        "message": (
            f"Local Demucs {runtime['version']} separation is ready."
            if available
            else "Demucs is not installed in Decksmith's isolated Python environment."
        ),
    }


def _emit(progress: ProgressCallback | None, state: StemProgress) -> None:
    if progress:
        progress(state)


def _update_job(
    database: Database,
    track_id: int,
    model: str,
    *,
    status: str,
    phase: str,
    progress: float,
    source_modified_ns: int,
    output_directory: str | None = None,
    error: str | None = None,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO stem_jobs(
                track_id, model, status, phase, progress, source_modified_ns,
                output_directory, queued_at, started_at, completed_at, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP,
                CASE WHEN ? = 'running' THEN CURRENT_TIMESTAMP ELSE NULL END,
                CASE WHEN ? IN ('completed', 'failed', 'cancelled') THEN CURRENT_TIMESTAMP ELSE NULL END,
                ?)
            ON CONFLICT(track_id, model) DO UPDATE SET
                status = excluded.status,
                phase = excluded.phase,
                progress = excluded.progress,
                source_modified_ns = excluded.source_modified_ns,
                output_directory = COALESCE(excluded.output_directory, stem_jobs.output_directory),
                queued_at = CASE WHEN excluded.status = 'queued' THEN CURRENT_TIMESTAMP ELSE stem_jobs.queued_at END,
                started_at = CASE WHEN excluded.status = 'running' THEN CURRENT_TIMESTAMP ELSE stem_jobs.started_at END,
                completed_at = CASE
                    WHEN excluded.status IN ('completed', 'failed', 'cancelled') THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END,
                error = excluded.error
            """,
            (
                int(track_id), model, status, phase, max(0.0, min(1.0, progress)),
                int(source_modified_ns), output_directory, status, status, error,
            ),
        )


def _valid_cached_stems(
    database: Database,
    track_id: int,
    model: str,
    source_modified_ns: int,
) -> list[dict[str, Any]]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM stem_cache
            WHERE track_id = ? AND model = ? AND source_modified_ns = ?
            ORDER BY CASE stem_kind
                WHEN 'vocals' THEN 1 WHEN 'drums' THEN 2 WHEN 'bass' THEN 3 ELSE 4 END
            """,
            (int(track_id), model, int(source_modified_ns)),
        ).fetchall()
    stems = [dict(row) for row in rows]
    if {item["stem_kind"] for item in stems} != set(STEM_KINDS):
        return []
    for item in stems:
        path = Path(item["path"])
        if not path.is_file() or path.stat().st_size <= 0:
            return []
    return stems


def stem_status(
    database: Database,
    track_ids: list[int] | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    database.initialize()
    ids = list(dict.fromkeys(int(value) for value in (track_ids or [])))
    where = ""
    parameters: list[Any] = [model]
    if ids:
        where = f" AND tracks.id IN ({','.join('?' for _ in ids)})"
        parameters.extend(ids)
    with database.connect() as connection:
        jobs = connection.execute(
            f"""
            SELECT stem_jobs.*, tracks.title, tracks.filename,
                CASE WHEN stem_jobs.source_modified_ns = tracks.modified_ns THEN 0 ELSE 1 END AS stale
            FROM stem_jobs
            JOIN tracks ON tracks.id = stem_jobs.track_id
            WHERE stem_jobs.model = ?{where}
            ORDER BY stem_jobs.queued_at DESC, stem_jobs.id DESC
            """,
            parameters,
        ).fetchall()
        track_rows = connection.execute(
            f"SELECT id, modified_ns FROM tracks WHERE 1 = 1{where.replace('tracks.id', 'id')}",
            parameters[1:],
        ).fetchall()
    stems: list[dict[str, Any]] = []
    for track in track_rows:
        stems.extend(_valid_cached_stems(
            database, int(track["id"]), model, int(track["modified_ns"])
        ))
    return {
        "capability": stem_capability(),
        "model": model,
        "jobs": [dict(row) for row in jobs],
        "stems": stems,
        "ready_track_ids": sorted({int(item["track_id"]) for item in stems}),
    }


def run_demucs(
    source: Path,
    working_directory: Path,
    model: str,
    should_cancel: CancellationCallback | None = None,
    separation_progress: SeparationProgressCallback | None = None,
) -> dict[str, Path]:
    runtime = _demucs_runtime()
    if runtime is None:
        raise RuntimeError(
            "Demucs is not installed in Decksmith's isolated Python environment."
        )
    log_path = working_directory / "demucs.log"
    output_root = working_directory / "separated"
    if runtime.get("executable"):
        invocation = [runtime["executable"]]
    else:
        invocation = [runtime["python"], "-m", "demucs"]
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            invocation + [
                "--name",
                model,
                "--out",
                str(output_root),
                str(source),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        last_reported = -1
        while process.poll() is None:
            if should_cancel and should_cancel():
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                raise StemCancelled("Stem separation was cancelled.")
            if separation_progress:
                try:
                    detail = log_path.read_text(errors="replace")[-16_000:]
                    percentages = re.findall(r"(?:^|\r|\n)\s*(\d{1,3})%\|", detail)
                    if percentages:
                        current = min(100, max(0, int(percentages[-1])))
                        if current != last_reported:
                            last_reported = current
                            separation_progress(current / 100)
                except OSError:
                    pass
            time.sleep(0.25)
    if process.returncode != 0:
        detail = log_path.read_text(errors="replace")[-4000:].strip()
        raise RuntimeError(detail or f"Demucs exited with status {process.returncode}.")

    outputs: dict[str, Path] = {}
    for stem_kind in STEM_KINDS:
        matches = list(output_root.rglob(f"{stem_kind}.wav"))
        if len(matches) != 1:
            raise RuntimeError(f"Demucs did not produce exactly one {stem_kind} stem.")
        outputs[stem_kind] = matches[0]
    return outputs


def separate_track_stems(
    database: Database,
    track_id: int,
    cache_directory: str | Path,
    *,
    model: str = DEFAULT_MODEL,
    force: bool = False,
    separator: Separator | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancellationCallback | None = None,
) -> StemProgress:
    database.initialize()
    normalized_model = str(model).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", normalized_model):
        raise ValueError("Stem model name is invalid.")
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT id, path, filename, modified_ns, missing
            FROM tracks WHERE id = ?
            """,
            (int(track_id),),
        ).fetchone()
    if row is None:
        raise ValueError("Library track was not found.")
    source = Path(row["path"])
    source_modified_ns = int(row["modified_ns"])
    if row["missing"] or not source.is_file():
        raise ValueError("This track is missing from disk and cannot be separated.")
    if source.stat().st_mtime_ns != source_modified_ns:
        raise ValueError("The source track changed on disk. Rescan its music folder first.")
    source_bytes_before = source.stat().st_size

    cached = _valid_cached_stems(database, int(track_id), normalized_model, source_modified_ns)
    if cached and not force:
        state = StemProgress(
            track_id=int(track_id), status="completed", phase="cached", progress=1.0,
            stem_count=len(cached), cached=True,
        )
        _emit(progress, state)
        return state
    if separator is None:
        separator = run_demucs
        if not stem_capability()["available"]:
            raise RuntimeError(
                "Demucs is not installed in Decksmith's isolated Python environment."
            )

    cache_root = Path(cache_directory).expanduser().resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    working_root = cache_root / ".working"
    working_root.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    working_directory = working_root / nonce
    ready_directory = working_directory / "ready"
    final_directory = cache_root / f"{int(track_id)}-{source_modified_ns}-{normalized_model}-{nonce[:8]}"
    working_directory.mkdir(parents=True)

    state = StemProgress(track_id=int(track_id))
    _update_job(
        database, int(track_id), normalized_model, status="queued", phase="queued",
        progress=0, source_modified_ns=source_modified_ns, error=None,
    )
    _emit(progress, state)

    old_directories: set[Path] = set()
    published = False
    cache_committed = False
    try:
        if should_cancel and should_cancel():
            raise StemCancelled("Stem separation was cancelled.")
        state.status = "running"
        state.phase = "separating"
        state.progress = 0.1
        _update_job(
            database, int(track_id), normalized_model, status=state.status, phase=state.phase,
            progress=state.progress, source_modified_ns=source_modified_ns, error=None,
        )
        _emit(progress, state)

        if separator is run_demucs:
            def report_separation(value: float) -> None:
                state.progress = 0.1 + max(0, min(1, value)) * 0.72
                _update_job(
                    database, int(track_id), normalized_model,
                    status=state.status, phase=state.phase,
                    progress=state.progress, source_modified_ns=source_modified_ns,
                    error=None,
                )
                _emit(progress, state)

            outputs = run_demucs(
                source,
                working_directory,
                normalized_model,
                should_cancel,
                report_separation,
            )
        else:
            outputs = separator(source, working_directory, normalized_model, should_cancel)
        if should_cancel and should_cancel():
            raise StemCancelled("Stem separation was cancelled.")
        if set(outputs) != set(STEM_KINDS):
            raise RuntimeError("The stem engine did not return all four required stems.")

        state.phase = "validating"
        state.progress = 0.85
        _update_job(
            database, int(track_id), normalized_model, status=state.status, phase=state.phase,
            progress=state.progress, source_modified_ns=source_modified_ns, error=None,
        )
        _emit(progress, state)
        ready_directory.mkdir()
        resolved_work = working_directory.resolve()
        for stem_kind in STEM_KINDS:
            stem_source = Path(outputs[stem_kind]).resolve()
            if not stem_source.is_relative_to(resolved_work):
                raise RuntimeError("The stem engine returned output outside Decksmith's cache workspace.")
            if not stem_source.is_file() or stem_source.stat().st_size <= 0:
                raise RuntimeError(f"The generated {stem_kind} stem is empty or missing.")
            shutil.copy2(stem_source, ready_directory / f"{stem_kind}.wav")

        if source.stat().st_size != source_bytes_before or source.stat().st_mtime_ns != source_modified_ns:
            raise RuntimeError("The source track changed during separation. Cached output was discarded.")
        os.replace(ready_directory, final_directory)
        published = True
        with database.connect() as connection:
            previous = connection.execute(
                "SELECT path FROM stem_cache WHERE track_id = ? AND model = ?",
                (int(track_id), normalized_model),
            ).fetchall()
            old_directories = {Path(item["path"]).parent for item in previous}
            connection.execute(
                "DELETE FROM stem_cache WHERE track_id = ? AND model = ?",
                (int(track_id), normalized_model),
            )
            for stem_kind in STEM_KINDS:
                stem_path = final_directory / f"{stem_kind}.wav"
                connection.execute(
                    """
                    INSERT INTO stem_cache(
                        track_id, stem_kind, model, source_modified_ns, path, file_size
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(track_id), stem_kind, normalized_model, source_modified_ns,
                        str(stem_path), stem_path.stat().st_size,
                    ),
                )
        cache_committed = True
        state.status = "completed"
        state.phase = "completed"
        state.progress = 1.0
        state.stem_count = 4
        _update_job(
            database, int(track_id), normalized_model, status=state.status, phase=state.phase,
            progress=state.progress, source_modified_ns=source_modified_ns,
            output_directory=str(final_directory), error=None,
        )
        for directory in old_directories:
            resolved = directory.resolve()
            if resolved != final_directory and resolved.is_relative_to(cache_root):
                shutil.rmtree(resolved, ignore_errors=True)
        _emit(progress, state)
        return state
    except StemCancelled as error:
        state.status = "cancelled"
        state.phase = "cancelled"
        state.error = str(error)
        _update_job(
            database, int(track_id), normalized_model, status=state.status, phase=state.phase,
            progress=state.progress, source_modified_ns=source_modified_ns, error=state.error,
        )
        _emit(progress, state)
        return state
    except Exception as error:
        if published and not cache_committed and final_directory.is_relative_to(cache_root):
            shutil.rmtree(final_directory, ignore_errors=True)
        state.status = "failed"
        state.phase = "failed"
        state.error = f"{type(error).__name__}: {error}"
        _update_job(
            database, int(track_id), normalized_model, status=state.status, phase=state.phase,
            progress=state.progress, source_modified_ns=source_modified_ns, error=state.error,
        )
        _emit(progress, state)
        raise
    finally:
        shutil.rmtree(working_directory, ignore_errors=True)
