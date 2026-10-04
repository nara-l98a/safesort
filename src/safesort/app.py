"""Safe, preview-first file organizer with an undo journal."""
from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
import json
import os
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HISTORY_NAME = ".safesort-history.jsonl"
IGNORED_DIRS = {".git", ".hg", ".svn", ".venv", "node_modules", "__pycache__"}

CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff", ".heic"},
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".tex"},
    "Spreadsheets": {".csv", ".tsv", ".xls", ".xlsx", ".ods"},
    "Presentations": {".ppt", ".pptx", ".odp", ".key"},
    "Archives": {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"},
    "Video": {".mp4", ".mov", ".mkv", ".avi", ".webm", ".mpeg"},
    "Code": {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".java", ".c", ".h", ".cpp", ".go", ".rs", ".sh", ".json", ".yml", ".yaml", ".toml"},
}


@dataclass(frozen=True)
class Move:
    source: Path
    destination: Path


def category_for(path: Path, overrides: dict[str, str] | None = None) -> str:
    ext = path.suffix.lower()
    if overrides and ext in overrides:
        return overrides[ext]
    for category, extensions in CATEGORIES.items():
        if ext in extensions:
            return category
    return "Other" if ext else "No Extension"


def _free_destination(path: Path, reserved: set[Path]) -> Path:
    if path not in reserved and not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    index = 1
    while True:
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if candidate not in reserved and not candidate.exists():
            return candidate
        index += 1


def parse_category_override(value: str) -> tuple[str, str]:
    """Parse EXTENSION=CATEGORY while preventing category path traversal."""
    extension, separator, category = value.partition("=")
    extension, category = extension.strip().lower(), category.strip()
    if not separator or not extension.startswith(".") or len(extension) < 2:
        raise ValueError("category mapping must look like .ext=Category")
    if not category or category in {".", ".."} or "/" in category or "\\" in category:
        raise ValueError("category name must be a single non-empty folder name")
    return extension, category


def plan_moves(root: str | Path, recursive: bool = False,
               category_overrides: dict[str, str] | None = None,
               exclude_patterns: list[str] | None = None) -> list[Move]:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    overrides = {}
    for extension, category in (category_overrides or {}).items():
        normalized_extension, safe_category = parse_category_override(f"{extension}={category}")
        overrides[normalized_extension] = safe_category
    if recursive:
        def walk_files():
            for current, directories, filenames in os.walk(root, followlinks=False):
                current_path = Path(current)
                directories[:] = [name for name in directories
                                  if name not in IGNORED_DIRS and not (current_path / name).is_symlink()]
                for name in filenames:
                    path = current_path / name
                    if path.is_file() and not path.is_symlink():
                        yield path
        candidates = walk_files()
    else:
        candidates = (p for p in root.iterdir() if p.is_file() and not p.is_symlink())
    reserved: set[Path] = set()
    moves = []
    patterns = [pattern for pattern in (exclude_patterns or []) if pattern]
    for source in sorted(candidates, key=lambda p: str(p).casefold()):
        if source.name == HISTORY_NAME:
            continue
        relative = source.relative_to(root).as_posix()
        if any(fnmatchcase(relative, pattern) or fnmatchcase(source.name, pattern) for pattern in patterns):
            continue
        target_dir = root / category_for(source, overrides)
        if source.parent == target_dir:
            continue
        destination = _free_destination(target_dir / source.name, reserved)
        reserved.add(destination)
        moves.append(Move(source, destination))
    return moves


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def apply_moves(root: str | Path, moves: list[Move]) -> str | None:
    root = Path(root).expanduser().resolve()
    if not moves:
        return None
    batch_id = uuid.uuid4().hex
    completed: list[tuple[Path, Path]] = []
    try:
        for move in moves:
            move.destination.parent.mkdir(parents=True, exist_ok=True)
            if move.destination.exists():
                raise FileExistsError(f"refusing to overwrite: {move.destination}")
            shutil.move(str(move.source), str(move.destination))
            completed.append((move.source, move.destination))
        entry = {"event": "batch", "id": batch_id,
                 "created_at": datetime.now(timezone.utc).isoformat(),
                 "moves": [{"source": _relative(src, root), "destination": _relative(dst, root)}
                           for src, dst in completed]}
        with (root / HISTORY_NAME).open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return batch_id
    except Exception:
        for original, moved in reversed(completed):
            original.parent.mkdir(parents=True, exist_ok=True)
            if moved.exists() and not original.exists():
                shutil.move(str(moved), str(original))
        raise


def undo_last(root: str | Path) -> int:
    root = Path(root).expanduser().resolve()
    journal_path = root / HISTORY_NAME
    if not journal_path.exists():
        raise ValueError("no SafeSort history found")
    try:
        entries = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read history journal: {exc}") from exc
    undone = {e.get("id") for e in entries if e.get("event") == "undo"}
    batch = next((e for e in reversed(entries) if e.get("event") == "batch" and e.get("id") not in undone), None)
    if not batch:
        raise ValueError("there are no unapplied moves to undo")
    moves = [(root / item["destination"], root / item["source"]) for item in reversed(batch["moves"])]
    for current, original in moves:
        if not current.exists():
            raise ValueError(f"cannot undo; moved file is missing: {current}")
        if original.exists():
            raise ValueError(f"cannot undo; original path is occupied: {original}")
    restored: list[tuple[Path, Path]] = []
    try:
        for current, original in moves:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(original))
            restored.append((current, original))
        with journal_path.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps({"event": "undo", "id": batch["id"],
                                      "undone_at": datetime.now(timezone.utc).isoformat()}) + "\n")
    except Exception:
        for original, current in reversed(restored):
            current.parent.mkdir(parents=True, exist_ok=True)
            if original.exists() and not current.exists():
                shutil.move(str(original), str(current))
        raise
    return len(restored)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="safesort", description="Organize files into type folders, safely and locally.")
    parser.add_argument("directory", nargs="?", default=".", help="directory to organize (default: current directory)")
    parser.add_argument("--recursive", action="store_true", help="include files in subdirectories (flatten into type folders)")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                        help="skip paths matching a glob (repeatable; matches path or filename)")
    parser.add_argument("--category", action="append", default=[], metavar=".EXT=NAME",
                        help="override an extension category (repeatable, e.g. .pdf=Reading)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="perform the previewed moves")
    mode.add_argument("--undo", action="store_true", help="undo the most recent SafeSort batch")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = Path(args.directory).expanduser().resolve()
        if args.undo:
            count = undo_last(root)
            print(f"Undid {count} move(s).")
            return 0
        overrides = dict(parse_category_override(item) for item in args.category)
        moves = plan_moves(root, args.recursive, overrides, args.exclude)
        if not moves:
            print("Nothing to organize.")
            return 0
        for move in moves:
            print(f"{_relative(move.source, root)} -> {_relative(move.destination, root)}")
        if not args.apply:
            print(f"\nPreview only: {len(moves)} move(s). Re-run with --apply to proceed.")
            return 0
        batch_id = apply_moves(root, moves)
        print(f"\nMoved {len(moves)} file(s). Batch {batch_id}; undo with: safesort {root} --undo")
        return 0
    except (ValueError, OSError, shutil.Error) as exc:
        print(f"safesort: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
