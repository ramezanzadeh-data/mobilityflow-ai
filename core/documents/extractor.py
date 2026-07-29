
from core.documents.ocr import extract_text_from_pdf, OCRDependencyError


class UnsupportedFormatError(Exception):
    pass


def extract_text(filename: str, file_bytes: bytes) -> dict:

    lower_name = (filename or "").lower()

    if lower_name.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)

    raise UnsupportedFormatError(
        f"No extractor implemented yet for '{filename}'. "
        f"Currently supported formats: .pdf"
    )
