from pydantic import BaseModel


class DocumentItem(BaseModel):
    id: int
    case_id: int
    name: str
    status: str
    ocr_method: str | None = None
    ocr_confidence: str | None = None
    uploaded_at: str | None = None


class DocumentCreate(BaseModel):
    case_id: int
    name: str


class DocumentStatusUpdate(BaseModel):
    status: str


class DocumentExtractedText(BaseModel):
    id: int
    extracted_text: str | None = None
