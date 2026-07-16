FROM python:3.11-slim

WORKDIR /app

COPY services/edge-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/ ./tools/
COPY services/edge-gateway/broadcaster.py .

ENV PYTHONUNBUFFERED=1

CMD ["python", "broadcaster.py"]
