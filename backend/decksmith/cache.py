from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .database import Database


CACHE_CATEGORIES = ("renders", "stems", "consolidated", "waveforms", "artwork")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()] if root.is_dir() else []


def _size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


def _references(database: Database) -> dict[str, set[Path]]:
    with database.connect() as connection:
        render_rows = connection.execute("SELECT path FROM render_cache").fetchall()
        stem_rows = connection.execute("SELECT path FROM stem_cache").fetchall()
        consolidated_rows = connection.execute(
            "SELECT path FROM rendered_clip_sources"
        ).fetchall()
    renders: set[Path] = set()
    for row in render_rows:
        path = Path(row["path"]).expanduser().resolve()
        renders.add(path)
        renders.add(path.with_suffix(".waveform.png"))
    return {
        "renders": renders,
        "stems": {Path(row["path"]).expanduser().resolve() for row in stem_rows},
        "consolidated": {
            Path(row["path"]).expanduser().resolve() for row in consolidated_rows
        },
    }


def cache_status(database: Database, cache_directory: str | Path) -> dict[str, Any]:
    database.initialize()
    root = Path(cache_directory).expanduser().resolve()
    references = _references(database)
    categories: dict[str, dict[str, int]] = {}
    total = 0
    reclaimable = 0
    for name in CACHE_CATEGORIES:
        category_root = root / name
        files = _files(category_root)
        category_size = _size(files)
        known = references.get(name)
        orphaned = [] if known is None else [
            path for path in files
            if ".working" not in path.parts and path.resolve() not in known
        ]
        orphaned_size = _size(orphaned)
        categories[name] = {
            "bytes": category_size,
            "files": len(files),
            "reclaimable_bytes": orphaned_size,
            "reclaimable_files": len(orphaned),
        }
        total += category_size
        reclaimable += orphaned_size
    return {
        "root": str(root),
        "total_bytes": total,
        "reclaimable_bytes": reclaimable,
        "categories": categories,
    }


def prune_cache(database: Database, cache_directory: str | Path) -> dict[str, Any]:
    """Remove only unreferenced app-owned derivatives; projects and source media are untouched."""
    database.initialize()
    root = Path(cache_directory).expanduser().resolve()
    references = _references(database)
    removed_files = 0
    removed_bytes = 0
    for name in ("renders", "stems", "consolidated"):
        category_root = (root / name).resolve()
        if not category_root.is_dir() or not _inside(category_root, root):
            continue
        keep = references[name]
        for path in _files(category_root):
            resolved = path.resolve()
            if ".working" in path.parts or resolved in keep or not _inside(resolved, category_root):
                continue
            try:
                size = path.stat().st_size
                path.unlink()
                removed_files += 1
                removed_bytes += size
            except OSError:
                continue
        for directory in sorted(
            (path for path in category_root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            if directory.name == ".working":
                continue
            try:
                directory.rmdir()
            except OSError:
                pass
    with database.connect() as connection:
        for table in ("render_cache", "render_jobs"):
            connection.execute(
                f"DELETE FROM {table} WHERE clip_id NOT IN (SELECT id FROM timeline_clips)"
            )
        connection.execute(
            "DELETE FROM render_cache WHERE path IS NULL OR path = ''"
        )
    result = cache_status(database, root)
    result["removed_files"] = removed_files
    result["removed_bytes"] = removed_bytes
    return result
