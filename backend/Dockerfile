FROM python:3.12-slim

# System libraries: ZBar for pyzbar; glib/gomp/libGL for OpenCV + Paddle.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libzbar0 libglib2.0-0 libgomp1 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# PaddleOCR downloads its weights on first use; persist them with a volume (see docker-compose.yml)
# so a container restart does not re-download ~100 MB.
ENV PADDLE_PDX_CACHE_HOME=/models-cache \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Listen on all interfaces for Render/container networking.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
