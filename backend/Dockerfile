FROM python:3.12-slim

# System libraries: ZBar for pyzbar; glib/gomp/libGL for OpenCV + Paddle.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libzbar0 libglib2.0-0 libgomp1 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# PaddleOCR cache + unbuffered Python output
ENV PADDLE_PDX_CACHE_HOME=/models-cache \
    PYTHONUNBUFFERED=1

# Render uses the PORT environment variable for web services.
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD python -c "import os, urllib.request; port=os.getenv('PORT', '10000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health')" || exit 1

# Bind to Render's PORT.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
