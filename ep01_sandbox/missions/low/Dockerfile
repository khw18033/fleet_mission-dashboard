# 1. 가벼운 Python 3.8 베이스 이미지 사용
FROM python:3.8-slim

# 2. 시스템 필수 라이브러리 설치
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리 설정
WORKDIR /app

# 4. RoboMaster SDK 설치
RUN pip install --no-cache-dir robomaster

# 5. 실행 코드 복사
COPY low_executor.py .

# 6. 실행 명령 
ENTRYPOINT ["python", "-u", "low_executor.py"]