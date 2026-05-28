# 가벼운 Python 3.8 베이스 이미지 사용
FROM python:3.8-slim

# 시스템 필수 라이브러리 설치 (네트워크 및 기본 도구)
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리 설정
WORKDIR /app

# 필요 패키지 설치
# Core에서는 OpenCV가 필요 없으므로 리소스 절약을 위해 robomaster만 설치 권장
# 하지만 호환성을 위해 기본적인 robomaster 의존성만 유지
RUN pip install --no-cache-dir robomaster

# 코드 복사
COPY core_streamer.py .

# 실행 (unbuffered 모드로 로그가 실시간으로 보이게 설정)
CMD ["python", "-u", "core_streamer.py"]