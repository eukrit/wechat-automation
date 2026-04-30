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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Add parent for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.cloud import firestore, storage
from google.cloud.firestore_v1.base_query import FieldFilter

PROJECT = os.environ.get("GCP_PROJECT_ID", "ai-agents-go")
DATABASE = os.environ.get("FIRESTORE_DATABASE", "wechat-documents")
BUCKET = os.environ.get("GCS_BUCKET", "wechat-documents-attachments")

app = FastAPI(title="WeChat Products Browser", docs_url=None, redoc_url=None)
web_dir = Path(__file__).parent

# Serve consolidated static docs hub at /docs/*
_static_dir = web_dir / "static"
if _static_dir.exists():
    app.mount("/docs", StaticFiles(directory=str(_static_dir / "docs"), html=True), name="docs")


@app.get("/hub")
async def hub_redirect():
    """Short alias for the docs hub landing page."""
    return RedirectResponse(url="/docs/")

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


_filter_cache: dict = {}
_filter_cache_ts: float = 0


@app.get("/api/filters")
async def get_filters():
    """Return filter options with cross-reference metadata for interactive filtering.

    - vendors: [{name, product_count, categories: [...]}]
    - categories: [str]
    - subcategories: [{name, category, vendor_names: [...]}]
    - category_to_vendors: {category: [vendor_name]}
    - vendor_to_subcategories: {vendor_name: [subcategory]}
    """
    import time
    global _filter_cache, _filter_cache_ts

    # 5-minute in-memory cache
    if _filter_cache and time.time() - _filter_cache_ts < 300:
        return JSONResponse(_filter_cache)

    # Build from vendors collection (pre-aggregated)
    vendors_list = []
    category_to_vendors: dict[str, set] = {}
    vendor_to_subcategories: dict[str, set] = {}
    vendor_to_categories: dict[str, set] = {}
    subcategory_to_categories: dict[str, set] = {}
    subcategory_to_vendors: dict[str, set] = {}
    categories_set = set()

    for doc in db().collection("wechat_vendors").order_by(
        "product_count", direction=firestore.Query.DESCENDING
    ).stream():
        v = doc.to_dict()
        name = str(v.get("vendor_name", "")).strip()
        if not name:
            continue

        vendor_cats = [str(c).strip() for c in v.get("categories", []) if isinstance(c, str) and c.strip()]
        vendor_subs = [str(s).strip() for s in v.get("subcategories", []) if isinstance(s, str) and s.strip()]

        vendors_list.append({
            "vendor_name": name,
            "product_count": int(v.get("product_count", 0) or 0),
            "file_count": int(v.get("file_count", 0) or 0),
            "categories": vendor_cats,
            "subcategories": vendor_subs,
        })

        vendor_to_categories[name] = set(vendor_cats)
        vendor_to_subcategories[name] = set(vendor_subs)
        for c in vendor_cats:
            categories_set.add(c)
            category_to_vendors.setdefault(c, set()).add(name)
        for s in vendor_subs:
            subcategory_to_vendors.setdefault(s, set()).add(name)

    # Build subcategory -> category lookup from products (sample 1 product per subcategory)
    # This is approximate — a subcategory might appear in multiple categories
    from google.cloud.firestore_v1.base_query import FieldFilter
    for sub in subcategory_to_vendors.keys():
        try:
            result = db().collection("wechat_products").where(
                filter=FieldFilter("subcategory", "==", sub)
            ).limit(1).stream()
            for p in result:
                cat = p.to_dict().get("category", "").strip()
                if cat:
                    subcategory_to_categories.setdefault(sub, set()).add(cat)
                break
        except Exception:
            pass

    response = {
        "vendors": vendors_list,
        "categories": sorted(categories_set),
        "subcategories": sorted(subcategory_to_vendors.keys()),
        "category_to_vendors": {k: sorted(v) for k, v in category_to_vendors.items()},
        "vendor_to_categories": {k: sorted(v) for k, v in vendor_to_categories.items()},
        "vendor_to_subcategories": {k: sorted(v) for k, v in vendor_to_subcategories.items()},
        "subcategory_to_category": {k: (sorted(v)[0] if v else "") for k, v in subcategory_to_categories.items()},
        "subcategory_to_vendors": {k: sorted(v) for k, v in subcategory_to_vendors.items()},
    }

    _filter_cache = response
    _filter_cache_ts = time.time()
    return JSONResponse(response)


