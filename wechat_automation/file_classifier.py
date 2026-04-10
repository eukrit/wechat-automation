"""Classify files by type based on extension and filename keywords."""

from __future__ import annotations

from wechat_automation.filename_parser import ParsedFilename

# Extension -> default file_type mapping
_EXT_MAP: dict[str, str] = {
    # Documents
    "pdf": "document",  # further classified by keywords
    "doc": "document",
    "docx": "document",
    "pptx": "presentation",
    # Spreadsheets
    "xlsx": "spreadsheet",
    "xls": "spreadsheet",
    "csv": "spreadsheet",
    # Drawings / 3D
    "dwg": "drawing",
    "dxf": "drawing",
    "skp": "drawing",
    "3dm": "drawing",
    # Images
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
    "webp": "image",
    "bmp": "image",
    "gif": "image",
    # Video
    "mp4": "video",
    "m4v": "video",
    "mov": "video",
    "avi": "video",
    # Archives
    "rar": "archive",
    "zip": "archive",
    "tgz": "archive",
    "7z": "archive",
}

# doc_type_hint from filename_parser -> final file_type
_HINT_TO_TYPE: dict[str, str] = {
    "invoice": "invoice",
    "quotation": "quotation",
    "po": "po",
    "catalog": "catalog",
    "price_list": "price_list",
    "pi": "invoice",
    "packing_list": "packing_list",
    "drawing": "drawing",
    "certificate": "certificate",
    "form_e": "certificate",
}

# MIME type mapping
_MIME_MAP: dict[str, str] = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "skp": "application/octet-stream",
    "dwg": "application/acad",
    "dxf": "application/dxf",
    "3dm": "application/octet-stream",
    "rar": "application/x-rar-compressed",
    "zip": "application/zip",
    "tgz": "application/gzip",
    "csv": "text/csv",
}


def classify_file(extension: str, parsed: ParsedFilename) -> tuple[str, str]:
    """Classify a file and return (file_type, content_type).

    Uses filename keyword hints first, falls back to extension mapping.
    """
    ext = extension.lower().lstrip(".")

    # Keyword-based classification takes priority for documents/spreadsheets
    if parsed.doc_type_hint and parsed.doc_type_hint in _HINT_TO_TYPE:
        file_type = _HINT_TO_TYPE[parsed.doc_type_hint]
    else:
        file_type = _EXT_MAP.get(ext, "other")

    content_type = _MIME_MAP.get(ext, "application/octet-stream")

    return file_type, content_type
