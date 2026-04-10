"""Main ingestion pipeline orchestrator.

Processes a single file through: hash -> parse -> classify -> upload -> match -> store.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from wechat_automation import firestore_store
from wechat_automation.file_classifier import classify_file
from wechat_automation.filename_parser import parse_filename
from wechat_automation.gcs_store import GCSStore
from wechat_automation.models import IngestionEvent, WeChatFile
from wechat_automation.vendor_matcher import VendorMatcher

logger = logging.getLogger(__name__)


class FileProcessor:
    """Processes files through the full ingestion pipeline."""

    def __init__(self, gcs: GCSStore | None = None, matcher: VendorMatcher | None = None) -> None:
        self._gcs = gcs or GCSStore()
        self._matcher = matcher or VendorMatcher()

    def process_file(
        self,
        filepath: str | Path,
        source: str = "xwechat_auto",
        folder_name: str = "",
    ) -> WeChatFile | None:
        """Process a single file through the full ingestion pipeline.

        Args:
            filepath: Absolute path to the file.
            source: "xwechat_auto" or "wechat_onedrive".
            folder_name: Parent folder name (used for vendor matching in OneDrive sources).

        Returns:
            The created WeChatFile, or None if skipped/failed.
        """
        path = Path(filepath)
        if not path.exists():
            logger.warning("File not found: %s", path)
            return None

        filename = path.name
        extension = path.suffix.lstrip(".").lower()

        # Step 1: Hash for deduplication
        file_bytes = path.read_bytes()
        file_id = hashlib.sha256(file_bytes).hexdigest()

        if firestore_store.file_exists(file_id):
            logger.debug("Skipping duplicate: %s (%s)", filename, file_id[:12])
            return None

        logger.info("Processing: %s (%s, %d bytes)", filename, file_id[:12], len(file_bytes))

        # Step 2: Parse filename
        parsed = parse_filename(str(path))

        # Step 3: Classify
        file_type, content_type = classify_file(extension, parsed)

        # Step 4: Determine year-month for GCS path
        year_month = parsed.date[:7] if parsed.date else _get_year_month(path)

        # Step 5: Upload to GCS
        try:
            gcs_path = self._gcs.upload(
                file_bytes=file_bytes,
                filename=filename,
                file_type=file_type,
                year_month=year_month,
                content_type=content_type,
            )
        except Exception as e:
            logger.error("GCS upload failed for %s: %s", filename, e)
            firestore_store.log_event(IngestionEvent(
                event_type="error",
                filename=filename,
                source_path=str(path),
                details={"error": f"GCS upload failed: {e}"},
            ))
            return None

        # Step 6: Vendor matching
        vendor_match = self._matcher.match(
            vendor_hint=parsed.vendor_hint,
            folder_name=folder_name,
        )

        # Step 7: Get file timestamps
        stat = path.stat()
        file_created = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
        file_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        # Determine source folder
        if not folder_name:
            folder_name = path.parent.name  # e.g. "2026-04" from msg/file/2026-04/

        # Step 8: Build and store the document
        status = "vendor_linked" if vendor_match.vendor_id else "needs_vendor_link"

        wechat_file = WeChatFile(
            file_id=file_id,
            filename=filename,
            file_extension=extension,
            file_size_bytes=len(file_bytes),
            source=source,
            source_path=str(path),
            source_folder=folder_name,
            file_type=file_type,
            document_language=parsed.language,
            parsed_date=parsed.date,
            parsed_vendor_name=parsed.vendor_hint,
            parsed_project_name=parsed.project_hint,
            vendor_id=vendor_match.vendor_id,
            vendor_name=vendor_match.vendor_name,
            vendor_match_method=vendor_match.match_method,
            vendor_match_confidence=vendor_match.confidence,
            people_contact_id=vendor_match.people_contact_id,
            peak_contact_code=vendor_match.peak_contact_code,
            gcs_path=gcs_path,
            content_type=content_type,
            status=status,
            file_created_at=file_created,
            file_modified_at=file_modified,
        )

        firestore_store.upsert_file(wechat_file)

        # Log the ingestion event
        firestore_store.log_event(IngestionEvent(
            event_type="file_uploaded",
            file_id=file_id,
            filename=filename,
            source_path=str(path),
            details={
                "source": source,
                "file_type": file_type,
                "vendor_id": vendor_match.vendor_id,
                "vendor_name": vendor_match.vendor_name,
                "match_method": vendor_match.match_method,
                "gcs_path": gcs_path,
            },
        ))

        logger.info(
            "Ingested: %s -> %s (vendor: %s, type: %s)",
            filename, file_id[:12], vendor_match.vendor_name or "unmatched", file_type,
        )
        return wechat_file


def _get_year_month(path: Path) -> str:
    """Extract YYYY-MM from file path or modification time."""
    # Try parent folder name (msg/file/2026-04/)
    parent = path.parent.name
    if len(parent) == 7 and parent[4] == "-":
        return parent
    # Fall back to file modification time
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime.strftime("%Y-%m")
