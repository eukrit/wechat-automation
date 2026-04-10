"""Scanner for WeChat OneDrive manual download folder.

Processes the manually organized folder structure where folder names
contain vendor names and dates:
- "2026-04-08 Moonhill Climbing Wall/" -> vendor=Moonhill Climbing Wall, date=2026-04-08
- "WeChat China Lighting/CDN Lighting/" -> vendor=CDN Lighting, category=Lighting
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from config.settings import get_settings
from watcher.file_watcher import WATCH_EXTENSIONS
from watcher.processor import FileProcessor

logger = logging.getLogger(__name__)

# Pattern for date-prefixed folders: "YYYY-MM-DD Vendor Name"
_DATE_FOLDER_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(.+)$")

# Pattern for category folders: "WeChat China Category" or "WeChat Category"
_CATEGORY_PATTERN = re.compile(r"^WeChat\s+(?:China\s+)?(.+)$", re.IGNORECASE)


def _parse_folder_name(folder_name: str) -> tuple[str, str, str]:
    """Parse a folder name and return (vendor_name, date, category).

    Examples:
        "2026-04-08 Moonhill Climbing Wall" -> ("Moonhill Climbing Wall", "2026-04-08", "")
        "WeChat China Lighting" -> ("", "", "Lighting")
    """
    # Try date-prefixed pattern
    m = _DATE_FOLDER_PATTERN.match(folder_name)
    if m:
        return m.group(2).strip(), m.group(1), ""

    # Try category pattern
    m = _CATEGORY_PATTERN.match(folder_name)
    if m:
        return "", "", m.group(1).strip()

    return folder_name, "", ""


def scan_onedrive(processor: FileProcessor | None = None) -> int:
    """Scan the WeChat OneDrive folder and process all files.

    Returns the count of newly processed files.
    """
    settings = get_settings()
    onedrive_path = Path(settings.wechat_onedrive_path)

    if not onedrive_path.exists():
        logger.error("OneDrive path does not exist: %s", onedrive_path)
        return 0

    if processor is None:
        processor = FileProcessor()

    count = 0

    for item in sorted(onedrive_path.iterdir()):
        if item.is_file():
            # Top-level files (e.g., standalone PDFs)
            if item.suffix.lower() in WATCH_EXTENSIONS:
                result = processor.process_file(
                    str(item),
                    source="wechat_onedrive",
                    folder_name=item.name,
                )
                if result:
                    count += 1
            continue

        if not item.is_dir():
            continue

        # Parse the folder name for vendor/category info
        vendor_name, date_str, category = _parse_folder_name(item.name)

        if category:
            # Category folder — iterate sub-vendor folders
            count += _scan_category_folder(item, category, processor)
        else:
            # Vendor folder — process all files inside
            folder_name = item.name
            for fpath in _iter_files(item):
                result = processor.process_file(
                    str(fpath),
                    source="wechat_onedrive",
                    folder_name=folder_name,
                )
                if result:
                    count += 1

    logger.info("OneDrive scan complete: %d new files processed", count)
    return count


def _scan_category_folder(
    category_dir: Path,
    category: str,
    processor: FileProcessor,
) -> int:
    """Scan a category folder (e.g., "WeChat China Lighting/CDN Lighting/")."""
    count = 0
    for sub in sorted(category_dir.iterdir()):
        if sub.is_dir():
            # Sub-vendor folder
            folder_name = f"{category_dir.name}/{sub.name}"
            for fpath in _iter_files(sub):
                result = processor.process_file(
                    str(fpath),
                    source="wechat_onedrive",
                    folder_name=folder_name,
                )
                if result:
                    count += 1
        elif sub.is_file() and sub.suffix.lower() in WATCH_EXTENSIONS:
            result = processor.process_file(
                str(sub),
                source="wechat_onedrive",
                folder_name=category_dir.name,
            )
            if result:
                count += 1
    return count


def _iter_files(directory: Path):
    """Yield all files recursively that match watched extensions."""
    for fpath in directory.rglob("*"):
        if fpath.is_file() and fpath.suffix.lower() in WATCH_EXTENSIONS:
            yield fpath
