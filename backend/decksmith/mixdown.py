from __future__ import annotations

import json
import hashlib
import math
import os
import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .database import Database
from .projects import load_project
from .rendering import OUTPUT_SAMPLE_RATE, _ffmpeg_runtime, render_status


MixdownRunner = Callable[[list[str]], None]


def _finite_metric(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 3) if math.isfinite(number) else None


def parse_loudnorm_measurement(output: str) -> dict[str, float | None]:
    blocks = re.findall(r'\{\s*"input_i".*?\}', output, flags=re.DOTALL)
    if not blocks:
        raise RuntimeError("FFmpeg did not return a loudness measurement.")
    try:
        payload = json.loads(blocks[-1])
    except json.JSONDecodeError as error:
        raise RuntimeError("FFmpeg returned an invalid loudness measurement.") from error
    return {
        "integrated_lufs": _finite_metric(payload.get("input_i")),
        "true_peak_dbfs": _finite_metric(payload.get("input_tp")),
        "loudness_range_lu": _finite_metric(payload.get("input_lra")),
        "threshold_lufs": _finite_metric(payload.get("input_thresh")),
        "normalization_offset_db": _finite_metric(payload.get("target_offset")),
    }


def parse_silence_intervals(output: str, duration_seconds: float) -> list[dict[str, float]]:
    events = re.findall(r"silence_(start|end):\s*(-?[0-9.]+)", output)
    intervals: list[dict[str, float]] = []
    pending: float | None = None
    for event, raw_value in events:
        value = max(0.0, float(raw_value))
        if event == "start":
            pending = value
        elif pending is not None and value > pending:
            intervals.append({
                "start_seconds": round(pending, 3),
                "end_seconds": round(min(value, duration_seconds), 3),
                "duration_seconds": round(min(value, duration_seconds) - pending, 3),
            })
            pending = None
    if pending is not None and duration_seconds > pending:
        intervals.append({
            "start_seconds": round(pending, 3),
            "end_seconds": round(duration_seconds, 3),
            "duration_seconds": round(duration_seconds - pending, 3),
        })
    return intervals


def _active_clips(payload: dict[str, Any]) -> list[dict[str, Any]]:
    clips = [clip for clip in payload["clips"] if not clip["muted"]]
    if any(clip["solo"] for clip in clips):
        clips = [clip for clip in clips if clip["solo"]]
    return clips


