"""Extract product data from PDF files.

Two strategies:
1. pdfplumber: for PDFs with extractable text tables (quotations, price lists)
2. Gemini Vision: for image-heavy catalogs where tables are embedded in images

Falls back to Gemini when pdfplumber finds no usable tables.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

from wechat_automation.models import WeChatProduct

logger = logging.getLogger(__name__)

# Reuse column keyword mapping from excel_extractor
_HEADER_KEYWORDS: dict[str, list[str]] = {
    "product_name": ["product", "品名", "名称", "description", "item", "name", "features", "备注"],
    "sku": ["model", "型号", "code", "sku", "no", "编号", "item no", "货号"],
    "dimensions": ["size", "尺寸", "dimension", "规格", "spec"],
    "unit_price": ["unit price", "price", "价格", "单价", "rmb", "usd", "报价", "金额"],
    "material": ["material", "材质", "fabric"],
    "moq": ["moq", "qty", "数量", "quantity"],
    "unit": ["unit", "单位"],
}

_HEADER_INDICATORS = {
    "product", "model", "price", "size", "item", "description",
    "品名", "型号", "价格", "尺寸", "规格", "名称", "单价", "编号",
    "no", "qty", "unit", "单位", "数量", "金额", "备注", "材质",
}


def extract_products_from_pdf(
    filepath: str | Path,
    source_file_id: str = "",
    vendor_id: str = "",
    vendor_name: str = "",
    max_pages: int = 20,
) -> list[WeChatProduct]:
    """Extract products from a PDF file using pdfplumber.

    Args:
        max_pages: Maximum pages to process (large catalogs can be huge).
    """
    path = Path(filepath)
    if not path.exists():
        logger.warning("File not found: %s", path)
        return []

    try:
        with pdfplumber.open(str(path)) as pdf:
            total_pages = len(pdf.pages)
            pages_to_scan = min(total_pages, max_pages)

            all_products: list[WeChatProduct] = []
            tables_found = 0

            for page_num in range(pages_to_scan):
                page = pdf.pages[page_num]
                tables = page.extract_tables()

                if not tables:
                    continue

                for table in tables:
                    if len(table) < 2:
                        continue

                    products = _extract_from_table(
                        table=table,
                        page_num=page_num + 1,
                        source_file_id=source_file_id,
                        source_filename=path.name,
                        vendor_id=vendor_id,
                        vendor_name=vendor_name,
                    )
                    if products:
                        tables_found += 1
                        all_products.extend(products)

            if all_products:
                logger.info(
                    "Extracted %d products from %s (%d tables, %d/%d pages)",
                    len(all_products), path.name, tables_found, pages_to_scan, total_pages,
                )
            return all_products

    except Exception as e:
        logger.error("Failed to process %s: %s", path.name, e)
        return []


def _extract_from_table(
    table: list[list[str | None]],
    page_num: int,
    source_file_id: str,
    source_filename: str,
    vendor_id: str,
    vendor_name: str,
) -> list[WeChatProduct]:
    """Extract products from a single PDF table."""

    # Find header row
    header_idx = _find_header_row(table)
    if header_idx is None:
        return []

    header = table[header_idx]

    # Map columns
    col_map = _map_columns(header)
    if not col_map:
        return []

    # Detect currency from header
    currency = "CNY"
    for cell in header:
        if cell and ("usd" in str(cell).lower() or "$" in str(cell)):
            currency = "USD"
            break

    # Extract data rows
    products: list[WeChatProduct] = []
    for row_idx in range(header_idx + 1, len(table)):
        row = table[row_idx]
        product = _parse_row(
            row=row,
            col_map=col_map,
            page_num=page_num,
            row_num=row_idx + 1,
            currency=currency,
            source_file_id=source_file_id,
            source_filename=source_filename,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
        )
        if product:
            products.append(product)

    return products


def _find_header_row(table: list[list], max_scan: int = 8) -> int | None:
    best_idx = None
    best_score = 0

    for idx, row in enumerate(table[:max_scan]):
        score = 0
        for cell in row:
            if cell is None:
                continue
            cell_lower = str(cell).lower().strip()
            for indicator in _HEADER_INDICATORS:
                if indicator in cell_lower:
                    score += 1
                    break
        if score > best_score and score >= 2:
            best_score = score
            best_idx = idx

    return best_idx


def _map_columns(header: list) -> dict[str, int]:
    col_map: dict[str, int] = {}

    for col_idx, cell in enumerate(header):
        if cell is None:
            continue
        cell_str = str(cell).lower().strip()

        for field, keywords in _HEADER_KEYWORDS.items():
            if field in col_map:
                continue
            for kw in keywords:
                if kw in cell_str:
                    col_map[field] = col_idx
                    break

    return col_map


def _parse_row(
    row: list,
    col_map: dict[str, int],
    page_num: int,
    row_num: int,
    currency: str,
    source_file_id: str,
    source_filename: str,
    vendor_id: str,
    vendor_name: str,
) -> WeChatProduct | None:
    def _get(field: str) -> str:
        idx = col_map.get(field)
        if idx is None or idx >= len(row) or row[idx] is None:
            return ""
        return str(row[idx]).strip()

    name = _get("product_name")
    sku = _get("sku")

    if not name and not sku:
        return None

    combined = (name + sku).lower()
    if any(skip in combined for skip in ["total", "subtotal", "合计", "小计", "合计金额"]):
        return None

    price_str = _get("unit_price")
    unit_price = _parse_number(price_str)

    dimensions = _get("dimensions")
    material = _get("material")
    moq_str = _get("moq")
    moq = int(_parse_number(moq_str)) if moq_str else 0

    product_name = name if name else sku

    return WeChatProduct(
        product_name=product_name,
        product_name_zh="" if not re.search(r"[\u4e00-\u9fff]", product_name) else product_name,
        source_file_id=source_file_id,
        source_filename=source_filename,
        source_page=page_num,
        sku=sku,
        description=name if name != sku else "",
        material=material,
        dimensions=dimensions,
        unit_price=unit_price,
        currency=currency,
        moq=moq,
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        extraction_method="pdf_table",
        extraction_confidence=0.7,
    )


def _parse_number(s: str) -> float:
    if not s:
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    cleaned = re.sub(r"[¥$€฿,\s]", "", str(s))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0