@app.get("/api/products")
async def search_products(
    q: str = "",
    vendor: str = "",
    category: str = "",
    subcategory: str = "",
    min_price: float = 0,
    max_price: float = 0,
    currency: str = "",
    sort: str = "relevance",
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    """Search products with filters + sort. Returns JSON.

    sort: relevance (default) | name_asc | name_desc | vendor_asc | vendor_desc |
          price_asc | price_desc | newest | sku
    """
    query = db().collection("wechat_products")

    if vendor:
        query = query.where(filter=FieldFilter("vendor_name", "==", vendor))
    elif category:
        query = query.where(filter=FieldFilter("category", "==", category))
    elif subcategory:
        query = query.where(filter=FieldFilter("subcategory", "==", subcategory))
    elif currency:
        query = query.where(filter=FieldFilter("currency", "==", currency))

    results = [doc.to_dict() for doc in query.limit(5000).stream()]

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

    # Sort
    def _safe_price(p):
        try:
            return float(p.get("unit_price") or 0)
        except (TypeError, ValueError):
            return 0.0

    if sort == "name_asc":
        filtered.sort(key=lambda p: str(p.get("product_name", "")).lower())
    elif sort == "name_desc":
        filtered.sort(key=lambda p: str(p.get("product_name", "")).lower(), reverse=True)
    elif sort == "vendor_asc":
        filtered.sort(key=lambda p: (str(p.get("vendor_name", "")).lower(), str(p.get("product_name", "")).lower()))
    elif sort == "vendor_desc":
        filtered.sort(key=lambda p: (str(p.get("vendor_name", "")).lower(), str(p.get("product_name", "")).lower()), reverse=True)
    elif sort == "price_asc":
        filtered.sort(key=lambda p: (_safe_price(p) if _safe_price(p) > 0 else float('inf')))
    elif sort == "price_desc":
        filtered.sort(key=lambda p: _safe_price(p), reverse=True)
    elif sort == "newest":
        filtered.sort(key=lambda p: str(p.get("extracted_at", "") or p.get("created_at", "")), reverse=True)
    elif sort == "sku":
        filtered.sort(key=lambda p: str(p.get("sku", "")).lower())
    # else relevance: keep Firestore default order

    total = len(filtered)
    page = filtered[offset:offset + limit]

    return JSONResponse({
        "total": total,
        "offset": offset,
        "limit": limit,
        "sort": sort,
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
async def get_preview(file_id: str, page: int = 1, size: str = "thumb"):
    """Render and stream a thumbnail (size=thumb, 400px) or large preview (size=large, 1200px).

    Caches both resolutions separately in GCS.
    """
    from fastapi.responses import Response

    # Size: 'thumb' = 400px, 'large' = 1200px
    max_width = 1200 if size == "large" else 400

    doc = db().collection("wechat_files").document(file_id).get()
    if not doc.exists:
        return JSONResponse({"error": "File not found"}, status_code=404)

    file_data = doc.to_dict()
    gcs_path = file_data.get("gcs_path", "")
    ext = file_data.get("file_extension", "").lower()

    if not gcs_path:
        return JSONResponse({"error": "No source file"}, status_code=404)

    thumb_name = f"_thumbnails/{file_id}_p{page}_{size}.jpg"
    client = storage.Client(project=PROJECT)
    bucket = client.bucket(BUCKET)
    thumb_blob = bucket.blob(thumb_name)

    if thumb_blob.exists():
        return Response(
            content=thumb_blob.download_as_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    file_size = int(file_data.get("file_size_bytes", 0) or 0)
    if file_size > 200 * 1024 * 1024:
        placeholder = _generate_placeholder(f"{file_data.get('category','Large File')}")
        return Response(content=placeholder, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=3600"})

    source_blob_name = gcs_path.replace(f"gs://{BUCKET}/", "")
    source_blob = bucket.blob(source_blob_name)

    try:
        if ext == "pdf":
            thumb_bytes = _render_pdf_page(source_blob, page, max_width=max_width)
        elif ext in ("jpg", "jpeg", "png", "webp"):
            thumb_bytes = _resize_image(source_blob, max_width=max_width)
        elif ext == "xlsx":
            thumb_bytes = _render_xlsx_preview(source_blob, max_width=max_width)
        elif ext == "pptx":
            thumb_bytes = _render_pptx_slide(source_blob, page, max_width=max_width)
        else:
            thumb_bytes = _generate_placeholder(ext.upper())

        if not thumb_bytes:
            thumb_bytes = _generate_placeholder(file_data.get("file_type", "Document"))

        try:
            thumb_blob.upload_from_string(thumb_bytes, content_type="image/jpeg")
        except Exception:
            pass
        return Response(
            content=thumb_bytes,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception as e:
        placeholder = _generate_placeholder(file_data.get("file_type", "Preview Error"))
        return Response(content=placeholder, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=300"})


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
    import fitz

    pdf_bytes = blob.download_as_bytes()
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_idx = min(max(page_num - 1, 0), len(pdf_doc) - 1)
    page_obj = pdf_doc[page_idx]

    # Render at zoom that gets us close to target, then resize
    zoom = 3.0 if max_width > 600 else 2.0
    pix = page_obj.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img_bytes = pix.tobytes("jpeg", jpg_quality=85)

    from PIL import Image
    img = Image.open(io.BytesIO(img_bytes))
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    pdf_doc.close()
    return out.getvalue()


def _render_xlsx_preview(blob, max_width: int = 400) -> bytes:
    """Extract first embedded image from xlsx, or generate a text preview."""
    import io
    from zipfile import ZipFile

    xlsx_bytes = blob.download_as_bytes()
    try:
        with ZipFile(io.BytesIO(xlsx_bytes)) as z:
            for name in z.namelist():
                if name.startswith("xl/media/") and name.lower().endswith((".jpg", ".jpeg", ".png")):
                    img_data = z.read(name)
                    from PIL import Image
                    img = Image.open(io.BytesIO(img_data)).convert("RGB")
                    if img.width > max_width:
                        ratio = max_width / img.width
                        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
                    out = io.BytesIO()
                    img.save(out, format="JPEG", quality=85)
                    return out.getvalue()
    except Exception:
        pass

    return _generate_placeholder("Spreadsheet")


def _render_pptx_slide(blob, slide_num: int, max_width: int = 400) -> bytes:
    """Extract slide image from pptx."""
    import io
    from zipfile import ZipFile

    pptx_bytes = blob.download_as_bytes()
    try:
        with ZipFile(io.BytesIO(pptx_bytes)) as z:
            media_files = sorted([n for n in z.namelist() if n.startswith("ppt/media/") and n.lower().endswith((".jpg", ".jpeg", ".png"))])
            if media_files:
                idx = min(max(slide_num - 1, 0), len(media_files) - 1)
                img_data = z.read(media_files[idx])
                from PIL import Image
                img = Image.open(io.BytesIO(img_data)).convert("RGB")
                if img.width > max_width:
                    ratio = max_width / img.width
                    img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
                out = io.BytesIO()
                img.save(out, format="JPEG", quality=85)
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


@app.get("/sync-report", response_class=HTMLResponse)
async def sync_report():
    """HTML report: recent sync runs, file status breakdown, tail of sync.log."""
    from collections import Counter
    from datetime import datetime, timezone
    import html as _html

    runs = []
    try:
        q = (
            db().collection("sync_status")
            .order_by("started_at", direction=firestore.Query.DESCENDING)
            .limit(20)
        )
        for d in q.stream():
            runs.append(d.to_dict())
    except Exception as e:
        runs = [{"error": str(e)}]

    status_counts: Counter = Counter()
    type_counts: Counter = Counter()
    ext_counts: Counter = Counter()
    total = 0
    for d in db().collection("wechat_files").stream():
        f = d.to_dict()
        status_counts[f.get("status", "unknown")] += 1
        type_counts[f.get("file_type", "other")] += 1
        ext_counts[f.get("file_extension", "") or "(none)"] += 1
        total += 1

    log_tail = ""
    log_path = Path(os.path.expanduser("~")) / ".wechat-automation" / "sync.log"
    if log_path.exists():
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()[-200:]
            log_tail = "".join(lines)
        except Exception as e:
            log_tail = f"(error reading log: {e})"

    def _fmt_dt(v):
        if not v:
            return ""
        if isinstance(v, datetime):
            return v.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return str(v)

    rows = []
    for r in runs:
        if "error" in r:
            rows.append(f"<tr><td colspan='8'>Error: {_html.escape(r['error'])}</td></tr>")
            continue
        rows.append(
            "<tr>"
            f"<td>{_html.escape(r.get('sync_id',''))}</td>"
            f"<td>{_html.escape(r.get('status',''))}</td>"
            f"<td>{_fmt_dt(r.get('started_at'))}</td>"
            f"<td>{_fmt_dt(r.get('completed_at'))}</td>"
            f"<td style='text-align:right'>{r.get('files_new',0)}</td>"
            f"<td style='text-align:right'>{r.get('files_extracted',0)}</td>"
            f"<td style='text-align:right'>{r.get('products_new',0)}</td>"
            f"<td style='text-align:right'>{r.get('extraction_errors',0)}</td>"
            "</tr>"
        )
    runs_table = "\n".join(rows) or "<tr><td colspan='8'>No runs yet</td></tr>"

    def _counter_table(c: Counter) -> str:
        items = sorted(c.items(), key=lambda kv: -kv[1])
        return "\n".join(
            f"<tr><td>{_html.escape(str(k))}</td><td style='text-align:right'>{v}</td></tr>"
            for k, v in items
        )

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>WeChat Sync Report</title>
<style>
 body {{ font-family: -apple-system, Segoe UI, sans-serif; margin: 24px; color:#222; }}
 h1 {{ margin-top: 0; }}
 h2 {{ margin-top: 32px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
 table {{ border-collapse: collapse; margin-bottom: 16px; }}
 th, td {{ border: 1px solid #ddd; padding: 6px 10px; font-size: 13px; }}
 th {{ background: #f4f4f4; text-align: left; }}
 .grid {{ display: grid; grid-template-columns: repeat(3, minmax(240px, 1fr)); gap: 16px; }}
 pre {{ background: #0e1116; color: #d4d4d4; padding: 12px; border-radius: 6px;
        max-height: 500px; overflow: auto; font-size: 12px; white-space: pre-wrap; }}
 .kpi {{ display: inline-block; margin-right: 24px; padding: 12px 16px;
        background: #f7f7f9; border-radius: 8px; }}
 .kpi b {{ font-size: 22px; display: block; }}
</style></head><body>
<h1>WeChat Automation — Sync Report</h1>
<div>
  <span class="kpi"><b>{total}</b> total files</span>
  <span class="kpi"><b>{status_counts.get('product_extracted',0)}</b> extracted</span>
  <span class="kpi"><b>{status_counts.get('extraction_empty',0)}</b> empty</span>
  <span class="kpi"><b>{status_counts.get('extraction_failed',0)}</b> failed</span>
  <span class="kpi"><b>{status_counts.get('needs_vendor_link',0)}</b> need vendor</span>
</div>

<h2>Recent sync runs (last 20)</h2>
<table>
 <tr><th>sync_id</th><th>status</th><th>started</th><th>completed</th>
     <th>new files</th><th>extracted</th><th>products</th><th>errors</th></tr>
 {runs_table}
</table>

<h2>File breakdown</h2>
<div class="grid">
 <div><h3>By status</h3><table><tr><th>status</th><th>count</th></tr>{_counter_table(status_counts)}</table></div>
 <div><h3>By type</h3><table><tr><th>type</th><th>count</th></tr>{_counter_table(type_counts)}</table></div>
 <div><h3>By extension</h3><table><tr><th>ext</th><th>count</th></tr>{_counter_table(ext_counts)}</table></div>
</div>

<h2>sync.log (last 200 lines)</h2>
<pre>{_html.escape(log_tail) or '(log file not available in this environment)'}</pre>
</body></html>"""
    return HTMLResponse(html)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
