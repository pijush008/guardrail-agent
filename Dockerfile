FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
# Presidio's NER engine pulls en_core_web_lg (~400MB) on first boot; the
# container uses the deterministic PII redactor instead (build_redactor
# falls back automatically). NER redaction remains available in local runs.
RUN sed '/presidio/d' requirements.txt > requirements-runtime.txt \
    && pip install -r requirements-runtime.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
