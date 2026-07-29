FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app
# ---------------- SYSTEM DEPENDENCIES ----------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    curl \
    && rm -rf /var/lib/apt/lists/*


# ---------------- PYTHON DEPENDENCIES ----------------
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt


# ---------------- APP CODE ----------------
COPY . .

EXPOSE 8000 8501


