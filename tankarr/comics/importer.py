"""Library import for comic archives: scan, match to tracked issues, file."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from tankarr.comics.release import (
    clean_series_title,
    issue_key,
    match_issue,
    parse_release,
)
from tankarr.comics.store import ComicStore
from tankarr.config import Settings

COMIC_SUFFIXES = {".cbz", ".cbr", ".cb7", ".cbt", ".pdf", ".epub"}
MAX_FILES = 20_000
UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def comics_root(settings: Settings) -> Path:
    return Path(settings.comics_library_dir or Path(settings.library_dir) / "Comics")


def safe_name(text: str) -> str:
    return " ".join(UNSAFE.sub(" ", text).split()).strip(" .") or "Unknown"


def _walk(root: Path) -> tuple[list[Path], list[dict[str, str]]]:
    files: list[Path] = []
    skipped: list[dict[str, str]] = []
    stack = [root]
    while stack and len(files) < MAX_FILES:
        directory = stack.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            continue
        for child in children:
            if child.name.startswith("."):
                continue
            relative = str(child.relative_to(root))
            if child.is_symlink():
                skipped.append(
                    {"path": relative, "reason": "Symlinks are not imported"}
                )
            elif child.is_dir():
                stack.append(child)
            elif child.suffix.casefold() in COMIC_SUFFIXES:
                files.append(child)
    return sorted(files, key=lambda p: str(p).casefold()), skipped


def _candidate_title(root: Path, path: Path) -> str:
    """The file name, prefixed by its folder when the name has no series."""

    stem = path.name
    parsed = parse_release(stem)
    if parsed.series and parsed.issue is not None:
        return stem
    folder = path.parent
    return f"{folder.name} {stem}" if folder != root else stem


def scan(root: Path, store: ComicStore) -> dict:
    files, skipped = _walk(root)
    tracked = [store.get_series(row["id"]) for row in store.list_series()]
    groups: dict[str, dict] = {}
    for path in files:
        title = _candidate_title(root, path)
        guess = parse_release(title)
        entry = {
            "path": str(path.relative_to(root)),
            "name": path.name,
            "size": path.stat().st_size,
            "issue": guess.issue,
            "year": guess.year,
            "issue_id": None,
            "status": "unmatched",
        }
        series_match = None
        issue_row = None
        if guess.issue is not None and guess.kind == "issue":
            for series in tracked:
                matched = match_issue(
                    title,
                    series_title=series["title"],
                    issue_number=guess.issue,
                    series_year=series.get("year"),
                )
                if matched is None:
                    continue
                key = issue_key(guess.issue)
                issue_row = next(
                    (i for i in series["issues"] if issue_key(i["number"]) == key), None
                )
                series_match = series
                break
        if guess.kind != "issue":
            entry["status"] = "unsupported"
        elif series_match is None:
            entry["status"] = "unmatched"
        elif issue_row is None:
            entry["status"] = "no_issue"
        elif issue_row["status"] == "downloaded":
            entry["status"] = "already_have"
            entry["issue_id"] = issue_row["id"]
        else:
            entry["status"] = "ready"
            entry["issue_id"] = issue_row["id"]

        if series_match is not None:
            key = f"series:{series_match['id']}"
            label = series_match["title"]
        else:
            label = guess.series or "Unknown series"
            key = f"guess:{clean_series_title(label).casefold()}:{guess.year or ''}"
        group = groups.setdefault(
            key,
            {
                "key": key,
                "label": label,
                "year": series_match.get("year") if series_match else guess.year,
                "series_id": series_match["id"] if series_match else None,
                "files": [],
            },
        )
        group["files"].append(entry)

    ordered = sorted(groups.values(), key=lambda g: g["label"].casefold())
    return {
        "root": str(root),
        "groups": ordered,
        "skipped": skipped,
        "truncated": len(files) >= MAX_FILES,
    }


def _resolve(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if root.resolve() not in candidate.parents:
        raise ValueError("File is outside the import folder")
    if candidate.is_symlink() or not candidate.is_file():
        raise FileNotFoundError(relative)
    if candidate.suffix.casefold() not in COMIC_SUFFIXES:
        raise ValueError("Unsupported file type")
    return candidate


def destination(settings: Settings, series: dict, issue: dict, suffix: str) -> Path:
    year = f" ({series['year']})" if series.get("year") else ""
    folder = safe_name(f"{series['title']}{year}")
    number = issue["number"]
    padded = number.zfill(3) if number.isdigit() else number
    name = safe_name(f"{series['title']} {padded}{year}") + suffix.casefold()
    return comics_root(settings) / folder / name


def import_files(
    settings: Settings,
    store: ComicStore,
    root: Path,
    items: list[dict],
    *,
    move: bool,
) -> dict:
    """File each approved archive and mark its issue downloaded."""

    imported: list[str] = []
    errors: list[dict[str, str]] = []
    for item in items:
        relative = str(item.get("path") or "")
        try:
            source = _resolve(root, relative)
            series = store.get_series(str(item["series_id"]))
            issue = next(
                (i for i in series["issues"] if i["id"] == item.get("issue_id")), None
            )
            if issue is None:
                raise KeyError("issue")
            target = destination(settings, series, issue, source.suffix)
            if target.exists():
                raise FileExistsError(target.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if move:
                shutil.move(str(source), target)
            else:
                shutil.copy2(source, target)
            store.mark_downloaded(issue["id"], str(target))
            imported.append(relative)
        except KeyError:
            errors.append({"path": relative, "error": "Series or issue not found"})
        except FileExistsError as exc:
            errors.append({"path": relative, "error": f"{exc} already exists"})
        except (OSError, ValueError) as exc:
            errors.append({"path": relative, "error": type(exc).__name__})
    return {"imported": imported, "errors": errors}
