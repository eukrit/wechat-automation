"""Firestore CRUD operations for wechat-documents database."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from config.settings import get_settings
from wechat_automation.models import (
    IngestionEvent,
    SyncStatus,
    WeChatContactMapping,
    WeChatFile,
    WeChatProduct,
    WeChatVendor,
)

logger = logging.getLogger(__name__)

_db_cache: dict[str, firestore.Client] = {}


def _db(database: str | None = None) -> firestore.Client:
    """Get or create a Firestore client for the given database."""
    settings = get_settings()
    db_name = database or settings.firestore_database
    if db_name not in _db_cache:
        _db_cache[db_name] = firestore.Client(
            project=settings.gcp_project_id,
            database=db_name,
        )
    return _db_cache[db_name]


def shipping_db() -> firestore.Client:
    """Get Firestore client for shipping-automation database (read-only)."""
    return _db(get_settings().shipping_firestore_database)


def default_db() -> firestore.Client:
    """Get Firestore client for default database (read-only)."""
    return _db("(default)")


# ---------------------------------------------------------------------------
# wechat_files collection
# ---------------------------------------------------------------------------

def get_file(file_id: str) -> WeChatFile | None:
    doc = _db().collection("wechat_files").document(file_id).get()
    if doc.exists:
        return WeChatFile(**doc.to_dict())
    return None


def file_exists(file_id: str) -> bool:
    return _db().collection("wechat_files").document(file_id).get().exists


def upsert_file(wechat_file: WeChatFile) -> None:
    wechat_file.updated_at = datetime.now(timezone.utc)
    _db().collection("wechat_files").document(wechat_file.file_id).set(
        wechat_file.model_dump(mode="json")
    )
    logger.info("Upserted wechat_file %s: %s", wechat_file.file_id[:12], wechat_file.filename)


def search_files(
    vendor_id: str = "",
    file_type: str = "",
    status: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search files with optional filters. Uses client-side filtering to avoid composite indexes."""
    query = _db().collection("wechat_files")
    # Use a single server-side filter to avoid composite index requirements
    if file_type:
        query = query.where(filter=firestore.FieldFilter("file_type", "==", file_type))
    elif vendor_id:
        query = query.where(filter=firestore.FieldFilter("vendor_id", "==", vendor_id))
    elif status:
        query = query.where(filter=firestore.FieldFilter("status", "==", status))
    results = [doc.to_dict() for doc in query.limit(500).stream()]
    # Client-side filtering for additional criteria
    if file_type and vendor_id:
        results = [r for r in results if r.get("vendor_id") == vendor_id]
    if file_type and status:
        results = [r for r in results if r.get("status") == status]
    results.sort(key=lambda r: r.get("ingested_at", ""), reverse=True)
    return results[:limit]


def list_recent_files(limit: int = 30) -> list[dict[str, Any]]:
    query = (
        _db()
        .collection("wechat_files")
        .order_by("ingested_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [doc.to_dict() for doc in query.stream()]


def count_files() -> int:
    """Return total count of wechat_files documents."""
    return len(list(_db().collection("wechat_files").select([]).stream()))


# ---------------------------------------------------------------------------
# wechat_products collection (Phase 2)
# ---------------------------------------------------------------------------

def upsert_product(product: WeChatProduct) -> str:
    product.updated_at = datetime.now(timezone.utc)
    doc_ref = _db().collection("wechat_products").document()
    doc_ref.set(product.model_dump(mode="json"))
    return doc_ref.id


def search_products(
    vendor_id: str = "",
    category: str = "",
    search_text: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = _db().collection("wechat_products")
    if vendor_id:
        query = query.where("vendor_id", "==", vendor_id)
    if category:
        query = query.where("category", "==", category)
    query = query.limit(limit)
    results = [doc.to_dict() for doc in query.stream()]
    if search_text:
        search_lower = search_text.lower()
        results = [
            r for r in results
            if search_lower in r.get("product_name", "").lower()
            or search_lower in r.get("description", "").lower()
        ]
    return results


# ---------------------------------------------------------------------------
# wechat_contact_mapping collection
# ---------------------------------------------------------------------------

def get_contact_mapping(contact_hash: str) -> WeChatContactMapping | None:
    doc = _db().collection("wechat_contact_mapping").document(contact_hash).get()
    if doc.exists:
        return WeChatContactMapping(**doc.to_dict())
    return None


def upsert_contact_mapping(mapping: WeChatContactMapping) -> None:
    mapping.updated_at = datetime.now(timezone.utc)
    _db().collection("wechat_contact_mapping").document(mapping.contact_hash).set(
        mapping.model_dump(mode="json")
    )


def list_contact_mappings() -> list[dict[str, Any]]:
    return [doc.to_dict() for doc in _db().collection("wechat_contact_mapping").stream()]


# ---------------------------------------------------------------------------
# ingestion_log collection
# ---------------------------------------------------------------------------

def log_event(event: IngestionEvent) -> None:
    _db().collection("ingestion_log").document().set(
        event.model_dump(mode="json")
    )


# ---------------------------------------------------------------------------
# wechat_vendors collection
# ---------------------------------------------------------------------------

def upsert_vendor(vendor: WeChatVendor) -> None:
    vendor.updated_at = datetime.now(timezone.utc)
    _db().collection("wechat_vendors").document(vendor.vendor_id).set(
        vendor.model_dump(mode="json")
    )


def get_vendor(vendor_id: str) -> WeChatVendor | None:
    doc = _db().collection("wechat_vendors").document(vendor_id).get()
    if doc.exists:
        return WeChatVendor(**doc.to_dict())
    return None


def list_vendors(limit: int = 200) -> list[dict[str, Any]]:
    return [
        doc.to_dict()
        for doc in _db().collection("wechat_vendors")
        .order_by("file_count", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    ]


# ---------------------------------------------------------------------------
# sync_status collection
# ---------------------------------------------------------------------------

def upsert_sync_status(status: SyncStatus) -> None:
    _db().collection("sync_status").document("latest").set(
        status.model_dump(mode="json")
    )
    # Also write history entry
    _db().collection("sync_status").document(status.sync_id).set(
        status.model_dump(mode="json")
    )


def get_sync_status() -> SyncStatus | None:
    doc = _db().collection("sync_status").document("latest").get()
    if doc.exists:
        return SyncStatus(**doc.to_dict())
    return None


# ---------------------------------------------------------------------------
# Cross-DB reads (shipping-automation, default)
# ---------------------------------------------------------------------------

def get_go_vendors(limit: int = 200) -> list[dict[str, Any]]:
    """Read go_vendors from shipping-automation DB."""
    return [
        doc.to_dict() | {"_doc_id": doc.id}
        for doc in shipping_db().collection("go_vendors").limit(limit).stream()
    ]


def get_people_contacts(limit: int = 500) -> list[dict[str, Any]]:
    """Read people_contacts from default DB."""
    return [
        doc.to_dict() | {"_doc_id": doc.id}
        for doc in default_db().collection("people_contacts").limit(limit).stream()
    ]
