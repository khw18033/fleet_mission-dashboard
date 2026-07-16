FROM python:3.8-slim

# 인터랙티브 모드 방지
ENV DEBIAN_FRONTEND=noninteractive

# 필수 시스템 라이브러리 및 빌드 도구 설치
# redis-tools: 네트워크 진단용 (선택사항)
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    gcc \
    python3-dev \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. 의존성 파일 복사
COPY apps/brain-ep01/link/requirements.txt .

# 2. pip 업그레이드 및 setuptools 강제 설정 (SDK 설치 오류 방지)
# 3. requirements 설치
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir setuptools==58.2.0 && \
    pip install --no-cache-dir -r requirements.txt

# 런타임 설정/유틸 + 소스 코드 복사
COPY tools/ ./tools/
COPY apps/brain-ep01/link/link_proxy.py .

# Flask API를 제거하고 Redis를 사용하므로 5000번 포트 개방은 더 이상 필요 없습니다.
# 하지만 디버깅이나 타 용도로 유지하려면 남겨둬도 무방합니다.
# EXPOSE 5000

# -u 옵션은 로그 출력을 버퍼링 없이 즉시 stdout으로 보내어 K3s 로그 수집을 돕습니다.
CMD ["python", "-u", "link_proxy.py"]
