# ── Builder ─────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime ─────────────────────────────────────────────────────────────────
FROM python:3.13-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

# Run migrations (with retry) then start the server.
# The retry matters on EasyPanel/Compose: containers start in parallel, so on a
# fresh deploy Postgres may not be DNS-resolvable yet when this one boots —
# without the loop, alembic dies with gaierror and the container flaps until
# the restart policy happens to line up with the DB being ready.
# Use a single worker in production unless you disable the in-process scheduler.
CMD i=0; until alembic upgrade head; do i=$((i+1)); if [ "$i" -ge 12 ]; then echo "migrations failed after 12 attempts, giving up" >&2; exit 1; fi; echo "database not ready (attempt $i/12), retrying in 5s..." >&2; sleep 5; done; exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
