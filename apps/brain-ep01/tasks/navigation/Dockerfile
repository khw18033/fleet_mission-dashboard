FROM python:3.9-slim

WORKDIR /app

# Redis 클라이언트만 설치 (연산 위주)
RUN pip install --no-cache-dir redis

COPY nav_worker.py .

ENV REDIS_HOST=redis-service
ENV ROBOT_SN=ep01
ENV TASK_ID=default_nav

CMD ["python", "nav_worker.py"]