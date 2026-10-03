FROM python:3.12-slim

# System libraries:
# - ZBar for pyzbar
# - glib/gomp/libGL for OpenCV
# - Tesseract OCR engine
# - English Tesseract language data
RUN apt-get update && apt-get install -y --no-install-recommends \
        libzbar0 \
        libglib2.0-0 \
        libgomp1 \
        libgl1 \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD python -c "import os, urllib.request; port=os.getenv('PORT', '10000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health')" 

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
