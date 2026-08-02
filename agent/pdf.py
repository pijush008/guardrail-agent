"""Extract text from uploaded PDFs so they can be treated as evidence docs.

Uploaded documents are untrusted DATA, exactly like tool responses: the
extracted text is fed into the same guardrail path (indirect-injection scan
+ PII redaction) before it can reach synthesis.
"""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

MAX_PDF_BYTES = 10 * 1024 * 1024      # 10 MB upload cap
MAX_PDF_PAGES = 50                    # don't run away on huge docs
MAX_TEXT_CHARS = 60_000               # ~15k tokens of context


class PdfExtractionError(RuntimeError):
    pass


def extract_pdf_text(
    data: bytes,
    max_chars: int = MAX_TEXT_CHARS,
    max_pages: int = MAX_PDF_PAGES,
) -> str:
    """Return plain text from a PDF byte payload.

    Raises PdfExtractionError for empty payloads, password-protected PDFs,
    and files pypdf cannot parse. Output is capped at max_chars to bound
    token usage.
    """
    if not data:
        raise PdfExtractionError("empty file")
    if len(data) > MAX_PDF_BYTES:
        raise PdfExtractionError("file exceeds 10 MB limit")

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise PdfExtractionError(f"could not parse PDF: {exc}") from exc

    if reader.is_encrypted:
        raise PdfExtractionError("password-protected PDFs are not supported")

    chunks: list[str] = []
    total = 0
    for page in reader.pages[:max_pages]:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        text = " ".join(text.split())
        if not text:
            continue
        room = max_chars - total
        if room <= 0:
            break
        chunks.append(text[:room])
        total += len(text[:room])

    out = "\n".join(chunks)
    if not out.strip():
        raise PdfExtractionError(
            "no extractable text (scanned image PDFs are not supported)")
    return out
