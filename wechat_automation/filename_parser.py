"""Extract structured metadata from WeChat download filenames.

Handles patterns like:
- "Moonhill PI2026.04.02.xlsx" -> vendor=Moonhill, date=2026-04-02, type=invoice
- "2026-03-05 Wisdom Quotation 20260305 Dulwich.pdf" -> date, vendor, project
- "GO Corporation Co., Ltd  20260313.xls" -> date, known entity
- Chinese filenames like "庭院故事产品图册.pdf" -> type=catalog
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath


@dataclass
class ParsedFilename:
    date: str = ""  # YYYY-MM-DD
    vendor_hint: str = ""  # Best-guess vendor name from filename
    project_hint: str = ""  # Project name if detected
    doc_type_hint: str = ""  # Detected document type keyword
    language: str = ""  # en | zh | mixed
    raw: str = ""


# Date patterns sorted by specificity
_DATE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 2026-04-02, 2026-03-05
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "{0}-{1}-{2}"),
    # 2026.04.02, 2026.2.4
    (re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})"), "{0}-{1:0>2}-{2:0>2}"),
    # 20260402
    (re.compile(r"(?<!\d)(\d{4})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"), "{0}-{1}-{2}"),
]

# Document type keywords (case-insensitive)
_DOC_TYPE_KEYWORDS: dict[str, list[str]] = {
    "invoice": ["invoice", "ci", "commercial invoice"],
    "quotation": ["quotation", "quote", "rfq"],
    "po": ["po", "purchase order", "po#"],
    "catalog": ["catalog", "catalogue", "图册", "画册", "目录"],
    "price_list": ["price list", "pricelist", "报价", "报价单"],
    "pi": ["pi", "proforma invoice", "pi-"],
    "packing_list": ["packing list", "loading list"],
    "drawing": ["2d", "3d", "cad", "layout"],
    "certificate": ["certificate", "cert", "msds", "tds", "sgs"],
    "form_e": ["form e", "form-e"],
}

# Known project names (from actual file data)
_KNOWN_PROJECTS = [
    "Dulwich", "Anantara Siam", "Eton House", "Rawai Phuket",
    "Middleton", "Ibis Tower", "Dusit", "Avani", "PRASARN MANSION",
    "Rayong Star", "Koh Pha Ngan", "ZIVA", "HZA", "Punit",
    "Niwat", "Connoiseur", "RIVE GAUCHE",
]

_PROJECT_PATTERN = re.compile(
    "|".join(re.escape(p) for p in _KNOWN_PROJECTS),
    re.IGNORECASE,
)

# Chinese character detection
_HAS_CJK = re.compile(r"[\u4e00-\u9fff]")
_HAS_LATIN = re.compile(r"[a-zA-Z]")


def parse_filename(filepath: str) -> ParsedFilename:
    """Parse a filename (or full path) and extract structured metadata."""
    # Get just the filename stem
    try:
        name = PureWindowsPath(filepath).stem
    except Exception:
        name = PurePosixPath(filepath).stem

    result = ParsedFilename(raw=name)

    # Detect language
    has_cjk = bool(_HAS_CJK.search(name))
    has_latin = bool(_HAS_LATIN.search(name))
    if has_cjk and has_latin:
        result.language = "mixed"
    elif has_cjk:
        result.language = "zh"
    elif has_latin:
        result.language = "en"

    # Extract date
    for pattern, fmt in _DATE_PATTERNS:
        m = pattern.search(name)
        if m:
            try:
                result.date = fmt.format(*m.groups())
                break
            except (ValueError, IndexError):
                continue

    # Detect document type
    name_lower = name.lower()
    for doc_type, keywords in _DOC_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                result.doc_type_hint = doc_type
                break
        if result.doc_type_hint:
            break

    # Detect project
    pm = _PROJECT_PATTERN.search(name)
    if pm:
        result.project_hint = pm.group(0)

    # Extract vendor hint: take the leading text before date/type keywords
    result.vendor_hint = _extract_vendor_hint(name, result.date)

    return result


def _extract_vendor_hint(name: str, date_str: str) -> str:
    """Try to extract a vendor name from the filename.

    Strategy: take text before the first date, number sequence, or doc-type keyword.
    Clean up common prefixes/suffixes.
    """
    # Remove date-like patterns
    cleaned = name
    for pattern, _ in _DATE_PATTERNS:
        cleaned = pattern.sub("", cleaned)

    # Remove known doc-type keywords
    cleaned_lower = cleaned.lower()
    for keywords in _DOC_TYPE_KEYWORDS.values():
        for kw in keywords:
            idx = cleaned_lower.find(kw)
            if idx != -1:
                cleaned = cleaned[:idx] + cleaned[idx + len(kw):]
                cleaned_lower = cleaned.lower()

    # Remove project names
    cleaned = _PROJECT_PATTERN.sub("", cleaned)

    # Clean up separators and whitespace
    cleaned = re.sub(r"[_\-\.\(\)\[\]#]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Remove pure numeric tokens and very short tokens
    tokens = [t for t in cleaned.split() if not t.isdigit() and len(t) > 1]

    if not tokens:
        return ""

    # Take the first meaningful segment (up to 4 tokens) as vendor hint
    vendor = " ".join(tokens[:4]).strip(" -_.,")

    # Skip if it's a generic term
    generic = {"co", "ltd", "corp", "corporation", "new", "update", "draft", "signed", "low"}
    vendor_words = [w for w in vendor.lower().split() if w not in generic]
    if not vendor_words:
        return ""

    return vendor
