"""Encoding helpers for migration script files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class MigrationEncodingError(ValueError):
    """Raised when a migration script cannot be decoded safely."""


def _read_charset_header(raw: bytes) -> Optional[str]:
    """Return a BOM-signaled charset, following Flyway's UTF-16 header check."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if len(raw) < 2 or len(raw) % 2 != 0:
        return None
    first, second = raw[0], raw[1]
    if first == 0xFE and second == 0xFF:
        return "utf-16-be"
    if first == 0xFF and second == 0xFE:
        return "utf-16-le"
    return None


def _can_decode(raw: bytes, encoding: str) -> bool:
    try:
        raw.decode(encoding)
    except UnicodeDecodeError:
        return False
    return True


def _is_likely_utf16(raw: bytes) -> bool:
    """Mirror Flyway's heuristic: more NULs than non-NULs at odd byte offsets."""
    if len(raw) % 2 != 0:
        return False
    score = 0
    for offset in range(1, len(raw), 2):
        score += 1 if raw[offset] == 0 else -1
    return score > 0


def detect_file_encoding(path: Path) -> str:
    """Detect a migration script encoding using Flyway-like deterministic rules."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MigrationEncodingError(f"Could not read migration script '{path}': {exc}") from exc

    detected = _detect_bytes_encoding(raw)
    if not detected:
        raise MigrationEncodingError(f"Could not detect encoding for migration script '{path}'")
    return detected


def _detect_bytes_encoding(raw: bytes) -> Optional[str]:
    header_encoding = _read_charset_header(raw)
    if header_encoding:
        return header_encoding

    detected: Optional[str] = None
    for encoding in ("utf-8", "iso-8859-1", "utf-16"):
        if _can_decode(raw, encoding):
            detected = encoding
            break

    if detected not in {"utf-16", "utf-16-be", "utf-16-le"} and _is_likely_utf16(raw):
        return "utf-16-le"
    return detected


def read_migration_text(
    path: Path,
    *,
    configured_encoding: str = "utf-8",
    detect_encoding: bool = False,
) -> str:
    """Read migration text with either the configured or detected encoding."""
    encoding = detect_file_encoding(path) if detect_encoding else configured_encoding
    try:
        return path.read_text(encoding=encoding).lstrip("\ufeff")
    except UnicodeDecodeError as exc:
        mode = "detected" if detect_encoding else "configured"
        raise MigrationEncodingError(
            f"Could not decode migration script '{path}' with {mode} encoding '{encoding}': {exc}"
        ) from exc
    except OSError as exc:
        raise MigrationEncodingError(f"Could not read migration script '{path}': {exc}") from exc
