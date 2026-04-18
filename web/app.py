"""FastAPI web app for browsing/searching WeChat products.

Deployed to Cloud Run at asia-southeast1.
Reads from wechat-documents Firestore DB.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Add parent for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.cloud import firestore, storage
from google.cloud.firestore_v1.base_query import FieldFilter

PROJECT = os.environ.get("GCP_PROJECT_ID", "ai-agents-go")
DATABASE = os.environ.get("FIRESTORE_DATABASE", "wechat-documents")
BUCKET = os.environ.get("GCS_BUCKET", "wechat-documents-attachments")

app = FastAPI(title="WeChat Products Browser")
web_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(web_dir / "templates"))

_db_cache: dict[str, firestore.Client] = {}


def db() -> firestore.Client:
    if DATABASE not in _db_cache:
        _db_cache[DATABASE] = firestore.Client(project=PROJECT, database=DATABASE)
    return _db_cache[DATABASE]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main browse/search page."""
    # Get aggregate stats
    vendors = [d.to_dict() for d in db().collection("wechat_vendors").order_by(
        "product_count", direction=firestore.Query.DESCENDING
    ).limit(100).stream()]

    # Distinct categories from products
    categories_set = set()
    subcategories_set = set()
    for v in vendors:
        for c in v.get("categories", []):
            if c and c.strip():
                categories_set.add(c.strip())
        for sc in v.get("subcategories", []):
            if sc and sc.strip():
                subcategories_set.add(sc.strip())

    return templates.TemplateResponse("index.html", {
        "request": request,
        "vendors": vendors,
        "categories": sorted(categories_set),
        "subcategories": sorted(subcategories_set),
        "total_vendors": len(vendors),
    })


@app.get("/api/products")
async def search_products(
    q: str = "",
    vendor: str = "",
    category: str = "",
    subcategory: str = "",
    min_price: float = 0,
    max_price: float = 0,
    currency: str = "",
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    """Search products with filters. Returns JSON."""
    query = db().collection("wechat_products")

    # Firestore allows only one inequality + equality filters
    # Prefer equality filters for speed
    if vendor:
        query = query.where(filter=FieldFilter("vendor_name", "==", vendor))
    elif category:
        query = query.where(filter=FieldFilter("category", "==", category))
    elif subcategory:
        query = query.where(filter=FieldFilter("subcategory", "==", subcategory))
    elif currency:
        query = query.where(filter=FieldFilter("currency", "==", currency))

    # Pull more than limit to allow client-side secondary filtering
    results = [doc.to_dict() for doc in query.limit(2000).stream()]

    # Client-side filters
    q_lower = q.lower()
    filtered = []
    for p in results:
        if vendor and p.get("vendor_name") != vendor:
            continue
        if category and p.get("category") != category:
            continue
        if subcategory and p.get("subcategory") != subcategory:
            continue
        if currency and p.get("currency") != currency:
            continue
        if min_price > 0 and p.get("unit_price", 0) < min_price:
            continue
        if max_price > 0 and p.get("unit_price", 0) > max_price:
            continue
        if q_lower:
            blob = " ".join([
                str(p.get("product_name", "")),
                str(p.get("sku", "")),
                str(p.get("description", "")),
                str(p.get("material", "")),
                str(p.get("dimensions", "")),
            ]).lower()
            if q_lower not in blob:
                continue
        filtered.append(p)

    total = len(filtered)
    page = filtered[offset:offset + limit]

    return JSONResponse({
        "total": total,
        "offset": offset,
        "limit": limit,
        "products": page,
    })


@app.get("/api/vendors")
async def list_vendors():
    """List all vendors with file/product counts."""
    vendors = [d.to_dict() for d in db().collection("wechat_vendors").order_by(
        "product_count", direction=firestore.Query.DESCENDING
    ).stream()]
    return JSONResponse({"vendors": vendors})


@app.get("/api/vendor/{vendor_id}")
async def get_vendor(vendor_id: str):
    """Get details for a single vendor including their files."""
    doc = db().collection("wechat_vendors").document(vendor_id).get()
    if not doc.exists:
        return JSONResponse({"error": "Vendor not found"}, status_code=404)
    vendor = doc.to_dict()

    # Load file details
    file_ids = vendor.get("file_ids", [])[:50]
    files = []
    for fid in file_ids:
        f_doc = db().collection("wechat_files").document(fid).get()
        if f_doc.exists:
            files.append(f_doc.to_dict())
    vendor["files"] = files

    return JSONResponse(vendor)


@app.get("/api/file/{file_id}/download")
async def get_file_url(file_id: str):
    """Get signed GCS URL for downloading a file."""
    from datetime import timedelta
    doc = db().collection("wechat_files").document(file_id).get()
    if not doc.exists:
        return JSONResponse({"error": "File not found"}, status_code=404)

    file_data = doc.to_dict()
    gcs_path = file_data.get("gcs_path", "")
    if not gcs_path:
        return JSONResponse({"error": "No GCS path"}, status_code=404)

    # Strip gs://bucket/ prefix
    blob_name = gcs_path.replace(f"gs://{BUCKET}/", "")
    client = storage.Client(project=PROJECT)
    blob = client.bucket(BUCKET).blob(blob_name)

    try:
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=1),
            method="GET",
        )
        return JSONResponse({"url": url, "filename": file_data.get("filename", "")})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/stats")
async def stats():
    """Return aggregate stats."""
    vendors = [d.to_dict() for d in db().collection("wechat_vendors").stream()]
    total_files = sum(v.get("file_count", 0) for v in vendors)
    total_products = sum(v.get("product_count", 0) for v in vendors)

    return JSONResponse({
        "total_vendors": len(vendors),
        "total_files": total_files,
        "total_products": total_products,
    })


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
