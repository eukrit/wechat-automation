"""Environment-based configuration for WeChat Automation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Google Cloud
    gcp_project_id: str = Field(default="ai-agents-go", alias="GCP_PROJECT_ID")
    gcs_bucket: str = Field(
        default="wechat-documents-attachments", alias="GCS_BUCKET"
    )

    # Firestore databases
    firestore_database: str = Field(
        default="wechat-documents", alias="FIRESTORE_DATABASE"
    )
    shipping_firestore_database: str = Field(
        default="shipping-automation", alias="SHIPPING_FIRESTORE_DATABASE"
    )

    # Local paths (Windows defaults)
    wechat_auto_path: str = Field(
        default=r"C:\Users\eukri\OneDrive\Documents\xwechat_files\wxid_5i25oznpj6ox12_309f\msg\file",
        alias="WECHAT_AUTO_PATH",
    )
    wechat_onedrive_path: str = Field(
        default=r"C:\Users\eukri\OneDrive\Documents\Documents GO\WeChat OneDrive",
        alias="WECHAT_ONEDRIVE_PATH",
    )
    wechat_attach_path: str = Field(
        default=r"C:\Users\eukri\OneDrive\Documents\xwechat_files\wxid_5i25oznpj6ox12_309f\msg\attach",
        alias="WECHAT_ATTACH_PATH",
    )

    # Watcher settings
    watcher_debounce_seconds: float = Field(default=5.0, alias="WATCHER_DEBOUNCE_SECONDS")
    watcher_scan_interval_hours: float = Field(default=6.0, alias="WATCHER_SCAN_INTERVAL_HOURS")

    # Vendor matching
    vendor_match_threshold: int = Field(default=85, alias="VENDOR_MATCH_THRESHOLD")

    # Environment
    environment: str = Field(default="production", alias="ENVIRONMENT")
    log_dir: str = Field(
        default=str(Path.home() / ".wechat-automation"),
        alias="LOG_DIR",
    )

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
