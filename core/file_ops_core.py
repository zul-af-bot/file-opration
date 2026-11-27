import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IGNORED_TEMP_EXTS = {".crdownload", ".part", ".tmp", ".opdownload", ".download"}
IGNORED_FILENAMES = {"desktop.ini", "thumbs.db"}


@dataclass
class FileOpConfig:
    action: str = "move"  # "move" | "copy"
    filter_type: str = "all"  # "all" | "video" | "image" | "custom"
    custom_exts: str = ""
    rename_mode: str = "keep"  # "keep" | "prefix_suffix" | "sequence" | "replace"
    prefix: str = ""
    suffix: str = ""
    base_name: str = "file"
    start_index: int = 1
    zero_pad: int = 3
    find_text: str = ""
    replace_text: str = ""
    conflict_policy: str = "auto_number"  # "auto_number" | "overwrite" | "skip"


def parse_extensions(filter_type: str, custom_exts: str = "") -> Optional[set[str]]:
    if filter_type == "video":
        return VIDEO_EXTENSIONS
    if filter_type == "image":
        return IMAGE_EXTENSIONS
    if filter_type == "custom" and custom_exts.strip():
        exts = set()
        for part in custom_exts.replace(";", ",").split(","):
            cleaned = part.strip().lower()
            if cleaned:
                if not cleaned.startswith("."):
                    cleaned = "." + cleaned
                exts.add(cleaned)
        return exts or None
    return None


def collect_matching_files(folder: Path, config: FileOpConfig) -> list[Path]:
    if not folder.is_dir():
        return []
    allowed = parse_extensions(config.filter_type, config.custom_exts)
    files = []
    for p in sorted(folder.iterdir()):
        if not p.is_file():
            continue
        if p.name.startswith((".__tmp_", ".", "~$")) or p.name.lower() in IGNORED_FILENAMES:
            continue
        if p.suffix.lower() in IGNORED_TEMP_EXTS:
            continue
        if allowed is not None and p.suffix.lower() not in allowed:
            continue
        files.append(p)
    return files


def compute_new_filename(original: Path, config: FileOpConfig, seq_num: int) -> str:
    stem = original.stem
    ext = original.suffix

    if config.rename_mode == "prefix_suffix":
        new_stem = f"{config.prefix}{stem}{config.suffix}"
    elif config.rename_mode == "sequence":
        base = config.base_name.strip() or "file"
        pad = max(1, config.zero_pad)
        new_stem = f"{base}_{seq_num:0{pad}d}"
    elif config.rename_mode == "replace":
        if config.find_text:
            new_stem = stem.replace(config.find_text, config.replace_text)
        else:
            new_stem = stem
    else:
        new_stem = stem

    new_stem = new_stem.strip() or stem
    return f"{new_stem}{ext}"


def resolve_unique_target(target_path: Path) -> Path:
    if not target_path.exists():
        return target_path
    stem = target_path.stem
    ext = target_path.suffix
    parent = target_path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def process_file_operation(
    src_file: Path,
    dest_folder: Path,
    config: FileOpConfig,
    seq_num: int,
    status_cb: Optional[Callable[[str], None]] = None,
) -> tuple[str, Path]:
    """Execute move/copy + rename on a single file. Returns (status_tag, final_path)."""
    dest_folder.mkdir(parents=True, exist_ok=True)
    new_name = compute_new_filename(src_file, config, seq_num)
    dest_path = dest_folder / new_name

    if src_file.resolve() == dest_path.resolve():
        return "skipped", dest_path

    if dest_path.exists():
        if config.conflict_policy == "skip":
            return "skipped", dest_path
        if config.conflict_policy == "auto_number":
            dest_path = resolve_unique_target(dest_path)

    if status_cb:
        verb = "Memindahkan" if config.action == "move" else "Menyalin"
        status_cb(f"{verb}: {src_file.name} → {dest_path.name}")

    if config.action == "move":
        if dest_path.exists() and config.conflict_policy == "overwrite":
            dest_path.unlink(missing_ok=True)
        shutil.move(str(src_file), str(dest_path))
    else:
        shutil.copy2(str(src_file), str(dest_path))

    return "done", dest_path


def rename_file_in_place(
    src_file: Path,
    config: FileOpConfig,
    seq_num: int,
    status_cb: Optional[Callable[[str], None]] = None,
) -> tuple[str, Path]:
    """Rename a single file in its own folder. Returns (status_tag, final_path)."""
    new_name = compute_new_filename(src_file, config, seq_num)
    dest_path = src_file.parent / new_name
    if src_file.resolve() == dest_path.resolve():
        return "skipped", dest_path

    if dest_path.exists():
        if config.conflict_policy == "skip":
            return "skipped", dest_path
        if config.conflict_policy == "auto_number":
            dest_path = resolve_unique_target(dest_path)
        elif config.conflict_policy == "overwrite":
            dest_path.unlink(missing_ok=True)

    if status_cb:
        status_cb(f"Rename: {src_file.name} → {dest_path.name}")
    os.replace(str(src_file), str(dest_path))
    return "done", dest_path


def is_file_stable(path: Path, wait_seconds: float = 0.8) -> bool:
    try:
        if not path.is_file():
            return False
        s1 = path.stat().st_size
        if s1 <= 0:
            return False
        time.sleep(wait_seconds)
        if not path.is_file():
            return False
        s2 = path.stat().st_size
        return s1 == s2 and s2 > 0
    except OSError:
        return False
