"""Decode WeChat .dat image files.

WeChat Desktop (Windows) stores images as .dat files with a simple XOR cipher.
Each byte is XOR'd with a single key byte. The key is determined by XOR'ing
the first byte of the .dat file with the expected magic byte of the image format.

Known magic bytes:
- JPEG: 0xFF (first byte of FF D8 FF)
- PNG:  0x89 (first byte of 89 50 4E 47)
- GIF:  0x47 (first byte of 47 49 46 38)
- BMP:  0x42 (first byte of 42 4D)
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Magic bytes for common image formats
_MAGIC_BYTES: list[tuple[int, str, str]] = [
    (0xFF, "jpg", "image/jpeg"),   # JPEG: FF D8 FF
    (0x89, "png", "image/png"),    # PNG: 89 50 4E 47
    (0x47, "gif", "image/gif"),    # GIF: 47 49 46 38
    (0x42, "bmp", "image/bmp"),    # BMP: 42 4D
]

# Verification: second byte after XOR should match these
_VERIFY_SECOND: dict[int, int] = {
    0xFF: 0xD8,  # JPEG second byte
    0x89: 0x50,  # PNG second byte
    0x47: 0x49,  # GIF second byte
    0x42: 0x4D,  # BMP second byte
}


def detect_key_and_format(first_two_bytes: bytes) -> tuple[int, str, str] | None:
    """Detect the XOR key and image format from the first two bytes.

    Returns (key, extension, content_type) or None if unrecognized.
    """
    if len(first_two_bytes) < 2:
        return None

    b0, b1 = first_two_bytes[0], first_two_bytes[1]

    for magic, ext, mime in _MAGIC_BYTES:
        key = b0 ^ magic
        # Verify with second byte
        expected_second = _VERIFY_SECOND.get(magic, 0)
        if (b1 ^ key) == expected_second:
            return key, ext, mime

    return None


def decode_dat(dat_bytes: bytes) -> tuple[bytes, str, str] | None:
    """Decode a WeChat .dat file into an image.

    Returns (image_bytes, extension, content_type) or None if decoding fails.
    """
    if len(dat_bytes) < 2:
        return None

    result = detect_key_and_format(dat_bytes[:2])
    if result is None:
        return None

    key, ext, mime = result
    decoded = bytes(b ^ key for b in dat_bytes)
    return decoded, ext, mime


def decode_dat_file(dat_path: str | Path) -> tuple[bytes, str, str] | None:
    """Read and decode a .dat file from disk.

    Returns (image_bytes, extension, content_type) or None.
    """
    path = Path(dat_path)
    if not path.exists():
        logger.warning("DAT file not found: %s", path)
        return None

    dat_bytes = path.read_bytes()
    result = decode_dat(dat_bytes)
    if result is None:
        logger.warning("Could not decode DAT file: %s", path)
    return result


def save_decoded(dat_path: str | Path, output_dir: str | Path | None = None) -> Path | None:
    """Decode a .dat file and save the image alongside it (or in output_dir).

    Returns the output path or None if decoding failed.
    """
    dat_path = Path(dat_path)
    result = decode_dat_file(dat_path)
    if result is None:
        return None

    image_bytes, ext, _ = result
    if output_dir:
        out_path = Path(output_dir) / f"{dat_path.stem}.{ext}"
    else:
        out_path = dat_path.with_suffix(f".{ext}")

    out_path.write_bytes(image_bytes)
    logger.info("Decoded %s -> %s", dat_path.name, out_path.name)
    return out_path
