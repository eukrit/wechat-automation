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

# Add parent for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.cloud import firestore, storage
from google.cloud.firestore_v1.base_query import FieldFilter

PROJECT = os.environ.get("GCP_PROJECT_ID", "ai-agents-go")
DATABASE = os.environ.get("FIRESTORE_DATABASE", "wechat-documents")
BUCKET = os.environ.get("GCS_BUCKET", "wechat-documents-attachments")

app = FastAPI(title="WeChat Products Browser")
web_dir = Path(__file__).parent

_db_cache: dict[str, firestore.Client] = {}


def db() -> firestore.Client:
    if DATABASE not in _db_cache:
        _db_cache[DATABASE] = firestore.Client(project=PROJECT, database=DATABASE)
    return _db_cache[DATABASE]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main browse/search page. Returns minimal HTML — data loaded via AJAX."""
    html_path = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/filters")
async def get_filters():
    """Return all filter options: vendors, categories, subcategories."""
    vendors_list = []
    categories_set = set()
    subcategories_set = set()

    for doc in db().collection("wechat_vendors").order_by(
        "product_count", direction=firestore.Query.DESCENDING
    ).stream():
        v = doc.to_dict()
        name = str(v.get("vendor_name", "")).strip()
        if name:
            vendors_list.append({
                "vendor_name": name,
                "product_count": int(v.get("product_count", 0) or 0),
                "file_count": int(v.get("file_count", 0) or 0),
                "subcategories": [str(s) for s in v.get("subcategories", []) if s],
            })
        for c in v.get("categories", []):
            if isinstance(c, str) and c.strip():
                categories_set.add(c.strip())
        for sc in v.get("subcategories", []):
            if isinstance(sc, str) and sc.strip():
                subcategories_set.add(sc.strip())

    return JSONResponse({
        "vendors": vendors_list,
        "categories": sorted(categories_set),
        "subcategories": sorted(subcategories_set),
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


@app.get("/api/preview/{file_id}")
async def get_preview(file_id: str, page: int = 1):
    """Render and stream a thumbnail for a source file page.

    Caches rendered thumbnails in GCS and streams them to the client.
    """
    from fastapi.responses import Response

    doc = db().collection("wechat_files").document(file_id).get()
    if not doc.exists:
        return JSONResponse({"error": "File not found"}, status_code=404)

    file_data = doc.to_dict()
    gcs_path = file_data.get("gcs_path", "")
    ext = file_data.get("file_extension", "").lower()

    if not gcs_path:
        return JSONResponse({"error": "No source file"}, status_code=404)

    # Cached thumbnail path
    thumb_name = f"_thumbnails/{file_id}_p{page}.jpg"
    client = storage.Client(project=PROJECT)
    bucket = client.bucket(BUCKET)
    thumb_blob = bucket.blob(thumb_name)

    # If thumbnail exists, stream it
    if thumb_blob.exists():
        return Response(
            content=thumb_blob.download_as_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Otherwise render it
    source_blob_name = gcs_path.replace(f"gs://{BUCKET}/", "")
    source_blob = bucket.blob(source_blob_name)

    try:
        if ext == "pdf":
            thumb_bytes = _render_pdf_page(source_blob, page)
        elif ext in ("jpg", "jpeg", "png", "webp"):
            # Direct image: resize and stream
            thumb_bytes = _resize_image(source_blob)
        elif ext == "xlsx":
            thumb_bytes = _render_xlsx_preview(source_blob)
        elif ext == "pptx":
            thumb_bytes = _render_pptx_slide(source_blob, page)
        else:
            return JSONResponse({"error": f"preview not supported for .{ext}"}, status_code=415)

        if thumb_bytes:
            # Cache in GCS
            try:
                thumb_blob.upload_from_string(thumb_bytes, content_type="image/jpeg")
            except Exception:
                pass  # caching is best-effort
            return Response(
                content=thumb_bytes,
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=86400"},
            )
    except Exception as e:
        return JSONResponse({"error": f"rendering failed: {e}"}, status_code=500)

    return JSONResponse({"error": "no content"}, status_code=500)


def _resize_image(blob, max_width: int = 400) -> bytes:
    """Download and resize an image blob."""
    import io
    from PIL import Image
    img_bytes = blob.download_as_bytes()
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=75)
    return out.getvalue()


def _render_pdf_page(blob, page_num: int, max_width: int = 400) -> bytes:
    """Render a PDF page as JPEG bytes."""
    import io
    import fitz  # PyMuPDF

    pdf_bytes = blob.download_as_bytes()
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_idx = min(max(page_num - 1, 0), len(pdf_doc) - 1)
    page_obj = pdf_doc[page_idx]

    # Render at ~150 DPI, then resize
    pix = page_obj.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
    img_bytes = pix.tobytes("jpeg", jpg_quality=80)

    # Resize
    from PIL import Image
    img = Image.open(io.BytesIO(img_bytes))
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=75)
    pdf_doc.close()
    return out.getvalue()


def _render_xlsx_preview(blob) -> bytes:
    """Extract first embedded image from xlsx, or generate a text preview."""
    import io
    from zipfile import ZipFile

    xlsx_bytes = blob.download_as_bytes()
    try:
        with ZipFile(io.BytesIO(xlsx_bytes)) as z:
            # Find first image in xl/media/
            for name in z.namelist():
                if name.startswith("xl/media/") and name.lower().endswith((".jpg", ".jpeg", ".png")):
                    img_data = z.read(name)
                    from PIL import Image
                    img = Image.open(io.BytesIO(img_data)).convert("RGB")
                    max_w = 400
                    if img.width > max_w:
                        ratio = max_w / img.width
                        img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
                    out = io.BytesIO()
                    img.save(out, format="JPEG", quality=75)
                    return out.getvalue()
    except Exception:
        pass

    # Fallback: generate a placeholder
    return _generate_placeholder("Spreadsheet")


def _render_pptx_slide(blob, slide_num: int) -> bytes:
    """Extract slide image from pptx."""
    import io
    from zipfile import ZipFile

    pptx_bytes = blob.download_as_bytes()
    try:
        with ZipFile(io.BytesIO(pptx_bytes)) as z:
            # Try slide thumbnail first
            media_files = sorted([n for n in z.namelist() if n.startswith("ppt/media/") and n.lower().endswith((".jpg", ".jpeg", ".png"))])
            if media_files:
                idx = min(max(slide_num - 1, 0), len(media_files) - 1)
                img_data = z.read(media_files[idx])
                from PIL import Image
                img = Image.open(io.BytesIO(img_data)).convert("RGB")
                max_w = 400
                if img.width > max_w:
                    ratio = max_w / img.width
                    img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
                out = io.BytesIO()
                img.save(out, format="JPEG", quality=75)
                return out.getvalue()
    except Exception:
        pass

    return _generate_placeholder("Presentation")


def _generate_placeholder(text: str) -> bytes:
    """Generate a simple placeholder JPEG."""
    import io
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 300), (230, 240, 250))
    draw = ImageDraw.Draw(img)
    draw.text((180, 140), text, fill=(100, 120, 150))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=75)
    return out.getvalue()


@app.get("/api/file/{file_id}/download")
async def get_file_url(file_id: str):
    """Stream file directly from GCS (signed URLs don't work on Cloud Run without a key)."""
    from fastapi.responses import StreamingResponse
    import urllib.parse

    doc = db().collection("wechat_files").document(file_id).get()
    if not doc.exists:
        return JSONResponse({"error": "File not found"}, status_code=404)

    file_data = doc.to_dict()
    gcs_path = file_data.get("gcs_path", "")
    filename = file_data.get("filename", "download")
    content_type = file_data.get("content_type", "application/octet-stream")
    if not gcs_path:
        return JSONResponse({"error": "No GCS path"}, status_code=404)

    blob_name = gcs_path.replace(f"gs://{BUCKET}/", "")
    client = storage.Client(project=PROJECT)
    blob = client.bucket(BUCKET).blob(blob_name)

    def stream():
        with blob.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                yield chunk

    safe_name = urllib.parse.quote(filename)
    return StreamingResponse(
        stream(),
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )


@app.get("/api/stats")
async def stats():
    """Return aggregate stats - counts docs directly for accuracy."""
    vendors_count = db().collection("wechat_vendors").count().get()[0][0].value
    files_count = db().collection("wechat_files").count().get()[0][0].value
    products_count = db().collection("wechat_products").count().get()[0][0].value

    return JSONResponse({
        "total_vendors": vendors_count,
        "total_files": files_count,
        "total_products": products_count,
    })


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
