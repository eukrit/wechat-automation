"""Pydantic models for all Firestore documents in wechat-documents DB."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WeChatFile(BaseModel):
    """A file ingested from WeChat downloads.

    Collection: wechat_files
    Document ID: SHA-256 hash of file content (dedup built-in).
    """

    # Identity
    file_id: str  # SHA-256 of file bytes
    filename: str
    file_extension: str  # pdf, xlsx, dwg, skp, etc.
    file_size_bytes: int

    # Source tracking
    source: str  # "xwechat_auto" | "wechat_onedrive"
    source_path: str  # Original local path
    source_folder: str = ""  # e.g. "2026-04" or "2026-04-08 Moonhill Climbing Wall"
    wechat_contact_hash: str = ""

    # Classification
    file_type: str = "other"  # catalog | invoice | quotation | drawing | po | price_list | image | video | other
    document_language: str = ""  # en | zh | mixed

    # Parsed metadata from filename
    parsed_date: str = ""  # YYYY-MM-DD
    parsed_vendor_name: str = ""
    parsed_project_name: str = ""

    # Vendor linking
    vendor_id: str = ""  # FK -> go_vendors in shipping-automation DB
    vendor_name: str = ""
    vendor_match_method: str = ""  # filename_exact | filename_fuzzy | folder_name | manual | ai_extracted
    vendor_match_confidence: float = 0.0

    # Cross-references
    people_contact_id: str = ""  # FK -> people_contacts in default DB
    peak_contact_code: str = ""  # FK -> Peak contact
    shipping_order_ids: list[str] = Field(default_factory=list)

    # GCS storage
    gcs_path: str = ""  # gs://wechat-documents-attachments/...
    content_type: str = "application/octet-stream"

    # Processing status
    status: str = "ingested"  # ingested | classified | vendor_linked | product_extracted | needs_vendor_link
    processing_errors: list[str] = Field(default_factory=list)

    # Timestamps
    file_created_at: datetime | None = None
    file_modified_at: datetime | None = None
    ingested_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WeChatProduct(BaseModel):
    """Product extracted from a vendor file.

    Collection: wechat_products
    Document ID: auto-generated.
    """

    product_name: str
    product_name_zh: str = ""

    # Source file
    source_file_id: str  # FK -> wechat_files
    source_filename: str = ""
    source_page: int = 0

    # Product details
    sku: str = ""
    description: str = ""
    category: str = ""  # Furniture, Lighting, Climbing, Playground, etc.
    subcategory: str = ""
    material: str = ""
    dimensions: str = ""
    weight_kg: float = 0.0
    color: str = ""

    # Pricing
    unit_price: float = 0.0
    currency: str = "USD"
    price_term: str = ""  # FOB, CIF, EXW
    moq: int = 0

    # Vendor
    vendor_id: str = ""
    vendor_name: str = ""

    # Extraction metadata
    extraction_method: str = ""  # excel_parse | pdf_table | gemini_vision
    extraction_confidence: float = 0.0
    extracted_at: datetime = Field(default_factory=_utcnow)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WeChatContactMapping(BaseModel):
    """Maps a WeChat contact hash to a known vendor.

    Collection: wechat_contact_mapping
    Document ID: WeChat contact hash (from msg/attach/{hash}/).
    """

    contact_hash: str

    # Resolved identity
    vendor_id: str = ""
    vendor_name: str = ""
    people_contact_id: str = ""
    peak_contact_code: str = ""
    wechat_display_name: str = ""

    mapping_method: str = ""  # manual | folder_correlation | filename_pattern
    confidence: float = 1.0

    file_count: int = 0
    image_count: int = 0
    last_file_date: str = ""

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WeChatVendor(BaseModel):
    """Vendor profile aggregating all files and products.

    Collection: wechat_vendors
    Document ID: sanitized vendor name (lowercase, underscores).
    """

    vendor_id: str  # doc ID
    vendor_name: str
    aliases: list[str] = Field(default_factory=list)

    # Cross-references to other DBs
    go_vendor_id: str = ""  # FK -> go_vendors in shipping-automation DB
    peak_contact_code: str = ""  # FK -> peak_contacts
    people_contact_id: str = ""  # FK -> people_contacts

    # File references (list of file_ids)
    file_ids: list[str] = Field(default_factory=list)
    file_count: int = 0
    product_count: int = 0

    # File type breakdown
    catalogs: int = 0
    quotations: int = 0
    invoices: int = 0
    purchase_orders: int = 0
    price_lists: int = 0
    drawings: int = 0
    certificates: int = 0
    images: int = 0
    other_files: int = 0

    # Processing status
    files_extracted: int = 0  # files with products extracted
    files_pending: int = 0  # files not yet extracted
    last_file_date: str = ""  # most recent file date
    total_size_bytes: int = 0

    # Categories (from product data)
    categories: list[str] = Field(default_factory=list)
    subcategories: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SyncStatus(BaseModel):
    """Tracks sync/processing pipeline status.

    Collection: sync_status
    Document ID: "latest" (singleton) or timestamp-based for history.
    """

    sync_id: str = ""
    status: str = "running"  # running | completed | failed
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None

    # Ingestion stats
    files_scanned: int = 0
    files_new: int = 0
    files_skipped_duplicate: int = 0

    # Vendor matching stats
    files_vendor_matched: int = 0
    files_unmatched: int = 0

    # Product extraction stats
    files_extracted: int = 0
    products_new: int = 0
    extraction_errors: int = 0

    # Totals (cumulative)
    total_files: int = 0
    total_products: int = 0
    total_vendors: int = 0

    error_details: list[str] = Field(default_factory=list)


class IngestionEvent(BaseModel):
    """Audit trail for ingestion pipeline.

    Collection: ingestion_log
    Document ID: auto-generated.
    """

    event_type: str  # file_detected | file_uploaded | vendor_matched | product_extracted | error
    file_id: str = ""
    filename: str = ""
    source_path: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)
