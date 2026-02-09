ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.21
FROM ${BUILD_FROM}

# Install build dependencies for sqlite-vec
RUN apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev

# Set working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY brain/ ./brain/
COPY memory/ ./memory/
COPY tools/ ./tools/
COPY ha_addon/run.sh /run.sh

# Make run script executable
RUN chmod a+x /run.sh

# Expose port
EXPOSE 8080

CMD ["/run.sh"]
