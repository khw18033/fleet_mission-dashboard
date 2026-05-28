FROM python:3.11-slim

WORKDIR /app

COPY services/edge-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/ ./tools/
COPY config.yaml .
COPY services/edge-gateway/broadcaster.py .

ENV PYTHONUNBUFFERED=1
ENV CONFIG_PATH=/app/config.yaml

CMD ["python", "broadcaster.py"]
