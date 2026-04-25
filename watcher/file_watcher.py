"""Watchdog-based file watcher for WeChat auto-download folder.

Monitors xwechat_files/msg/file/ for new documents. Debounces events
to handle OneDrive sync delays. Includes periodic full-scan as safety net.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from config.settings import get_settings
from watcher.processor import FileProcessor

logger = logging.getLogger(__name__)

# File extensions we care about
WATCH_EXTENSIONS = {
    ".pdf", ".xlsx", ".xls", ".doc", ".docx", ".pptx",
    ".dwg", ".dxf", ".skp", ".3dm",
    ".jpg", ".jpeg", ".png", ".webp",
    ".mp4", ".m4v", ".mov",
    ".rar", ".zip", ".tgz",
    ".csv",
}


class DebouncedHandler(FileSystemEventHandler):
    """Handles file events with debouncing to avoid processing partial writes."""

    def __init__(self, processor: FileProcessor, debounce_seconds: float = 5.0) -> None:
        self._processor = processor
        self._debounce = debounce_seconds
        self._pending: dict[str, float] = {}  # path -> scheduled_time
        self._lock = threading.Lock()
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer_thread.start()

    def on_created(self, event: FileCreatedEvent) -> None:
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_modified(self, event: FileModifiedEvent) -> None:
        if not event.is_directory:
            self._schedule(event.src_path)

    def _schedule(self, path: str) -> None:
        ext = Path(path).suffix.lower()
        if ext not in WATCH_EXTENSIONS:
            return
        with self._lock:
            self._pending[path] = time.time() + self._debounce

    def _timer_loop(self) -> None:
        """Background loop that processes files after debounce period."""
        while True:
            time.sleep(1.0)
            now = time.time()
            ready: list[str] = []
            with self._lock:
                for path, scheduled in list(self._pending.items()):
                    if now >= scheduled:
                        ready.append(path)
                        del self._pending[path]
            for path in ready:
                try:
                    self._processor.process_file(path, source="xwechat_auto")
                except Exception:
                    logger.exception("Error processing %s", path)


def full_scan(processor: FileProcessor, scan_path: str) -> int:
    """Walk the entire directory and process all files. Returns count processed."""
    count = 0
    for root, _, files in Path(scan_path).walk():
        for fname in files:
            fpath = root / fname
            if fpath.suffix.lower() in WATCH_EXTENSIONS:
                try:
                    result = processor.process_file(str(fpath), source="xwechat_auto")
                    if result:
                        count += 1
                except Exception:
                    logger.exception("Error in full scan for %s", fpath)
    return count


def run_watcher() -> None:
    """Start the file watcher. Blocks forever."""
    settings = get_settings()
    watch_path = settings.wechat_auto_path

    if not Path(watch_path).exists():
        logger.error("Watch path does not exist: %s", watch_path)
        sys.exit(1)

    # Set up logging
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    file_handler = logging.FileHandler(log_dir / "watcher.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    logging.root.addHandler(file_handler)
    logging.root.setLevel(logging.INFO)

    processor = FileProcessor()
    handler = DebouncedHandler(processor, debounce_seconds=settings.watcher_debounce_seconds)

    # Initial full scan
    logger.info("Starting initial full scan of %s", watch_path)
    count = full_scan(processor, watch_path)
    logger.info("Initial scan complete: %d new files processed", count)

    # Start watchdog observer
    observer = Observer()
    observer.schedule(handler, watch_path, recursive=True)
    observer.start()
    logger.info("Watching %s for new files...", watch_path)

    # Periodic full scan as safety net
    scan_interval = settings.watcher_scan_interval_hours * 3600

    try:
        last_scan = time.time()
        while True:
            time.sleep(60)
            if time.time() - last_scan >= scan_interval:
                logger.info("Running periodic full scan...")
                count = full_scan(processor, watch_path)
                logger.info("Periodic scan: %d new files", count)
                last_scan = time.time()
    except KeyboardInterrupt:
        logger.info("Shutting down watcher...")
        observer.stop()
    observer.join()


if __name__ == "__main__":
    run_watcher()
