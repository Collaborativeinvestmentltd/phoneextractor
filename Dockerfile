# Use a slim Python base
FROM python:3.11-slim

# Prevent interactive prompts during package install
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
# Provide a default in case Render doesn't supply one (Render overrides PORT)
ENV PORT=10000

# Install system deps required by Playwright + typical media libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gnupg \
    wget \
    curl \
    unzip \
    fonts-liberation \
    libnss3 \
    libxss1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm1 \
    libpangocairo-1.0-0 \
    libx11-xcb1 \
    ffmpeg \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create app user & dir
RUN groupadd -r app && useradd -r -g app app
WORKDIR /opt/app

# Copy requirements first for Docker layer caching
COPY requirements.txt /opt/app/requirements.txt

# Install Python deps (including playwright in requirements.txt)
RUN pip install --no-cache-dir -r /opt/app/requirements.txt

# Install Playwright browsers and required deps (run as root)
# --with-deps will also install runtime deps for browsers
RUN python -m playwright install --with-deps

# Copy the rest of the app
COPY . /opt/app

# Set ownership to non-root user
RUN chown -R app:app /opt/app

# Switch to non-root user for runtime
USER app

# Expose a port (informational only - Render uses $PORT)
EXPOSE 10000

# Healthcheck (use shell form so $PORT expands)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl --fail http://127.0.0.1:$PORT/health || exit 1

# Use shell-form CMD so $PORT expands at runtime on Render
# Gunicorn will listen on the port Render provides in $PORT
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --worker-class gthread
