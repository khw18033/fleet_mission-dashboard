FROM python:3.11-slim

WORKDIR /app

COPY apps/central-hub/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# React SPA 빌드 결과 복사 (빌드 후 존재 시)
COPY ui-spa/dist/ ./ui-spa/dist/

COPY tools/ ./tools/
COPY config.yaml .
COPY apps/central-hub/ ./apps/central-hub/

ENV PYTHONUNBUFFERED=1
ENV K3S_DRY_RUN=0

CMD ["python", "-m", "uvicorn", "apps.central-hub.mission_orchestrator:app", \
     "--host", "0.0.0.0", "--port", "5000", "--log-level", "info"]
