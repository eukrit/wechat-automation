"""Upload and manage files in GCS bucket wechat-documents-attachments."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud import storage

from config.settings import get_settings

logger = logging.getLogger(__name__)


class GCSStore:
    """Stores WeChat files in GCS with organized path structure."""

    def __init__(self, client: storage.Client | None = None) -> None:
        settings = get_settings()
        self._client = client or storage.Client(project=settings.gcp_project_id)
        self._bucket = self._client.bucket(settings.gcs_bucket)

    def upload(
        self,
        file_bytes: bytes,
        filename: str,
        file_type: str,
        year_month: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload file to GCS and return the gs:// path.

        Path pattern: {file_type}/{YYYY-MM}/{filename}
        """
        gcs_path = f"{file_type}/{year_month}/{filename}"
        blob = self._bucket.blob(gcs_path)
        blob.upload_from_string(file_bytes, content_type=content_type)
        full_path = f"gs://{self._bucket.name}/{gcs_path}"
        logger.info("Uploaded %s (%d bytes)", full_path, len(file_bytes))
        return full_path

    def download(self, gcs_path: str) -> bytes:
        """Download a file given its gs:// path."""
        path = gcs_path.replace(f"gs://{self._bucket.name}/", "")
        blob = self._bucket.blob(path)
        return blob.download_as_bytes()

    def exists(self, gcs_path: str) -> bool:
        """Check if a file exists in GCS."""
        path = gcs_path.replace(f"gs://{self._bucket.name}/", "")
        return self._bucket.blob(path).exists()

    def list_by_type(self, file_type: str, limit: int = 100) -> list[dict]:
        """List files under a file_type prefix."""
        blobs = self._bucket.list_blobs(prefix=f"{file_type}/", max_results=limit)
        return [
            {
                "name": blob.name,
                "gcs_path": f"gs://{self._bucket.name}/{blob.name}",
                "size_bytes": blob.size or 0,
                "content_type": blob.content_type or "",
                "created": blob.time_created.isoformat() if blob.time_created else "",
            }
            for blob in blobs
        ]
