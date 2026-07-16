FROM python:3.11-slim

WORKDIR /app

COPY services/mission-listener/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/mission-listener/listener.py .
COPY tools/ ./tools/

ENV PYTHONUNBUFFERED=1

CMD ["python", "listener.py"]
