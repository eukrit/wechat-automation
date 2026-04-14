"""Extract products from any file type using Gemini 2.5 Flash via Vertex AI.

Uses GCP Service Account (GOOGLE_APPLICATION_CREDENTIALS) — no API key needed.
Project: ai-agents-go, Region: asia-southeast1.

Handles: PDF, PPTX, DOCX, images (JPG/PNG/WEBP/BMP/GIF).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from wechat_automation.models import WeChatProduct

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"
GCP_PROJECT = "ai-agents-go"
GCP_LOCATION = "asia-southeast1"

# MIME types for Vertex AI
_MIME_MAP = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "gif": "image/gif",
}

_EXTRACTION_PROMPT = """You are a product data extractor for a procurement company. Analyze this document thoroughly and extract ALL products, items, or line items shown.

For each product found, return a JSON object with these fields:
- "product_name": product name (English preferred, include Chinese name if bilingual)
- "sku": model number, SKU, item code, or catalog number
- "description": brief description of the product
- "dimensions": size/dimensions if shown (e.g., "1200x600x400mm")
- "material": material composition if shown
- "unit_price": numeric price only (no currency symbol). Use 0 if not shown.
- "currency": "USD", "CNY", "EUR", or "THB" (default "CNY" for Chinese documents)
- "category": product category (e.g., "Lighting", "Furniture", "Playground Equipment", "Flooring", "Hardware")
- "weight_kg": weight in kg if shown, else 0
- "moq": minimum order quantity if shown, else 0
- "color": color/finish if shown

Return a JSON array of these objects. Extract EVERY product visible — catalogs may have many items per page.
If the document contains no products (e.g., shipping docs, certificates), return: []

Return ONLY the JSON array, no other text."""

_initialized = False


def _init_vertex():
    """Initialize Vertex AI once."""
    global _initialized
    if _initialized:
        return
    import vertexai
    vertexai.init(project=GCP_PROJECT, location=GCP_LOCATION)
    _initialized = True


def extract_products_gemini(
    filepath: str | Path,
    source_file_id: str = "",
    vendor_id: str = "",
    vendor_name: str = "",
) -> list[WeChatProduct]:
    """Extract products from any supported file using Gemini 2.5 Flash via Vertex AI."""
    from vertexai.generative_models import GenerativeModel, Part

    path = Path(filepath)
    if not path.exists():
        logger.warning("File not found: %s", path)
        return []

    ext = path.suffix.lstrip(".").lower()
    mime_type = _MIME_MAP.get(ext)
    if not mime_type:
        logger.debug("Unsupported extension for Gemini: .%s", ext)
        return []

    file_size_mb = path.stat().st_size / (1024 * 1024)

    # Oversized PDFs (>50MB): split into chunks and process each
    if ext == "pdf" and file_size_mb > 45:
        return _extract_chunked_pdf(
            path, file_size_mb, source_file_id, vendor_id, vendor_name,
        )

    _init_vertex()
    model = GenerativeModel(MODEL_NAME)

    try:
        logger.info("Gemini processing %s (%.0fMB)...", path.name, file_size_mb)

        if file_size_mb > 20:
            file_part = _upload_via_gcs(path, mime_type)
        else:
            file_bytes = path.read_bytes()
            file_part = Part.from_data(data=file_bytes, mime_type=mime_type)

        context = f"Vendor: {vendor_name}\n" if vendor_name else ""
        prompt = f"""{context}Analyze this document and extract all products.

{_EXTRACTION_PROMPT}"""

        response = model.generate_content(
            [file_part, prompt],
            generation_config={"temperature": 0.1, "max_output_tokens": 65536},
        )

        products = []
        if response.text:
            products = _parse_gemini_response(
                response.text,
                source_file_id=source_file_id,
                source_filename=path.name,
                vendor_id=vendor_id,
                vendor_name=vendor_name,
            )

        if file_size_mb > 20:
            _cleanup_gcs_temp(path.name)

        logger.info("Gemini extracted %d products from %s", len(products), path.name)
        return products

    except Exception as e:
        logger.error("Gemini extraction failed for %s: %s", path.name, e)
        if file_size_mb > 20:
            _cleanup_gcs_temp(path.name)
        return []


def _extract_chunked_pdf(
    filepath: Path,
    file_size_mb: float,
    source_file_id: str,
    vendor_id: str,
    vendor_name: str,
    max_pages_per_chunk: int = 30,
) -> list[WeChatProduct]:
    """Split a large PDF into chunks, send each to Gemini, merge results."""
    import tempfile
    from pypdf import PdfReader, PdfWriter
    from vertexai.generative_models import GenerativeModel, Part

    _init_vertex()
    model = GenerativeModel(MODEL_NAME)

    try:
        reader = PdfReader(str(filepath))
        total_pages = len(reader.pages)
    except Exception as e:
        logger.error("Cannot read PDF %s: %s", filepath.name, e)
        return []

    logger.info("Splitting %s (%.0fMB, %d pages) into chunks of %d pages...",
                filepath.name, file_size_mb, total_pages, max_pages_per_chunk)

    all_products: list[WeChatProduct] = []
    chunk_num = 0

    for start in range(0, total_pages, max_pages_per_chunk):
        end = min(start + max_pages_per_chunk, total_pages)
        chunk_num += 1

        # Write chunk to temp file
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            writer.write(tmp)
            tmp_path = Path(tmp.name)

        chunk_size_mb = tmp_path.stat().st_size / (1024 * 1024)
        logger.info("  Chunk %d: pages %d-%d (%.0fMB)", chunk_num, start + 1, end, chunk_size_mb)

        try:
            # Upload chunk to GCS
            if chunk_size_mb > 20:
                chunk_name = f"{filepath.stem}_chunk{chunk_num}.pdf"
                file_part = _upload_via_gcs(tmp_path, "application/pdf", gcs_name=chunk_name)
            else:
                file_part = Part.from_data(data=tmp_path.read_bytes(), mime_type="application/pdf")

            context = f"Vendor: {vendor_name}\n" if vendor_name else ""
            prompt = f"""{context}Analyze this catalog chunk (pages {start+1}-{end} of {total_pages}) and extract all products.

