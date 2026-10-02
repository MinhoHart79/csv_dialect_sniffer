"""Public API for the csv_dialect_sniffer package."""

from .core import Dialect, detect_dialect, detect_dialects

__all__ = ["Dialect", "detect_dialect", "detect_dialects"]
