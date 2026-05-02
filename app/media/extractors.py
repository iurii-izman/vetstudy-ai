from __future__ import annotations

from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

from app.media.types import UnsupportedMediaError


def extract_document_text(path: Path, filename: str) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if suffix == ".docx":
        doc = DocxDocument(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    raise UnsupportedMediaError(f"Неподдерживаемый формат: {filename}")


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []
    chunks: list[str] = []
    i = 0
    while i < len(clean):
        chunks.append(clean[i : i + chunk_size])
        i += max(1, chunk_size - overlap)
    return chunks
