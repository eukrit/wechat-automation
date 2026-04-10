"""Quick sync: scan both WeChat sources for new files and ingest them.

Designed to run every 15 minutes via Task Scheduler.
Only processes NEW files (dedup via SHA-256 hash check in Firestore).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from watcher.file_watcher import full_scan
from watcher.onedrive_scanner import scan_onedrive
from watcher.processor import FileProcessor


def main() -> None:
    settings = get_settings()

    # Set up logging
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "sync.log"),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger(__name__)

    processor = FileProcessor()
    total = 0

    # Scan auto-downloads
    auto_path = settings.wechat_auto_path
    if Path(auto_path).exists():
        count = full_scan(processor, auto_path)
        if count:
            logger.info("Auto-downloads: %d new files", count)
        total += count

    # Scan OneDrive
    count = scan_onedrive(processor)
    if count:
        logger.info("OneDrive: %d new files", count)
    total += count

    if total:
        logger.info("Sync complete: %d new files ingested", total)
    else:
        logger.info("Sync complete: no new files")


if __name__ == "__main__":
    main()
