import io
import re
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def parse_file(file_bytes: bytes, filename: str) -> str:
    """Parse text from PDF, DOCX, or TXT files."""
    ext = Path(filename).suffix.lower()

    try:
        if ext == ".pdf":
            return _parse_pdf(file_bytes)
        elif ext == ".docx":
            return _parse_docx(file_bytes)
        elif ext == ".txt":
            return file_bytes.decode("utf-8", errors="replace")
        else:
            raise ValueError(f"Unsupported file type: {ext}")
    except Exception as e:
        logger.error(f"Failed to parse {filename}: {e}")
        raise


def _parse_pdf(data: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
            return "\n".join(pages).strip()
    except ImportError:
        # Fallback: pypdf
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(data))
        texts = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(texts).strip()


def _parse_docx(data: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def clean_resume_text(text: str) -> str:
    """Normalize whitespace and remove noise from resume text."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'[^\x20-\x7E\n]', ' ', text)
    return text.strip()


def extract_email(text: str) -> Optional[str]:
    match = re.search(r'[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}', text)
    return match.group(0) if match else None


def extract_phone(text: str) -> Optional[str]:
    match = re.search(r'(\+?\d[\d\s\-().]{7,}\d)', text)
    return match.group(0).strip() if match else None