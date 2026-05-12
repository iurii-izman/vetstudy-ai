import os
from pathlib import Path

from app.config import get_settings
from app.db.models import Document


def document_storage_paths(documents: list[Document]) -> list[str]:
    candidate_keys = ("path", "stored_path", "file_path", "upload_path")
    out: list[str] = []
    for doc in documents:
        metadata = dict(doc.metadata_ or {})
        for key in candidate_keys:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
                break
    return out


def cleanup_document_files(paths: list[str]) -> None:
    settings = get_settings()
    base = Path(settings.media_storage_path).resolve()
    seen: set[Path] = set()
    for raw_path in paths:
        file_path = Path(raw_path)
        resolved = file_path.resolve() if file_path.is_absolute() else (base / file_path).resolve()
        if base not in resolved.parents:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            os.remove(resolved)
        except FileNotFoundError:
            continue
