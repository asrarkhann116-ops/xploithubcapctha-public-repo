FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install base dependencies and Xvfb for headless browser execution
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    unzip \
    ca-certificates \
    xvfb \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome via official deb package (auto-resolves all modern Debian dependencies)
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN seleniumbase install chromedriver || true

COPY . .

# Expose default port (Railway overrides via $PORT env var)
EXPOSE 8000

CMD ["python", "run_all.py"]
