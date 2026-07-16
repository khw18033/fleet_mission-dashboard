FROM python:3.11-slim
WORKDIR /app
COPY services/handover_controller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tools/ ./tools/
COPY services/handover_controller/handover_controller.py .
ENV PYTHONUNBUFFERED=1
CMD ["python", "handover_controller.py"]
