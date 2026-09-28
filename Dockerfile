FROM node:22-bookworm-slim AS console-build

WORKDIR /build/results_console
COPY results_console/package.json results_console/package-lock.json ./
RUN npm ci
COPY results_console/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AX_PRODUCT_FROZEN_RESULTS_ROOT=/app/artifacts/phase6_product_demo_v4/runs \
    AX_PRODUCT_LOCAL_DATASETS_ROOT=/data/local-datasets \
    AX_PRODUCT_OCR_MODE=auto \
    AX_PRODUCT_CONSOLE_DIST=/app/results_console/dist

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-kor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY . ./
COPY --from=console-build /build/results_console/dist ./results_console/dist

RUN useradd --create-home --uid 10001 axpreflight \
    && mkdir -p /data/local-datasets \
    && chown -R axpreflight:axpreflight /data

USER axpreflight
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/capabilities', timeout=2)" || exit 1

CMD ["python", "-m", "uvicorn", "ax_product.web:create_local_review_web_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
