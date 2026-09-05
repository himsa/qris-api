"""qris — QRIS static->dynamic converter. Stdlib only, tanpa dependency."""
from .core import convert, crc16, generate_api_key, parse, selftest

__version__ = "0.2.0"
__all__ = ["convert", "parse", "crc16", "generate_api_key", "selftest"]
