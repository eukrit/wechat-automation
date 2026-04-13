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
    if file_size_mb > 700:
        logger.warning("File too large for Gemini (%dMB): %s", int(file_size_mb), path.name)
        return []

    _init_vertex()
    model = GenerativeModel(MODEL_NAME)

    try:
        logger.info("Gemini processing %s (%.0fMB)...", path.name, file_size_mb)

        # Read file as bytes and create Part
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

        logger.info("Gemini extracted %d products from %s", len(products), path.name)
        return products

    except Exception as e:
        logger.error("Gemini extraction failed for %s: %s", path.name, e)
        return []


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
