# Use official Playwright Python image (includes all browsers & dependencies)
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

# Set working directory
WORKDIR /opt/app

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Expose the port Render will provide
EXPOSE 10000

# Use non-root user (Playwright image already has 'pwuser')
USER pwuser

# Command to run the app with Gunicorn
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --worker-class gthread
