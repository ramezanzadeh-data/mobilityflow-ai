
import io


try:
    import fitz
    _PYMUPDF_AVAILABLE = True
except ImportError:
    _PYMUPDF_AVAILABLE = False


try:
    import pytesseract
    from PIL import Image
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False


MIN_CHARS_FOR_TEXT_PDF = 40


class OCRDependencyError(Exception):
    pass


def extract_text_from_pdf(file_bytes: bytes) -> dict:

    if not _PYMUPDF_AVAILABLE:
        raise OCRDependencyError(
            "PyMuPDF is not installed. Install it with:\n"
            "pip install pymupdf --break-system-packages"
        )


    doc = fitz.open(stream=file_bytes, filetype="pdf")


    native_pages_text = [
        page.get_text()
        for page in doc
    ]

    joined_native = "\n".join(native_pages_text).strip()


    if len(joined_native) >= MIN_CHARS_FOR_TEXT_PDF:

        return {
            "text": joined_native,
            "method": "native_text",
            "pages": doc.page_count,
            "warning": None
        }


    if not _OCR_AVAILABLE:

        return {
            "text": joined_native,
            "method": "empty",
            "pages": doc.page_count,
            "warning": (
                "This PDF appears to be scanned (image-based) and "
                "no readable text could be extracted.\n"
                "To enable OCR install:\n"
                "pip install pytesseract pillow --break-system-packages\n"
                "and install the Tesseract OCR engine on your operating system."
            )
        }


    try:

        ocr_pages_text = []


        for page in doc:

            pix = page.get_pixmap(dpi=200)

            img = Image.open(
                io.BytesIO(
                    pix.tobytes("png")
                )
            )

            ocr_pages_text.append(
                pytesseract.image_to_string(
                    img,
                    lang="eng"
                )
            )


        joined_ocr = "\n".join(ocr_pages_text).strip()


        return {
            "text": joined_ocr,
            "method": "ocr",
            "pages": doc.page_count,
            "warning": None if joined_ocr else "OCR completed but no text was detected."
        }


    except Exception as e:

        return {
            "text": joined_native,
            "method": "empty",
            "pages": doc.page_count,
            "warning": (
                f"OCR failed (Tesseract OCR may not be installed): {e}"
            )
        }