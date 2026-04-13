"""Extract products from any file type using Gemini 2.5 Flash.

Handles: PDF, PPTX, DOCX, images (JPG/PNG), Excel (as fallback).
Gemini 2.5 Flash: best balance of speed, cost, and quality for structured extraction.
- Input: $0.15/1M tokens
- Output: $0.60/1M tokens
- Supports native PDF/image upload via File API
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from wechat_automation.models import WeChatProduct

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"

# MIME types for Gemini File API upload
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


def extract_products_gemini(
    filepath: str | Path,
    source_file_id: str = "",
    vendor_id: str = "",
    vendor_name: str = "",
    max_pages: int = 50,
) -> list[WeChatProduct]:
    """Extract products from any supported file using Gemini 2.5 Flash.

    Supports: PDF, PPTX, DOCX, DOC, images (JPG/PNG/WEBP/BMP/GIF).
    """
    try:
        import google.generativeai as genai
    except ImportError:
        logger.error("google-generativeai not installed")
        return []

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

    # Gemini File API limit is 2GB, but very large files take longer
    if file_size_mb > 700:
        logger.warning("File too large for Gemini (%dMB): %s", int(file_size_mb), path.name)
        return []

    model = genai.GenerativeModel(MODEL_NAME)

    try:
        # Upload file to Gemini
        logger.info("Uploading %s (%.0fMB) to Gemini...", path.name, file_size_mb)
        uploaded = genai.upload_file(path, mime_type=mime_type)

        # Wait for file to be processed (large files need time)
        _wait_for_file(genai, uploaded)

        # Build prompt
        context = f"Vendor: {vendor_name}\n" if vendor_name else ""
        prompt = f"""{context}Analyze this document and extract all products.

{_EXTRACTION_PROMPT}"""

        response = model.generate_content(
            [uploaded, prompt],
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

        # Clean up
        try:
            genai.delete_file(uploaded.name)
        except Exception:
            pass

        logger.info("Gemini extracted %d products from %s (%.0fMB)", len(products), path.name, file_size_mb)
        return products

    except Exception as e:
        logger.error("Gemini extraction failed for %s: %s", path.name, e)
        return []


def _wait_for_file(genai, uploaded, timeout: int = 120) -> None:
    """Wait for Gemini File API to finish processing the uploaded file."""
    start = time.time()
    while time.time() - start < timeout:
        f = genai.get_file(uploaded.name)
        if f.state.name == "ACTIVE":
            return
        if f.state.name == "FAILED":
            raise RuntimeError(f"File processing failed: {uploaded.name}")
        time.sleep(2)
    raise TimeoutError(f"File processing timed out after {timeout}s: {uploaded.name}")


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
