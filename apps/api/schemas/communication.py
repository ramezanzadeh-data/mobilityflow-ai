from pydantic import BaseModel


class GenerateEmailRequest(BaseModel):
    step: str
    tone: str = "formal"