def project_mix_signature(
    payload: dict[str, Any], renders: list[dict[str, Any]] | None = None
) -> str:
    project_fields = (
        "master_gain_db", "master_limiter_enabled", "master_low_eq_db",
        "master_mid_eq_db", "master_high_eq_db", "master_stereo_width", "target_lufs",
    )
    clip_fields = (
        "id", "track_id", "clip_kind", "channel", "start_seconds", "source_in_seconds",
        "duration_seconds", "gain_db", "pan", "pitch_semitones", "tempo_percent",
        "muted", "solo", "loop_enabled", "reversed", "fade_in_seconds",
        "fade_out_seconds", "eq_low_db", "eq_mid_db", "eq_high_db", "highpass_hz",
        "lowpass_hz", "compressor_enabled", "compressor_threshold_db", "compressor_ratio",
    )
    render_signatures = {
        int(render["clip_id"]): str(render["signature"]) for render in (renders or [])
    }
    state = {
        "project": {field: payload["project"].get(field) for field in project_fields},
        "clips": [
            {
                **{field: clip.get(field) for field in clip_fields},
                "stem_states": clip.get("stem_states", {}),
                "render_signature": render_signatures.get(int(clip["id"])),
            }
            for clip in sorted(payload["clips"], key=lambda item: int(item["id"]))
        ],
    }
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clip_filter(index: int, clip: dict[str, Any]) -> str:
    filters = [f"[{index}:a]atrim=duration={float(clip['duration_seconds']):.6f}"]
    low_eq = float(clip["eq_low_db"])
    mid_eq = float(clip["eq_mid_db"])
    high_eq = float(clip["eq_high_db"])
    if abs(low_eq) > 0.0001:
        filters.append(f"bass=g={low_eq:.4f}:f=120:w=0.7")
    if abs(mid_eq) > 0.0001:
        filters.append(f"equalizer=f=1000:t=q:w=1:g={mid_eq:.4f}")
    if abs(high_eq) > 0.0001:
        filters.append(f"treble=g={high_eq:.4f}:f=8000:w=0.7")
    highpass = float(clip["highpass_hz"])
    lowpass = float(clip["lowpass_hz"])
    if highpass > 20.001:
        filters.append(f"highpass=f={highpass:.3f}")
    if lowpass < 19999.999:
        filters.append(f"lowpass=f={lowpass:.3f}")
    if clip["compressor_enabled"]:
        filters.append(
            "acompressor="
            f"threshold={float(clip['compressor_threshold_db']):.3f}dB:"
            f"ratio={float(clip['compressor_ratio']):.3f}:"
            "attack=3:release=250:makeup=1"
        )
    gain = float(clip["gain_db"])
    if abs(gain) > 0.0001:
        filters.append(f"volume={gain:.4f}dB")
    pan = max(-1.0, min(1.0, float(clip["pan"])))
    if abs(pan) > 0.0001:
        left = min(1.0, 1.0 - pan)
        right = min(1.0, 1.0 + pan)
        filters.append(f"pan=stereo|c0={left:.8f}*c0|c1={right:.8f}*c1")
    fade_in = min(float(clip["fade_in_seconds"]), float(clip["duration_seconds"]))
    fade_out = min(float(clip["fade_out_seconds"]), float(clip["duration_seconds"]))
    if fade_in > 0.0001:
        filters.append(f"afade=t=in:st=0:d={fade_in:.6f}")
    if fade_out > 0.0001:
        start = max(0.0, float(clip["duration_seconds"]) - fade_out)
        filters.append(f"afade=t=out:st={start:.6f}:d={fade_out:.6f}")
    delay_ms = max(0, round(float(clip["start_seconds"]) * 1000))
    if delay_ms:
        filters.append(f"adelay=delays={delay_ms}:all=1")
    return ",".join(filters) + f"[clip{index}]"


def build_mixdown_command(
    executable: str,
    payload: dict[str, Any],
    prepared_paths: dict[int, str],
    destination: Path,
    audio_format: str,
) -> list[str]:
    clips = _active_clips(payload)
    if not clips:
        raise ValueError("The project has no audible clips to export.")
    missing = [int(clip["id"]) for clip in clips if int(clip["id"]) not in prepared_paths]
    if missing:
        raise ValueError("Every audible clip must finish preparing before export.")
    command = [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command += ["-i", prepared_paths[int(clip["id"])]]
    filters = [_clip_filter(index, clip) for index, clip in enumerate(clips)]
    labels = "".join(f"[clip{index}]" for index in range(len(clips)))
    project_duration = max(
        float(clip["start_seconds"]) + float(clip["duration_seconds"]) for clip in clips
    )
    master = payload["project"]
    master_filters = [
        f"{labels}amix=inputs={len(clips)}:duration=longest:dropout_transition=0:normalize=0"
    ]
    low_eq = float(master["master_low_eq_db"])
    mid_eq = float(master["master_mid_eq_db"])
    high_eq = float(master["master_high_eq_db"])
    if abs(low_eq) > 0.0001:
        master_filters.append(f"bass=g={low_eq:.4f}:f=120:w=0.7")
    if abs(mid_eq) > 0.0001:
        master_filters.append(f"equalizer=f=1000:t=q:w=1:g={mid_eq:.4f}")
    if abs(high_eq) > 0.0001:
        master_filters.append(f"treble=g={high_eq:.4f}:f=8000:w=0.7")
    stereo_width = float(master["master_stereo_width"])
    if abs(stereo_width - 1.0) > 0.0001:
        master_filters.append(f"stereotools=mlev=1:slev={stereo_width:.4f}")
    master_gain = float(master["master_gain_db"])
    if abs(master_gain) > 0.0001:
        master_filters.append(f"volume={master_gain:.4f}dB")
    if master["master_limiter_enabled"]:
        master_filters.append("alimiter=limit=0.98:attack=5:release=50")
    master_filters.extend((
        f"apad=whole_dur={project_duration:.6f}",
        f"atrim=duration={project_duration:.6f}[out]",
    ))
    filters.append(",".join(master_filters))
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-ar", str(OUTPUT_SAMPLE_RATE), "-ac", "2",
    ])
    if audio_format == "wav":
        command.extend(["-c:a", "pcm_s24le"])
    elif audio_format == "mp3":
        command.extend(["-c:a", "libmp3lame", "-q:a", "2"])
    else:
        raise ValueError("Audio export format must be WAV or MP3.")
    command.append(str(destination))
    return command


