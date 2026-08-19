# ── Grams Recipe App — Dockerfile ─────────────────────────────
FROM python:3.11-slim

# System deps needed for psycopg2, playwright, yt-dlp
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser (chromium only — needed for TikTok scraping)
RUN playwright install chromium --with-deps

# Copy application source
COPY . .

# Expose Flask port
EXPOSE 5000

# Run with Gunicorn (config from gunicorn.conf.py)
CMD ["gunicorn", "--config", "gunicorn.conf.py", "--bind", "0.0.0.0:5000", "app:app"]
