from pathlib import Path

from pypdf import PdfWriter

from app.media.extractors import chunk_text, extract_document_text


def test_extract_txt_fixture():
    text = extract_document_text(Path("app/tests/fixtures/sample.txt"), "sample.txt")
    assert "plain text fixture" in text


def test_extract_md_fixture():
    text = extract_document_text(Path("app/tests/fixtures/sample.md"), "sample.md")
    assert "Sample Markdown" in text


def test_extract_pdf_and_chunk(tmp_path: Path):
    pdf_path = tmp_path / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf_path.open("wb") as f:
        writer.write(f)
    text = extract_document_text(pdf_path, "sample.pdf")
    chunks = chunk_text("a " * 1200)
    assert isinstance(text, str)
    assert len(chunks) > 1