def _run_mixdown(command: list[str]) -> None:
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "FFmpeg could not export the project mixdown.")


def _run_analysis(command: list[str]) -> str:
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "FFmpeg could not analyse the project audio.")
    return result.stderr


def _overlap(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float, float]:
    start = max(float(left["start_seconds"]), float(right["start_seconds"]))
    end = min(
        float(left["start_seconds"]) + float(left["duration_seconds"]),
        float(right["start_seconds"]) + float(right["duration_seconds"]),
    )
    return start, end, max(0.0, end - start)


def build_smart_render_issues(
    payload: dict[str, Any],
    metrics: dict[str, float | None],
    silence_intervals: list[dict[str, float]],
) -> list[dict[str, Any]]:
    clips = sorted(_active_clips(payload), key=lambda clip: (clip["start_seconds"], clip["id"]))
    issues: list[dict[str, Any]] = []

    def add(
        severity: str,
        code: str,
        title: str,
        detail: str,
        start: float | None = None,
        end: float | None = None,
        clip_ids: list[int] | None = None,
    ) -> None:
        issues.append({
            "severity": severity,
            "code": code,
            "title": title,
            "detail": detail,
            "start_seconds": None if start is None else round(start, 3),
            "end_seconds": None if end is None else round(end, 3),
            "clip_ids": clip_ids or [],
        })

    peak = metrics.get("true_peak_dbfs")
    if peak is None:
        add("error", "no_signal", "No measurable audio", "The rendered mix contains no measurable programme signal.")
    elif peak > 0:
        add("error", "clipping", "True-peak clipping", f"The mix reaches +{peak:.2f} dBTP. Reduce master or clip gain before export.")
    elif peak > -1:
        add("warning", "low_headroom", "Low true-peak headroom", f"The mix peaks at {peak:.2f} dBTP. Leave at least 1 dB of true-peak headroom.")

    integrated = metrics.get("integrated_lufs")
    target = float(payload["project"]["target_lufs"])
    if integrated is not None:
        difference = target - integrated
        if abs(difference) >= 3:
            direction = "below" if difference > 0 else "above"
            add(
                "warning",
                "loudness_target",
                "Loudness misses target",
                f"Integrated loudness is {integrated:.1f} LUFS, {abs(difference):.1f} LU {direction} the {target:.1f} LUFS target.",
            )
        elif abs(difference) >= 1:
            add(
                "info",
                "loudness_target",
                "Loudness target adjustment",
                f"Integrated loudness is {integrated:.1f} LUFS; a {difference:+.1f} dB master adjustment reaches the {target:.1f} LUFS target.",
            )

    for interval in silence_intervals[:8]:
        add(
            "warning",
            "silence",
            "Extended silence",
            f"The rendered mix is effectively silent for {interval['duration_seconds']:.1f} seconds.",
            interval["start_seconds"],
            interval["end_seconds"],
        )

    for index, left in enumerate(clips):
        left_end = float(left["start_seconds"]) + float(left["duration_seconds"])
        for right in clips[index + 1:]:
            right_start = float(right["start_seconds"])
            start, end, overlap = _overlap(left, right)
            ids = [int(left["id"]), int(right["id"])]
            names = f"{left['title']} and {right['title']}"
            if overlap >= 1 and left["clip_kind"] == right["clip_kind"] == "vocals":
                add(
                    "warning", "vocal_collision", "Overlapping isolated vocals",
                    f"{names} contain isolated vocal clips playing together for {overlap:.1f} seconds.",
                    start, end, ids,
                )
            bass_capable = left["clip_kind"] in {"song", "bass"} and right["clip_kind"] in {"song", "bass"}
            bass_open = float(left["highpass_hz"]) < 90 and float(right["highpass_hz"]) < 90
            if overlap >= 4 and bass_capable and bass_open:
                add(
                    "warning", "bass_masking", "Possible bass masking",
                    f"{names} overlap for {overlap:.1f} seconds with both low ends open. High-pass one clip or isolate its bass stem.",
                    start, end, ids,
                )
            boundary_gap = right_start - left_end
            if (
                -0.1 <= boundary_gap <= 0.15
                and float(left["fade_out_seconds"]) < 0.05
                and float(right["fade_in_seconds"]) < 0.05
            ):
                add(
                    "warning", "abrupt_transition", "Abrupt clip boundary",
                    f"{left['title']} hands off to {right['title']} without a fade or overlap.",
                    max(0.0, left_end - 0.1), right_start + 0.1, ids,
                )

    priority = {"error": 0, "warning": 1, "info": 2}
    return sorted(
        issues,
        key=lambda issue: (
            priority.get(issue["severity"], 3),
            issue["start_seconds"] is None,
            issue["start_seconds"] or 0,
            issue["code"],
        ),
    )