{_EXTRACTION_PROMPT}"""

            response = model.generate_content(
                [file_part, prompt],
                generation_config={"temperature": 0.1, "max_output_tokens": 65536},
            )

            if response.text:
                products = _parse_gemini_response(
                    response.text,
                    source_file_id=source_file_id,
                    source_filename=filepath.name,
                    vendor_id=vendor_id,
                    vendor_name=vendor_name,
                )
                all_products.extend(products)
                logger.info("    -> %d products from chunk %d", len(products), chunk_num)

            if chunk_size_mb > 20:
                _cleanup_gcs_temp(f"{filepath.stem}_chunk{chunk_num}.pdf")

        except Exception as e:
            logger.error("    Chunk %d failed: %s", chunk_num, e)
        finally:
            tmp_path.unlink(missing_ok=True)

    logger.info("Gemini extracted %d total products from %s (%d chunks)",
                len(all_products), filepath.name, chunk_num)
    return all_products


_GCS_BUCKET = "wechat-documents-attachments"


def _upload_via_gcs(filepath: Path, mime_type: str, gcs_name: str = ""):
    """Upload large file to GCS temp location, return Vertex AI Part referencing it."""
    from google.cloud import storage
    from vertexai.generative_models import Part

    gcs_path = f"_gemini_temp/{gcs_name or filepath.name}"
    client = storage.Client(project=GCP_PROJECT)
    blob = client.bucket(_GCS_BUCKET).blob(gcs_path)

    logger.info("Uploading %s to GCS for Gemini (%.0fMB)...", filepath.name, filepath.stat().st_size / 1024 / 1024)
    blob.upload_from_filename(str(filepath), content_type=mime_type)

    return Part.from_uri(uri=f"gs://{_GCS_BUCKET}/{gcs_path}", mime_type=mime_type)


def _cleanup_gcs_temp(filename: str) -> None:
    """Delete temp file from GCS after Gemini processing."""
    try:
        from google.cloud import storage
        client = storage.Client(project=GCP_PROJECT)
        client.bucket(_GCS_BUCKET).blob(f"_gemini_temp/{filename}").delete()
    except Exception:
        pass


def _parse_gemini_response(
    text: str,
    source_file_id: str,
    source_filename: str,
    vendor_id: str,
    vendor_name: str,
) -> list[WeChatProduct]:
    """Parse Gemini's JSON response into WeChatProduct objects."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                items = json.loads(match.group())
            except json.JSONDecodeError:
                logger.warning("Could not parse Gemini response as JSON for %s", source_filename)
                return []
        else:
            return []

    if not isinstance(items, list):
        return []

    products: list[WeChatProduct] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        name = str(item.get("product_name", "") or item.get("name", ""))
        sku = str(item.get("sku", "") or item.get("model", ""))
        if not name and not sku:
            continue

        price = 0.0
        try:
            price = float(item.get("unit_price", 0) or 0)
        except (ValueError, TypeError):
            pass

        weight = 0.0
        try:
            weight = float(item.get("weight_kg", 0) or 0)
        except (ValueError, TypeError):
            pass

        moq = 0
        try:
            moq = int(float(item.get("moq", 0) or 0))
        except (ValueError, TypeError):
            pass

        products.append(WeChatProduct(
            product_name=name,
            product_name_zh=name if re.search(r"[\u4e00-\u9fff]", name) else "",
            source_file_id=source_file_id,
            source_filename=source_filename,
            source_page=0,
            sku=sku,
            description=str(item.get("description", "")),
            category=str(item.get("category", "")),
            material=str(item.get("material", "")),
            dimensions=str(item.get("dimensions", "")),
            weight_kg=weight,
            color=str(item.get("color", "")),
            unit_price=price,
            currency=str(item.get("currency", "CNY")),
            moq=moq,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            extraction_method="gemini_vision",
            extraction_confidence=0.7,
        ))

    return products
