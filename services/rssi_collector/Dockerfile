FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends iw wireless-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/rssi_collector/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/ ./tools/
COPY services/rssi_collector/rssi_collector.py .

ENV PYTHONUNBUFFERED=1
CMD ["python", "rssi_collector.py"]
