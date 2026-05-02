from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class StoredFile:
    telegram_file_id: str
    original_name: str
    content_type: str
    size_bytes: int
    path: Path


class MediaError(RuntimeError):
    pass


class FileTooLargeError(MediaError):
    pass


class UnsupportedMediaError(MediaError):
    pass
