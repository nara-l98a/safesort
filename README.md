# SafeSort CLI

SafeSort tidies a downloads or project folder into type-based subfolders. It is deliberately **preview-first**: the default command lists intended moves and changes nothing. Applying a batch creates a local journal, so the most recent batch can be undone.

## Requirements

- Python 3.10 or newer
- No third-party runtime dependencies

## Install

```bash
git clone https://github.com/nara-l98a/safesort.git
cd safesort
python3 -m venv .venv
. .venv/bin/activate
pip install .
```

From a checkout without installation, use `PYTHONPATH=src python -m safesort --help`.

## Quick start

```bash
# Inspect the plan first; this does not move anything.
safesort ~/Downloads

# After reviewing the output, apply the moves.
safesort ~/Downloads --apply

# Restore files moved by the latest SafeSort batch.
safesort ~/Downloads --undo

# Customize file placement and skip sensitive exports; both options are repeatable.
safesort ~/Downloads --category .pdf=Reading --category .epub=Reading --exclude "private-*"
```

Example preview:

```text
photo.jpg -> Images/photo.jpg
invoice.pdf -> Documents/invoice.pdf
backup.zip -> Archives/backup.zip

Preview only: 3 move(s). Re-run with --apply to proceed.
```

`--recursive` includes files in subdirectories and flattens them into the category folders. Without it, only files directly inside the chosen directory are considered. Recursive scanning skips `.git`, `.hg`, `.svn`, `.venv`, `node_modules`, and `__pycache__` directories, and does not follow symlinked directories. If a name already exists, SafeSort selects `name (1).ext`, `name (2).ext`, etc.; it will not intentionally overwrite an existing file. Directories themselves are never moved. Extension matching is case-insensitive.

`--category .EXT=Folder` overrides a built-in category (extension matching is case-insensitive); the folder must be a single name and cannot escape the selected root. `--exclude GLOB` skips matching relative paths or file names, and can be repeated. Exclusions apply to both direct and recursive scans. Review the preview before applying a customized plan.

## Categories

Images, Documents, Spreadsheets, Presentations, Archives, Audio, Video, Code, Other (unknown extension), and No Extension.

## Undo and safety notes

- `--apply` is the only mode that moves files; preview is the default.
- A `.safesort-history.jsonl` journal is stored at the root of the organized directory. It contains relative paths, batch IDs, and timestamps. It is used only for undo and is never uploaded.
- `--undo` restores the latest batch that has not already been undone. If a moved file is missing or its original path is occupied, undo stops and reports the conflict rather than overwriting data.
- `--undo` only reverts SafeSort's recorded moves; it does not reverse unrelated changes.
- Back up important files before reorganizing them. Review the preview, especially before using `--recursive`.

## Development and tests

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

All tests use temporary directories and do not alter personal files.

## License

MIT. See [LICENSE](LICENSE).
