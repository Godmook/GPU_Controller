# WDRF Controller Dockerfile
FROM python:3.11-slim

# 메타데이터
LABEL maintainer="AX Technology Group"
LABEL description="WDRF Controller for GPU Scheduling Optimization"
LABEL version="1.0.0"

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 업데이트 및 필요한 패키지 설치
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY controller/ ./controller/
COPY README.md .

# 로그 디렉토리 생성
RUN mkdir -p /var/log

# 비root 사용자 생성
RUN useradd --create-home --shell /bin/bash wdrf && \
    chown -R wdrf:wdrf /app /var/log

# 사용자 전환
USER wdrf

# 헬스 체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -m controller --health-check || exit 1

# 포트 노출 (메트릭스용)
EXPOSE 8080

# 기본 명령어
ENTRYPOINT ["python", "-m", "controller"]

# 기본 인수
CMD ["--log-level", "INFO"]
