# 1. 런타임 환경 설정
FROM python:3.8-slim

# 2. 시스템 의존성 설치 (OpenCV 헤드리스 실행용)
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 3. 작업 공간 생성
WORKDIR /app

# 4. 파이썬 패키지 설치
# opencv-python-headless는 GUI 기능이 빠져서 서버/도커 환경에 최적입니다.
RUN pip install --no-cache-dir \
    robomaster \
    opencv-python-headless \
    numpy

# 5. 소스 코드 복사
COPY vision_streamer.py .

# 6. 실행 설정 (-u 옵션으로 로그 버퍼링 방지)
ENTRYPOINT ["python", "-u", "vision_streamer.py"]