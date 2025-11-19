# Dockerfile (suitable for Render and Railway Docker deployments)
FROM python:3.11-slim

# Install system deps required by Playwright browsers
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libasound2 \
    libgbm1 \
    libpangocairo-1.0-0 \
    libx11-xcb1 \
    fonts-liberation \
    wget \
    curl \
    unzip \
    gnupg \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /opt/app

# Copy requirements (make sure playwright is in requirements)
COPY requirements.txt /opt/app/requirements.txt

RUN pip install --no-cache-dir -r /opt/app/requirements.txt

# Install Playwright browsers (with dependencies)
RUN python -m playwright install --with-deps

# Copy app code
COPY . /opt/app

# Expose port (Render uses PORT env)
ENV PORT 5000
EXPOSE 5000

# Use a non-root user for safety (optional)
RUN groupadd -r app && useradd -r -g app app
RUN chown -R app:app /opt/app
USER app

# Start command: adjust if you use gunicorn in production
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "2", "--worker-class", "gthread"]
