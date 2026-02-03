# Dockerfile for FEC Monitor
# Supports both web server and job modes

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8080

# Default command: run web server with gunicorn
# Override with MODE=job for background jobs
CMD ["sh", "-c", "if [ \"$MODE\" = 'job' ]; then python -m scripts.ingest_job; else gunicorn app.main:app --bind 0.0.0.0:8080 --workers 2 --worker-class uvicorn.workers.UvicornWorker --timeout 120; fi"]
