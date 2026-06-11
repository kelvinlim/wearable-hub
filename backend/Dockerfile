FROM python:3.13-slim

WORKDIR /app

# Install deps first for layer caching.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

COPY . .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

# Wait for the DB, run migrations, then serve. podman-compose 1.0.6 doesn't honor
# `depends_on: service_healthy`, so the wait must live here.
CMD ["/entrypoint.sh"]
