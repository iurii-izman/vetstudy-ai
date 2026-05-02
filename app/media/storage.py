from __future__ import annotations

import os
from pathlib import Path

from app.config import get_settings
from app.media.types import FileTooLargeError, StoredFile


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


async def download_telegram_file(*, bot, telegram_file_id: str, file_name: str, size_bytes: int, max_size_bytes: int, content_type: str) -> StoredFile:
    if size_bytes > max_size_bytes:
        raise FileTooLargeError(f"Файл слишком большой: {size_bytes} bytes > {max_size_bytes} bytes")
    settings = get_settings()
    base = Path(settings.media_storage_path).resolve()
    _ensure_dir(base)
    safe_name = "".join(ch for ch in file_name if ch.isalnum() or ch in {'.', '_', '-'}) or "upload.bin"
    target = base / f"{telegram_file_id}_{safe_name}"
    telegram_file = await bot.get_file(telegram_file_id)
    await bot.download_file(telegram_file.file_path, destination=target)
    if not target.exists():
        raise RuntimeError("Не удалось сохранить файл")
    real_size = os.path.getsize(target)
    return StoredFile(
        telegram_file_id=telegram_file_id,
        original_name=file_name,
        content_type=content_type,
        size_bytes=real_size,
        path=target,
    )
