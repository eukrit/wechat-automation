"""One-time backfill: ingest all existing WeChat files into Firestore + GCS.

Processes both sources:
1. xwechat_files/msg/file/ (260 auto-downloaded documents)
2. Documents GO/WeChat OneDrive/ (37 manually organized vendor folders)

Usage:
    python -m scripts.initial_scan [--auto-only | --onedrive-only] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from watcher.file_watcher import full_scan
from watcher.onedrive_scanner import scan_onedrive
from watcher.processor import FileProcessor
from wechat_automation import firestore_store

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Initial scan of all WeChat files")
    parser.add_argument("--auto-only", action="store_true", help="Only scan xwechat_files auto-downloads")
    parser.add_argument("--onedrive-only", action="store_true", help="Only scan WeChat OneDrive manual downloads")
    parser.add_argument("--dry-run", action="store_true", help="Count files without processing")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()

    if args.dry_run:
        _dry_run(settings, args)
        return

    processor = FileProcessor()
    total = 0

    if not args.onedrive_only:
        logger.info("=== Scanning xwechat_files auto-downloads ===")
        auto_path = settings.wechat_auto_path
        if Path(auto_path).exists():
            count = full_scan(processor, auto_path)
            logger.info("Auto-downloads: %d new files ingested", count)
            total += count
        else:
            logger.warning("Auto-download path not found: %s", auto_path)

    if not args.auto_only:
        logger.info("=== Scanning WeChat OneDrive manual downloads ===")
        count = scan_onedrive(processor)
        logger.info("OneDrive: %d new files ingested", count)
        total += count

    # Summary
    total_in_db = firestore_store.count_files()
    logger.info("=== Summary ===")
    logger.info("New files ingested this run: %d", total)
    logger.info("Total files in Firestore: %d", total_in_db)


def _dry_run(settings, args) -> None:
    """Count files without processing."""
    from watcher.file_watcher import WATCH_EXTENSIONS

    if not args.onedrive_only:
        auto_path = Path(settings.wechat_auto_path)
        if auto_path.exists():
            count = sum(
                1 for f in auto_path.rglob("*")
                if f.is_file() and f.suffix.lower() in WATCH_EXTENSIONS
            )
            logger.info("Auto-downloads: %d files found", count)

    if not args.auto_only:
        onedrive_path = Path(settings.wechat_onedrive_path)
        if onedrive_path.exists():
            count = sum(
                1 for f in onedrive_path.rglob("*")
                if f.is_file() and f.suffix.lower() in WATCH_EXTENSIONS
            )
            logger.info("OneDrive: %d files found", count)


if __name__ == "__main__":
    main()