def load_latest_project_audit(database: Database, project_id: int) -> dict[str, Any] | None:
    database.initialize()
    payload = load_project(database, int(project_id))
    status = render_status(database, [int(clip["id"]) for clip in _active_clips(payload)])
    current_signature = project_mix_signature(payload, status["renders"])
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM project_audits WHERE project_id = ? ORDER BY id DESC LIMIT 1",
            (int(project_id),),
        ).fetchone()
    if row is None:
        return None
    try:
        report = json.loads(row["report_json"])
    except json.JSONDecodeError as error:
        raise RuntimeError("The saved Smart Render report is unreadable.") from error
    report.update({
        "audit_id": int(row["id"]),
        "project_signature": str(row["project_signature"]),
        "fresh": str(row["project_signature"]) == current_signature,
        "created_at": str(row["created_at"]),
    })
    return report


def list_project_exports(database: Database, project_id: int) -> list[dict[str, Any]]:
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM project_exports WHERE project_id = ? ORDER BY id DESC",
            (int(project_id),),
        ).fetchall()
    return [{
        **dict(row),
        "path": str(row["destination_path"]),
        "sample_rate": OUTPUT_SAMPLE_RATE,
        "exists": Path(row["destination_path"]).is_file(),
    } for row in rows]


def audit_project_mixdown(database: Database, project_id: int) -> dict[str, Any]:
    database.initialize()
    payload = load_project(database, int(project_id))
    active = _active_clips(payload)
    if not active:
        raise ValueError("The project has no audible clips to analyse.")
    status = render_status(database, [int(clip["id"]) for clip in active])
    prepared_paths = {int(item["clip_id"]): str(item["path"]) for item in status["renders"]}
    missing = [int(clip["id"]) for clip in active if int(clip["id"]) not in prepared_paths]
    if missing:
        raise ValueError("Every audible clip must finish preparing before Smart Render can run.")
    runtime = _ffmpeg_runtime()
    if runtime is None:
        raise RuntimeError("FFmpeg is not installed, so Smart Render cannot analyse the project.")
    executable = str(runtime["path"])
    duration = max(float(clip["start_seconds"]) + float(clip["duration_seconds"]) for clip in active)
    with tempfile.TemporaryDirectory(prefix="decksmith-smart-render-") as temporary:
        mix_path = Path(temporary) / "analysis-mix.wav"
        _run_mixdown(build_mixdown_command(executable, payload, prepared_paths, mix_path, "wav"))
        target = float(payload["project"]["target_lufs"])
        loudness_output = _run_analysis([
            executable, "-nostdin", "-hide_banner", "-nostats", "-i", str(mix_path),
            "-af", f"loudnorm=I={target:.1f}:TP=-1:LRA=11:print_format=json",
            "-f", "null", "-",
        ])
        silence_output = _run_analysis([
            executable, "-nostdin", "-hide_banner", "-nostats", "-i", str(mix_path),
            "-af", "silencedetect=noise=-50dB:d=1", "-f", "null", "-",
        ])
    metrics = parse_loudnorm_measurement(loudness_output)
    silences = parse_silence_intervals(silence_output, duration)
    integrated = metrics["integrated_lufs"]
    current_gain = float(payload["project"]["master_gain_db"])
    adjustment = None if integrated is None else round(target - integrated, 2)
    recommended_gain = None if adjustment is None else round(
        max(-24.0, min(12.0, current_gain + adjustment)), 2
    )
    metrics.update({
        "target_lufs": target,
        "gain_to_target_db": adjustment,
        "recommended_master_gain_db": recommended_gain,
    })
    issues = build_smart_render_issues(payload, metrics, silences)
    counts = {
        severity: sum(issue["severity"] == severity for issue in issues)
        for severity in ("error", "warning", "info")
    }
    report_status = "blocked" if counts["error"] else "warning" if counts["warning"] else "ready"
    signature = project_mix_signature(payload, status["renders"])
    report = {
        "project_id": int(project_id),
        "status": report_status,
        "analyzed_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round(duration, 3),
        "clip_count": len(active),
        "metrics": metrics,
        "silence_intervals": silences,
        "issues": issues,
        "counts": counts,
        "project_signature": signature,
        "fresh": True,
    }
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO project_audits(project_id, project_signature, status, report_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                int(project_id), signature, report_status,
                json.dumps(report, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        report["audit_id"] = int(cursor.lastrowid)
    return report


def export_project_mixdown(
    database: Database,
    project_id: int,
    destination: str | Path,
    audio_format: str,
    *,
    loudness_targeted: bool = False,
    runner: MixdownRunner | None = None,
    executable: str | None = None,
) -> dict[str, Any]:
    database.initialize()
    normalized_format = str(audio_format).strip().casefold()
    if normalized_format not in {"wav", "mp3"}:
        raise ValueError("Audio export format must be WAV or MP3.")
    output = Path(destination).expanduser().resolve()
    expected_suffix = f".{normalized_format}"
    if output.suffix.casefold() != expected_suffix:
        output = output.with_suffix(expected_suffix)
    if not output.parent.is_dir():
        raise ValueError("Choose an existing folder for the audio export.")
    payload = load_project(database, int(project_id))
    active = _active_clips(payload)
    status = render_status(database, [int(clip["id"]) for clip in active])
    prepared_paths = {
        int(item["clip_id"]): str(item["path"]) for item in status["renders"]
    }
    runtime = _ffmpeg_runtime()
    if executable is None and runtime is None:
        raise RuntimeError("FFmpeg is not installed, so the project cannot be exported.")
    active_executable = executable or str(runtime["path"])
    latest_audit = load_latest_project_audit(database, int(project_id))
    if loudness_targeted and (latest_audit is None or not latest_audit["fresh"]):
        raise ValueError("Run Smart Render after the latest project change before creating a loudness-targeted export.")
    temporary = output.with_name(
        f".{output.stem}.decksmith-{uuid.uuid4().hex[:10]}{output.suffix}"
    )
    source_temporary = output.with_name(
        f".{output.stem}.decksmith-source-{uuid.uuid4().hex[:10]}.wav"
    ) if loudness_targeted else None
    export_metrics: dict[str, Any] = (
        latest_audit["metrics"] if latest_audit and latest_audit["fresh"] else {}
    )
    try:
        if loudness_targeted:
            metrics = latest_audit["metrics"]
            required = (
                "integrated_lufs", "true_peak_dbfs", "loudness_range_lu",
                "threshold_lufs", "normalization_offset_db",
            )
            if any(metrics.get(field) is None for field in required):
                raise ValueError("Smart Render did not measure enough signal for loudness targeting.")
            (runner or _run_mixdown)(build_mixdown_command(
                active_executable, payload, prepared_paths, source_temporary, "wav"
            ))
            target = float(payload["project"]["target_lufs"])
            loudnorm = (
                f"loudnorm=I={target:.1f}:TP=-1:LRA=11:"
                f"measured_I={float(metrics['integrated_lufs']):.3f}:"
                f"measured_TP={float(metrics['true_peak_dbfs']):.3f}:"
                f"measured_LRA={float(metrics['loudness_range_lu']):.3f}:"
                f"measured_thresh={float(metrics['threshold_lufs']):.3f}:"
                f"offset={float(metrics['normalization_offset_db']):.3f}:"
                "linear=true:print_format=summary"
            )
            normalize_command = [
                active_executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source_temporary), "-af", loudnorm,
                "-ar", str(OUTPUT_SAMPLE_RATE), "-ac", "2",
            ]
            if normalized_format == "wav":
                normalize_command.extend(["-c:a", "pcm_s24le"])
            else:
                normalize_command.extend(["-c:a", "libmp3lame", "-q:a", "2"])
            normalize_command.append(str(temporary))
            _run_mixdown(normalize_command)
        else:
            (runner or _run_mixdown)(build_mixdown_command(
                active_executable, payload, prepared_paths, temporary, normalized_format
            ))
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RuntimeError("The exported mixdown is missing or empty.")
        if loudness_targeted:
            export_metrics = parse_loudnorm_measurement(_run_analysis([
                active_executable, "-nostdin", "-hide_banner", "-nostats",
                "-i", str(temporary),
                "-af", f"loudnorm=I={float(payload['project']['target_lufs']):.1f}:TP=-1:LRA=11:print_format=json",
                "-f", "null", "-",
            ]))
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
        if source_temporary is not None:
            source_temporary.unlink(missing_ok=True)
    signature = project_mix_signature(payload, status["renders"])
    digest = hashlib.sha256()
    with output.open("rb") as audio:
        for chunk in iter(lambda: audio.read(1024 * 1024), b""):
            digest.update(chunk)
    measured = export_metrics
    duration = max(
        float(clip["start_seconds"]) + float(clip["duration_seconds"]) for clip in active
    )
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO project_exports(
                project_id, audit_id, project_signature, format, export_mode, target_lufs,
                destination_path, file_size, duration_seconds, clip_count, sha256,
                integrated_lufs, true_peak_dbfs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(project_id), latest_audit.get("audit_id") if latest_audit and latest_audit["fresh"] else None,
                signature, normalized_format,
                "loudness_targeted" if loudness_targeted else "original",
                float(payload["project"]["target_lufs"]) if loudness_targeted else None,
                str(output), output.stat().st_size, duration, len(active), digest.hexdigest(),
                measured.get("integrated_lufs"), measured.get("true_peak_dbfs"),
            ),
        )
        export_id = int(cursor.lastrowid)
        created_at = connection.execute(
            "SELECT created_at FROM project_exports WHERE id = ?", (export_id,)
        ).fetchone()["created_at"]
    return {
        "id": export_id,
        "project_id": int(project_id),
        "format": normalized_format,
        "export_mode": "loudness_targeted" if loudness_targeted else "original",
        "target_lufs": float(payload["project"]["target_lufs"]) if loudness_targeted else None,
        "path": str(output),
        "destination_path": str(output),
        "file_size": output.stat().st_size,
        "duration_seconds": duration,
        "clip_count": len(active),
        "sample_rate": OUTPUT_SAMPLE_RATE,
        "sha256": digest.hexdigest(),
        "integrated_lufs": measured.get("integrated_lufs"),
        "true_peak_dbfs": measured.get("true_peak_dbfs"),
        "created_at": created_at,
        "exists": True,
    }
