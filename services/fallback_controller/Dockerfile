FROM python:3.11-slim
WORKDIR /app
COPY services/fallback_controller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tools/ ./tools/
COPY config.yaml .
COPY services/fallback_controller/fallback_controller.py .
ENV PYTHONUNBUFFERED=1
ENV MISSION_STORE=/data/missions
CMD ["python", "fallback_controller.py"]
