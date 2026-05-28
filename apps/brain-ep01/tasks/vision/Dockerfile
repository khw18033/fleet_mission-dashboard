FROM python:3.9-slim

WORKDIR /app

# 비전 처리를 위해 최소한의 라이브러리만 설치
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir redis opencv-python-headless

COPY . .

# 실행 시 어떤 워커를 돌릴지 환경변수로 제어
CMD ["python", "vision_worker.py"]