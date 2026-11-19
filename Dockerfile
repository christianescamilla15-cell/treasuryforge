# treasuryforge — containerized end-to-end validation.
#   docker build -t treasuryforge:ci .
#   docker run --rm treasuryforge:ci          # runs the full quality gate
FROM python:3.12-slim

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# deps first (layer cache)
COPY requirements-dev.txt requirements-live.txt pyproject.toml README.md ./
RUN pip install --upgrade pip && pip install -r requirements-dev.txt -r requirements-live.txt

# source + editable install
COPY treasuryforge ./treasuryforge
COPY tests ./tests
COPY scripts ./scripts
RUN pip install -e .

# No corre como root (Trivy DS-0002); la compuerta escribe coverage.xml y cachés en /app.
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

# default: run the full gate (lint, types, security, deps, tests+coverage)
CMD ["bash", "scripts/ci.sh"]
