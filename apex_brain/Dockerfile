# Apex Brain - HA Add-on Dockerfile
# BUILD_FROM is overridden by HA Supervisor using build.json for multi-arch builds.
# For local docker-compose builds, the default below is used.
# NOTE: HA only publishes the latest Python base images. If 3.13 is removed,
#       update the tag here AND in build.json. Check available tags at:
#       https://github.com/home-assistant/docker-base/pkgs/container/amd64-base-python
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.21
FROM ${BUILD_FROM}

# jq is required because init: false disables S6 overlay and bashio.
# We read /data/options.json with jq in run.sh instead.
RUN apk add --no-cache jq

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
