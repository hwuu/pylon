# Multi-stage build for Pylon
# Stage 1: Build frontend
# Stage 2: Final image with Python + Nginx

# =============================================================================
# Stage 1: Build frontend
# =============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Install dependencies
COPY frontend/package*.json ./
RUN npm ci

# Build
COPY frontend/ ./
RUN npm run build

# =============================================================================
# Stage 2: Final image
# =============================================================================
FROM python:3.12-slim

# Install nginx and utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    gettext-base \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY pylon/ ./pylon/
COPY tests/mock_server/ ./tests/mock_server/

# Copy frontend build
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Copy docker files
COPY docker/docker-entrypoint.sh /docker-entrypoint.sh
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/config.template.js /app/frontend/dist/config.template.js

RUN chmod +x /docker-entrypoint.sh

# Create data directory
RUN mkdir -p /data

# Expose ports
# 8000: Proxy
# 8001: Admin
# 5173: Frontend
# 9999: Mock server
EXPOSE 8000 8001 5173 9999

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["serve", "-c", "/config/config.yaml"]
