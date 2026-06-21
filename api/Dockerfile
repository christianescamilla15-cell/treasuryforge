# TreasuryForge API — Render deploy
# Builds the FastAPI wrapper over the real treasuryforge package.

FROM python:3.11-slim

WORKDIR /app

# Install API dependencies (the core package is stdlib-only, no runtime deps)
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Copy the production package + the API wrapper + tests (for /api/stats to count them)
COPY treasuryforge /app/treasuryforge
COPY tests /app/tests
COPY api /app/api

EXPOSE 8000

# Honor Render's $PORT
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
