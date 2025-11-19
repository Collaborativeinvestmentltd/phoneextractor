FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libnss3 libatk-bridge2.0-0 libgtk-3-0 libxcomposite1 \
    libxdamage1 libxrandr2 libasound2 libgbm1 libpangocairo-1.0-0 \
    libx11-xcb1 fonts-liberation wget curl unzip gnupg ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/app

COPY requirements.txt /opt/app/requirements.txt
RUN pip install --no-cache-dir -r /opt/app/requirements.txt
RUN python -m playwright install --with-deps

COPY . /opt/app

ENV PORT 5000
EXPOSE 5000

RUN groupadd -r app && useradd -r -g app app
RUN chown -R app:app /opt/app
USER app

# Shell form to expand $PORT
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --worker-class gthread
