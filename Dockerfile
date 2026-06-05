FROM python:3.10-slim AS builder

WORKDIR /build
COPY pyproject.toml /build/
COPY paper_radar/ /build/paper_radar/
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.10-slim

WORKDIR /app

# Keep this dependency layer in sync with pyproject.toml runtime dependencies.
# Installing deps separately lets source-only changes reuse the expensive layer.
RUN pip install --no-cache-dir \
    "requests>=2.31" \
    "paperscraper>=0.2" \
    "pymupdf4llm>=0.0.17" \
    "pdfplumber>=0.11" \
    "fastapi>=0.110" \
    "jinja2>=3.1" \
    "uvicorn>=0.27"

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir --no-deps /tmp/*.whl && rm /tmp/*.whl

COPY .env.example /app/.env.example
COPY config.yaml /app/config.yaml

ENTRYPOINT ["paper-radar"]
CMD ["--help"]
