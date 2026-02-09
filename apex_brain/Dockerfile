ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.21
FROM ${BUILD_FROM}

# Set working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (all in add-on folder for Supervisor build context)
COPY brain/ ./brain/
COPY memory/ ./memory/
COPY tools/ ./tools/
COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8080
CMD ["/run.sh"]
