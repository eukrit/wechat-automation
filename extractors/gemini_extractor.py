"""Extract products from image-heavy PDFs using Gemini Vision.

Sends PDF pages as images to Gemini 2.5 Flash for structured product extraction.
Used as fallback when pdfplumber finds no usable tables.
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

_EXTRACTION_PROMPT = """You are a product data extractor. Analyze this catalog/price list page and extract all products shown.

For each product, return a JSON array with objects containing these fields:
- "product_name": product name (English preferred, include Chinese if bilingual)
- "sku": model number or SKU code
- "description": brief description
- "dimensions": size/dimensions if shown
- "material": material if shown
- "unit_price": numeric price (just the number, no currency symbol)
- "currency": "USD", "CNY", "EUR", or "THB"
- "category": product category (e.g., "Lighting", "Furniture", "Playground Equipment")

Only include products with at least a name or SKU. Skip headers, footers, and non-product content.
If no products are found on this page, return an empty array: []

Return ONLY the JSON array, no other text."""


def extract_products_gemini(
    filepath: str | Path,
    source_file_id: str = "",
    vendor_id: str = "",
    vendor_name: str = "",
    max_pages: int = 10,
    rate_limit_delay: float = 6.0,
) -> list[WeChatProduct]:
    """Extract products from a PDF using Gemini Vision.

    Args:
        max_pages: Maximum pages to process (to control API costs).
        rate_limit_delay: Seconds between API calls (10 req/min = 6s).
    """
    try:
        import google.generativeai as genai
    except ImportError:
        logger.error("google-generativeai not installed. Run: pip install google-generativeai")
        return []

    path = Path(filepath)
    if not path.exists():
        logger.warning("File not found: %s", path)
        return []

    # Configure Gemini
    model = genai.GenerativeModel("gemini-2.5-flash")

    # Read PDF bytes
    pdf_bytes = path.read_bytes()
    file_size_mb = len(pdf_bytes) / (1024 * 1024)

    # For very large PDFs, limit pages further
    if file_size_mb > 50:
        max_pages = min(max_pages, 5)
    elif file_size_mb > 20:
        max_pages = min(max_pages, 8)

    all_products: list[WeChatProduct] = []

    try:
        # Upload PDF to Gemini
        uploaded = genai.upload_file(path, mime_type="application/pdf")

        # Process pages - Gemini handles multi-page PDFs natively
        prompt = f"""Analyze this product catalog/price list PDF (up to first {max_pages} pages).

{_EXTRACTION_PROMPT}"""

        response = model.generate_content([uploaded, prompt])

        if response.text:
            products = _parse_gemini_response(
                response.text,
                source_file_id=source_file_id,
                source_filename=path.name,
                vendor_id=vendor_id,
                vendor_name=vendor_name,
            )
            all_products.extend(products)

        # Clean up uploaded file
        try:
            genai.delete_file(uploaded.name)
        except Exception:
            pass

    except Exception as e:
        logger.error("Gemini extraction failed for %s: %s", path.name, e)
        return []

    logger.info("Gemini extracted %d products from %s", len(all_products), path.name)
    return all_products


def _parse_gemini_response(
    text: str,
    source_file_id: str,
    source_filename: str,
    vendor_id: str,
    vendor_name: str,
) -> list[WeChatProduct]:
    """Parse Gemini's JSON response into WeChatProduct objects."""
    # Extract JSON array from response (may have markdown fencing)
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                items = json.loads(match.group())
            except json.JSONDecodeError:
                logger.warning("Could not parse Gemini response as JSON")
                return []
        else:
            return []

    if not isinstance(items, list):
        return []

    products: list[WeChatProduct] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        name = item.get("product_name", "") or item.get("name", "")
        sku = item.get("sku", "") or item.get("model", "")
        if not name and not sku:
            continue

        price = 0.0
        try:
            price = float(item.get("unit_price", 0) or 0)
        except (ValueError, TypeError):
            pass

        products.append(WeChatProduct(
            product_name=str(name),
            product_name_zh="" if not re.search(r"[\u4e00-\u9fff]", str(name)) else str(name),
            source_file_id=source_file_id,
            source_filename=source_filename,
            source_page=0,
            sku=str(sku),
            description=str(item.get("description", "")),
            category=str(item.get("category", "")),
            material=str(item.get("material", "")),
            dimensions=str(item.get("dimensions", "")),
            unit_price=price,
            currency=str(item.get("currency", "CNY")),
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            extraction_method="gemini_vision",
            extraction_confidence=0.6,
        ))

    return products
