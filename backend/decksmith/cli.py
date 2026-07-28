from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .analysis import analysis_summary, analyze_tracks
from .assistant import (
    compatible_tracks,
    create_mashup_draft,
    create_project_from_mashup_draft,
    create_setlist_draft,
    list_drafts,
)
from .artwork import extract_artwork
from .cache import cache_status, prune_cache
from .database import Database
from .consolidation import bounce_timeline_clip, freeze_timeline_clip, unfreeze_timeline_clip
from .library import (
    find_duplicates,
    library_issues,
    list_roots,
    list_tracks,
    record_playback,
    update_track,
    update_tracks,
)
from .mixdown import (
    audit_project_mixdown,
    export_project_mixdown,
    list_project_exports,
    load_latest_project_audit,
)
from .projects import (
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
    trim_timeline_clips_to_selection,
    shift_timeline_group_channels,
    undo_project,
    ungroup_timeline_clips,
    update_project_marker,
    update_project,
    update_project_selection,
    update_clip_stem_state,
    update_timeline_clip,
)
from .rendering import render_capability, render_clip, render_status
from .scanner import scan_library
from .serato import crate_track_ids, discover_serato_libraries, list_crates, sync_serato_crates
from .smart_playlists import (
    create_smart_playlist,
    delete_smart_playlist,
    list_smart_playlists,
    smart_playlist_track_ids,
)
from .stems import separate_track_stems, stem_capability, stem_status
from .transfer import (
    capture_transfer_snapshot,
    create_rekordbox_package,
    latest_transfer_plan,
    list_transfer_exports,
    verify_transfer_package,
)
from .waveform import generate_waveform


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decksmith", description="Decksmith library tools")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path.home() / ".decksmith" / "decksmith.db",
        help="SQLite database location",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan", help="Scan a music folder without modifying it")
    scan.add_argument("folder", type=Path)
    scan.add_argument("--progress", action="store_true", help="Emit newline-delimited progress events")
    scan.add_argument("--cancel-file", type=Path, help="Cancel when this file appears")
    tracks = commands.add_parser("tracks", help="Return indexed tracks as JSON")
    tracks.add_argument("--include-missing", action="store_true")
    commands.add_parser("roots", help="Return configured music folders as JSON")
    commands.add_parser("issues", help="Return missing files and metadata errors as JSON")
    commands.add_parser("duplicates", help="Find byte-identical duplicate audio files")
    update = commands.add_parser("update-track", help="Update user-managed track metadata")
    update.add_argument("track_id", type=int)
    update.add_argument("--rating", type=int)
    update.add_argument("--tags")
    update.add_argument("--color-tag")
    update.add_argument("--mood")
    update.add_argument("--comment")
    bulk = commands.add_parser("bulk-update", help="Update user metadata for multiple tracks")
    bulk.add_argument("--track-id", type=int, action="append", required=True)
    bulk.add_argument("--rating", type=int)
    bulk.add_argument("--tags")
    bulk.add_argument("--color-tag")
    bulk.add_argument("--mood")
    bulk.add_argument("--tag-mode", choices=("add", "replace"), default="add")
    playback = commands.add_parser("record-playback", help="Record a local preview play")
    playback.add_argument("track_id", type=int)
    commands.add_parser("serato-discover", help="Locate Serato libraries without modifying them")
    commands.add_parser("serato-sync", help="Read Serato crates into Decksmith")
    commands.add_parser("crates", help="Return imported Serato crates")
    crate_tracks = commands.add_parser("crate-tracks", help="Return matched track ids in crate order")
    crate_tracks.add_argument("crate_id", type=int)
    waveform = commands.add_parser("waveform", help="Generate or return a cached waveform image")
    waveform.add_argument("track_id", type=int)
    waveform.add_argument("cache_dir", type=Path)
    artwork = commands.add_parser("artwork", help="Extract or return cached embedded artwork")
    artwork.add_argument("track_id", type=int)
    artwork.add_argument("cache_dir", type=Path)
    analyse = commands.add_parser("analyse", help="Analyse BPM, key and signal energy")
    analyse.add_argument("--track-id", type=int, action="append")
    analyse.add_argument("--force", action="store_true")
    analyse.add_argument("--progress", action="store_true")
    analyse.add_argument("--cancel-file", type=Path)
    commands.add_parser("analysis-summary", help="Return persistent audio-analysis status counts")
    commands.add_parser("smart-playlists", help="Return persistent smart playlists")
    smart_create = commands.add_parser("smart-create", help="Create a smart playlist")
    smart_create.add_argument("name")
    smart_create.add_argument("rules")
    smart_delete = commands.add_parser("smart-delete", help="Delete a smart playlist")
    smart_delete.add_argument("playlist_id", type=int)
    smart_tracks = commands.add_parser("smart-tracks", help="Return matching smart-playlist track ids")
    smart_tracks.add_argument("playlist_id", type=int)
    commands.add_parser("transfer-snapshot", help="Snapshot Serato state and compare it with the previous snapshot")
    commands.add_parser("transfer-plan", help="Return the latest Serato transfer plan")
    transfer_export = commands.add_parser("transfer-export", help="Create a new Rekordbox XML transfer package")
    transfer_export.add_argument("destination", type=Path)
    transfer_export.add_argument("--crate-id", type=int, action="append")
    commands.add_parser("transfer-history", help="Return completed transfer packages")
    transfer_verify = commands.add_parser("transfer-verify", help="Verify a recorded transfer package and its manifest")
    transfer_verify.add_argument("destination", type=Path)
    commands.add_parser("projects", help="Return arrangement projects")
    project_create = commands.add_parser("project-create", help="Create an arrangement project")
    project_create.add_argument("name")
    project_create.add_argument("--tempo", type=float, default=120)
    project_load = commands.add_parser("project-load", help="Load an arrangement project")
    project_load.add_argument("project_id", type=int)
    project_update = commands.add_parser("project-update", help="Update arrangement project settings")
    project_update.add_argument("project_id", type=int)
    project_update.add_argument("--name")
    project_update.add_argument("--tempo", type=float)
    project_update.add_argument("--snap-enabled", type=int, choices=(0, 1))
    project_update.add_argument("--snap-beats", type=float)
    project_update.add_argument("--master-gain", type=float)
    project_update.add_argument("--master-limiter", type=int, choices=(0, 1))
    project_update.add_argument("--musical-key")
    project_update.add_argument("--master-low-eq", type=float)
    project_update.add_argument("--master-mid-eq", type=float)
    project_update.add_argument("--master-high-eq", type=float)
    project_update.add_argument("--master-width", type=float)
    project_update.add_argument("--target-lufs", type=float)
    project_selection = commands.add_parser("project-selection", help="Update timeline selection")
    project_selection.add_argument("project_id", type=int)
    project_selection.add_argument("--start", type=float)
    project_selection.add_argument("--end", type=float)
    project_selection.add_argument("--loop-enabled", type=int, choices=(0, 1), default=0)
    project_selection.add_argument("--clear", action="store_true")
    project_undo = commands.add_parser("project-undo", help="Undo the latest project edit")
    project_undo.add_argument("project_id", type=int)
    project_redo = commands.add_parser("project-redo", help="Redo the latest undone project edit")
    project_redo.add_argument("project_id", type=int)
    project_add = commands.add_parser("project-add-track", help="Add a library track to an arrangement")
    project_add.add_argument("project_id", type=int)
    project_add.add_argument("track_id", type=int)
    project_add.add_argument("--channel", type=int, required=True)
    project_add.add_argument("--start", type=float)
    stem_add = commands.add_parser("project-add-stem", help="Add a cached stem as an editable arrangement clip")
    stem_add.add_argument("source_clip_id", type=int)
    stem_add.add_argument("stem_kind", choices=("vocals", "drums", "bass", "other"))
    stem_add.add_argument("--channel", type=int, required=True)
    stem_add.add_argument("--start", type=float)
    clip_source = commands.add_parser("project-clip-source", help="Switch a clip between its song and stem sources")
    clip_source.add_argument("clip_id", type=int)
    clip_source.add_argument("clip_kind", choices=("song", "vocals", "drums", "bass", "other"))
    stem_state = commands.add_parser("project-stem-state", help="Mute or solo a separated stem lane")
    stem_state.add_argument("clip_id", type=int)
    stem_state.add_argument("stem_kind", choices=("vocals", "drums", "bass", "other"))
    stem_state.add_argument("--muted", type=int, choices=(0, 1))
    stem_state.add_argument("--solo", type=int, choices=(0, 1))
    clip_update = commands.add_parser("project-clip-update", help="Update a timeline clip")
    clip_update.add_argument("clip_id", type=int)
    clip_update.add_argument("changes")
    clip_resize = commands.add_parser("project-clip-resize", help="Resize a timeline clip edge")
    clip_resize.add_argument("clip_id", type=int)
    clip_resize.add_argument("edge", choices=("start", "end"))
    clip_resize.add_argument("boundary", type=float)
    clip_split = commands.add_parser("project-clip-split", help="Split a timeline clip")
    clip_split.add_argument("clip_id", type=int)
    clip_split.add_argument("offset", type=float)
    clip_duplicate = commands.add_parser("project-clip-duplicate", help="Duplicate a timeline clip")
    clip_duplicate.add_argument("clip_id", type=int)
    clip_quantize = commands.add_parser("project-clip-quantize", help="Quantize a timeline clip")
    clip_quantize.add_argument("clip_id", type=int)
    clip_crossfade = commands.add_parser("project-clip-crossfade", help="Crossfade overlapping clips")
    clip_crossfade.add_argument("clip_id", type=int)
    clip_crossfade.add_argument("target_clip_id", type=int)
    clip_group = commands.add_parser("project-clip-group", help="Group timeline clips")
    clip_group.add_argument("clip_ids")
    clip_ungroup = commands.add_parser("project-clip-ungroup", help="Remove a timeline clip group")
    clip_ungroup.add_argument("project_id", type=int)
    clip_ungroup.add_argument("group_id", type=int)
    clip_batch = commands.add_parser("project-clip-batch", help="Batch edit timeline clips")
    clip_batch.add_argument("clip_ids")
    clip_batch.add_argument("changes")
    group_shift = commands.add_parser("project-group-shift", help="Shift a group between channels")
    group_shift.add_argument("project_id", type=int)
    group_shift.add_argument("group_id", type=int)
    group_shift.add_argument("delta", type=int, choices=(-1, 1))
    clip_delete = commands.add_parser("project-clip-delete", help="Delete selected timeline clips")
    clip_delete.add_argument("clip_ids")
    clip_trim_selection = commands.add_parser("project-clip-trim-selection", help="Trim clips to a timeline selection")
    clip_trim_selection.add_argument("clip_ids")
    clip_trim_selection.add_argument("start", type=float)
    clip_trim_selection.add_argument("end", type=float)
    marker_create = commands.add_parser("project-marker-create", help="Create a marker or section")
    marker_create.add_argument("project_id", type=int)
    marker_create.add_argument("--kind", choices=("marker", "section"), required=True)
    marker_create.add_argument("--name", required=True)
    marker_create.add_argument("--start", type=float, required=True)
    marker_create.add_argument("--end", type=float)
    marker_create.add_argument("--color", default="violet")
    marker_update = commands.add_parser("project-marker-update", help="Update a marker or section")
    marker_update.add_argument("marker_id", type=int)
    marker_update.add_argument("changes")
    marker_delete = commands.add_parser("project-marker-delete", help="Delete a marker or section")
    marker_delete.add_argument("marker_id", type=int)
    project_history = commands.add_parser("project-history", help="Return arrangement project history")
    project_history.add_argument("project_id", type=int)
    project_export = commands.add_parser("project-export-audio", help="Export a project mixdown")
    project_export.add_argument("project_id", type=int)
    project_export.add_argument("destination", type=Path)
    project_export.add_argument("--format", choices=("wav", "mp3"), required=True)
    project_export.add_argument("--loudness-targeted", action="store_true")
    project_audit = commands.add_parser("project-audit", help="Run loudness and Smart Render checks")
    project_audit.add_argument("project_id", type=int)
    project_audit_latest = commands.add_parser("project-audit-latest", help="Return the latest Smart Render report")
    project_audit_latest.add_argument("project_id", type=int)
    project_export_history = commands.add_parser("project-export-history", help="Return project audio exports")
    project_export_history.add_argument("project_id", type=int)
    commands.add_parser("stems-capability", help="Report local stem-engine availability")
    stems_status = commands.add_parser("stems-status", help="Return persistent stem jobs and cache")
    stems_status.add_argument("--track-id", type=int, action="append")
    stems_status.add_argument("--model", default="htdemucs")
    stems_separate = commands.add_parser("stems-separate", help="Separate and cache four local stems")
    stems_separate.add_argument("track_id", type=int)
    stems_separate.add_argument("cache_dir", type=Path)
    stems_separate.add_argument("--model", default="htdemucs")
    stems_separate.add_argument("--force", action="store_true")
    stems_separate.add_argument("--progress", action="store_true")
    stems_separate.add_argument("--cancel-file", type=Path)
    commands.add_parser("render-capability", help="Report local clip-rendering availability")
    renders_status = commands.add_parser("render-status", help="Return clip render jobs and cache")
    renders_status.add_argument("--clip-id", type=int, action="append")
    render = commands.add_parser("render-clip", help="Render and cache one processed timeline clip")
    render.add_argument("clip_id", type=int)
    render.add_argument("cache_dir", type=Path)
    render.add_argument("--force", action="store_true")
    render.add_argument("--progress", action="store_true")
    render.add_argument("--cancel-file", type=Path)
    freeze_clip = commands.add_parser("project-clip-freeze", help="Freeze a prepared clip source")
    freeze_clip.add_argument("clip_id", type=int)
    freeze_clip.add_argument("destination_dir", type=Path)
    unfreeze_clip = commands.add_parser("project-clip-unfreeze", help="Restore a frozen clip source")
    unfreeze_clip.add_argument("clip_id", type=int)
    bounce_clip = commands.add_parser("project-clip-bounce", help="Create a consolidated clip copy")
    bounce_clip.add_argument("clip_id", type=int)
    bounce_clip.add_argument("destination_dir", type=Path)
    assistant_matches = commands.add_parser("assistant-matches", help="Explain local compatibility matches")
    assistant_matches.add_argument("track_id", type=int)
    assistant_matches.add_argument("--limit", type=int, default=12)
    assistant_drafts = commands.add_parser("assistant-drafts", help="List saved assistant drafts")
    mashup_draft = commands.add_parser("assistant-mashup", help="Create a saved mashup draft")
    mashup_draft.add_argument("anchor_track_id", type=int)
    mashup_draft.add_argument("partner_track_id", type=int)
    mashup_draft.add_argument("--name", default="")
    setlist_draft = commands.add_parser("assistant-setlist", help="Build a local-library setlist draft")
    setlist_draft.add_argument("name")
    setlist_draft.add_argument("duration_minutes", type=int)
    setlist_draft.add_argument("--genre", default="")
    setlist_draft.add_argument("--energy-curve", default="rise", choices=("rise", "steady", "wave"))
    setlist_draft.add_argument("--must-play", type=int, action="append")
    setlist_draft.add_argument("--avoid-tag", action="append")
    draft_project = commands.add_parser("assistant-draft-project", help="Turn a mashup draft into an arrangement")
    draft_project.add_argument("draft_id", type=int)
    cache_info = commands.add_parser("cache-status", help="Report app-owned derivative cache usage")
    cache_info.add_argument("cache_dir", type=Path)
    cache_prune = commands.add_parser("cache-prune", help="Remove unreferenced app-owned cache files")
    cache_prune.add_argument("cache_dir", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database = Database(args.database)
    if args.command == "scan":
        def progress(result, path):
            if args.progress:
                print(json.dumps({
                    "event": "progress",
                    "data": asdict(result),
                    "current_file": path.name,
                }), flush=True)

        result = scan_library(
            database,
            args.folder,
            progress=progress if args.progress else None,
            should_cancel=(lambda: args.cancel_file.exists()) if args.cancel_file else None,
        )
        if args.progress:
            print(json.dumps({"event": "complete", "data": asdict(result)}), flush=True)
        else:
            print(json.dumps(asdict(result), indent=2))
    elif args.command == "tracks":
        print(json.dumps(list_tracks(database, include_missing=args.include_missing)))
    elif args.command == "roots":
        print(json.dumps(list_roots(database)))
    elif args.command == "issues":
        print(json.dumps(library_issues(database)))
    elif args.command == "duplicates":
        print(json.dumps(find_duplicates(database)))
    elif args.command == "update-track":
        tags = args.tags.split(",") if args.tags is not None else None
        print(json.dumps(update_track(
            database, args.track_id, args.rating, tags, args.color_tag, args.mood, args.comment
        )))
    elif args.command == "bulk-update":
        tags = args.tags.split(",") if args.tags is not None else None
        print(json.dumps({"updated": update_tracks(
            database, args.track_id, args.rating, tags, args.color_tag, args.mood,
            None, args.tag_mode
        )}))
    elif args.command == "record-playback":
        print(json.dumps(record_playback(database, args.track_id)))
    elif args.command == "serato-discover":
        print(json.dumps([str(path) for path in discover_serato_libraries()]))
    elif args.command == "serato-sync":
        print(json.dumps(sync_serato_crates(database)))
    elif args.command == "crates":
        print(json.dumps(list_crates(database)))
    elif args.command == "crate-tracks":
        print(json.dumps(crate_track_ids(database, args.crate_id)))
    elif args.command == "waveform":
        print(json.dumps({"path": str(generate_waveform(database, args.track_id, args.cache_dir))}))
    elif args.command == "artwork":
        path = extract_artwork(database, args.track_id, args.cache_dir)
        print(json.dumps({"path": str(path) if path else None}))
    elif args.command == "analyse":
        def analysis_progress(result):
            if args.progress:
                print(json.dumps({
                    "event": "progress",
                    "data": asdict(result),
                }), flush=True)

        result = analyze_tracks(
            database,
            args.track_id,
            force=args.force,
            progress=analysis_progress if args.progress else None,
            should_cancel=(lambda: args.cancel_file.exists()) if args.cancel_file else None,
        )
        if args.progress:
            print(json.dumps({"event": "complete", "data": asdict(result)}), flush=True)
        else:
            print(json.dumps(asdict(result)))
    elif args.command == "analysis-summary":
        print(json.dumps(analysis_summary(database)))
    elif args.command == "stems-capability":
        print(json.dumps(stem_capability()))
    elif args.command == "stems-status":
        print(json.dumps(stem_status(database, args.track_id, args.model)))
    elif args.command == "stems-separate":
        def stem_progress(result):
            if args.progress:
                print(json.dumps({
                    "event": "progress" if result.status in {"queued", "running"} else "complete",
                    "data": result.to_dict(),
                }), flush=True)

        result = separate_track_stems(
            database,
            args.track_id,
            args.cache_dir,
            model=args.model,
            force=args.force,
            progress=stem_progress if args.progress else None,
            should_cancel=(lambda: args.cancel_file.exists()) if args.cancel_file else None,
        )
        if not args.progress:
            print(json.dumps(result.to_dict()))
    elif args.command == "render-capability":
        print(json.dumps(render_capability()))
    elif args.command == "render-status":
        print(json.dumps(render_status(database, args.clip_id)))
    elif args.command == "render-clip":
        def render_progress(result):
            if args.progress:
                print(json.dumps({
                    "event": "progress" if result.status in {"queued", "running"} else "complete",
                    "data": result.to_dict(),
                }), flush=True)

        result = render_clip(
            database,
            args.clip_id,
            args.cache_dir,
            force=args.force,
            progress=render_progress if args.progress else None,
            should_cancel=(lambda: args.cancel_file.exists()) if args.cancel_file else None,
        )
        if not args.progress:
            print(json.dumps(result.to_dict()))
    elif args.command == "smart-playlists":
        print(json.dumps(list_smart_playlists(database)))
    elif args.command == "smart-create":
        print(json.dumps(create_smart_playlist(database, args.name, json.loads(args.rules))))
    elif args.command == "smart-delete":
        print(json.dumps({"deleted": delete_smart_playlist(database, args.playlist_id)}))
    elif args.command == "smart-tracks":
        print(json.dumps(smart_playlist_track_ids(database, args.playlist_id)))
    elif args.command == "transfer-snapshot":
        print(json.dumps(capture_transfer_snapshot(database)))
    elif args.command == "transfer-plan":
        print(json.dumps(latest_transfer_plan(database)))
    elif args.command == "transfer-export":
        print(json.dumps(create_rekordbox_package(database, args.destination, args.crate_id)))
    elif args.command == "transfer-history":
        print(json.dumps(list_transfer_exports(database)))
    elif args.command == "transfer-verify":
        print(json.dumps(verify_transfer_package(database, args.destination)))
    elif args.command == "projects":
        print(json.dumps(list_projects(database)))
    elif args.command == "project-create":
        print(json.dumps(create_project(database, args.name, args.tempo)))
    elif args.command == "project-load":
        print(json.dumps(load_project(database, args.project_id)))
    elif args.command == "project-update":
        print(json.dumps(update_project(
            database,
            args.project_id,
            args.name,
            args.tempo,
            None if args.snap_enabled is None else bool(args.snap_enabled),
            args.snap_beats,
            args.master_gain,
            None if args.master_limiter is None else bool(args.master_limiter),
            args.musical_key,
            args.master_low_eq,
            args.master_mid_eq,
            args.master_high_eq,
            args.master_width,
            args.target_lufs,
        )))
    elif args.command == "project-add-track":
        print(json.dumps(add_track_to_project(
            database, args.project_id, args.track_id, args.channel, args.start
        )))
    elif args.command == "project-add-stem":
        print(json.dumps(add_stem_to_project(
            database, args.source_clip_id, args.stem_kind, args.channel, args.start
        )))
    elif args.command == "project-clip-freeze":
        print(json.dumps(freeze_timeline_clip(
            database, args.clip_id, args.destination_dir
        )))
    elif args.command == "project-clip-unfreeze":
        print(json.dumps(unfreeze_timeline_clip(database, args.clip_id)))
    elif args.command == "project-clip-bounce":
        print(json.dumps(bounce_timeline_clip(
            database, args.clip_id, args.destination_dir
        )))
    elif args.command == "assistant-matches":
        print(json.dumps(compatible_tracks(database, args.track_id, args.limit)))
    elif args.command == "assistant-drafts":
        print(json.dumps(list_drafts(database)))
    elif args.command == "assistant-mashup":
        print(json.dumps(create_mashup_draft(
            database, args.anchor_track_id, args.partner_track_id, args.name
        )))
    elif args.command == "assistant-setlist":
        print(json.dumps(create_setlist_draft(
            database, args.name, args.duration_minutes, args.genre,
            args.energy_curve, args.must_play, args.avoid_tag,
        )))
    elif args.command == "assistant-draft-project":
        print(json.dumps(create_project_from_mashup_draft(database, args.draft_id)))
    elif args.command == "cache-status":
        print(json.dumps(cache_status(database, args.cache_dir)))
    elif args.command == "cache-prune":
        print(json.dumps(prune_cache(database, args.cache_dir)))
    elif args.command == "project-clip-source":
        print(json.dumps(set_timeline_clip_source(
            database, args.clip_id, args.clip_kind
        )))
    elif args.command == "project-stem-state":
        print(json.dumps(update_clip_stem_state(
            database,
            args.clip_id,
            args.stem_kind,
            muted=None if args.muted is None else bool(args.muted),
            solo=None if args.solo is None else bool(args.solo),
        )))
    elif args.command == "project-selection":
        print(json.dumps(update_project_selection(
            database,
            args.project_id,
            None if args.clear else args.start,
            None if args.clear else args.end,
            bool(args.loop_enabled),
        )))
    elif args.command == "project-undo":
        print(json.dumps(undo_project(database, args.project_id)))
    elif args.command == "project-redo":
        print(json.dumps(redo_project(database, args.project_id)))
    elif args.command == "project-clip-update":
        print(json.dumps(update_timeline_clip(database, args.clip_id, json.loads(args.changes))))
    elif args.command == "project-clip-resize":
        print(json.dumps(resize_timeline_clip(
            database, args.clip_id, args.edge, args.boundary
        )))
    elif args.command == "project-clip-split":
        print(json.dumps(split_timeline_clip(database, args.clip_id, args.offset)))
    elif args.command == "project-clip-duplicate":
        print(json.dumps(duplicate_timeline_clip(database, args.clip_id)))
    elif args.command == "project-clip-quantize":
        print(json.dumps(quantize_timeline_clip(database, args.clip_id)))
    elif args.command == "project-clip-crossfade":
        print(json.dumps(crossfade_timeline_clips(database, args.clip_id, args.target_clip_id)))
    elif args.command == "project-clip-group":
        print(json.dumps(group_timeline_clips(database, json.loads(args.clip_ids))))
    elif args.command == "project-clip-ungroup":
        print(json.dumps(ungroup_timeline_clips(database, args.project_id, args.group_id)))
    elif args.command == "project-clip-batch":
        print(json.dumps(batch_update_timeline_clips(
            database, json.loads(args.clip_ids), json.loads(args.changes)
        )))
    elif args.command == "project-group-shift":
        print(json.dumps(shift_timeline_group_channels(
            database, args.project_id, args.group_id, args.delta
        )))
    elif args.command == "project-clip-delete":
        print(json.dumps(delete_timeline_clips(database, json.loads(args.clip_ids))))
    elif args.command == "project-clip-trim-selection":
        print(json.dumps(trim_timeline_clips_to_selection(
            database, json.loads(args.clip_ids), args.start, args.end
        )))
    elif args.command == "project-marker-create":
        print(json.dumps(create_project_marker(
            database,
            args.project_id,
            args.kind,
            args.name,
            args.start,
            args.end,
            args.color,
        )))
    elif args.command == "project-marker-update":
        print(json.dumps(update_project_marker(database, args.marker_id, json.loads(args.changes))))
    elif args.command == "project-marker-delete":
        print(json.dumps(delete_project_marker(database, args.marker_id)))
    elif args.command == "project-history":
        print(json.dumps(list_project_history(database, args.project_id)))
    elif args.command == "project-export-audio":
        print(json.dumps(export_project_mixdown(
            database, args.project_id, args.destination, args.format,
            loudness_targeted=args.loudness_targeted,
        )))
    elif args.command == "project-audit":
        print(json.dumps(audit_project_mixdown(database, args.project_id)))
    elif args.command == "project-audit-latest":
        print(json.dumps(load_latest_project_audit(database, args.project_id)))
    elif args.command == "project-export-history":
        print(json.dumps(list_project_exports(database, args.project_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
