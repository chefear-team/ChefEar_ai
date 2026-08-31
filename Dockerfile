# ChefEar RunPod GPU Pod 배포용 이미지.
#
# 팀 GPU 데스크탑(run_local.sh)과 동일한 조건을 맞추려고 한다:
#   - CUDA 12.4 베이스 (faster-whisper/ctranslate2가 libcublas.so.12를 요구하는데,
#     nvidia-cu13 pip 패키지만 있으면 못 찾아서 죽었던 문제 - run_local.sh 주석 참고.
#     torch를 cu124 인덱스로 설치하면 nvidia-*-cu12 계열이 같이 깔려서 이 문제를
#     원천적으로 피해간다는 게 이 선택의 근거다 - 다만 실제 빌드/실행으로 검증된 적은
#     아직 없으니 첫 배포 때 STT 로딩 로그를 반드시 확인할 것)
#   - Python 3.13 고정 (streamlit-webrtc가 의존하는 aioice가 3.14 미지원 - 팀이 실측
#     확인한 이슈, run_local.sh 주석 참고). 베이스 이미지에 3.13이 없어서 소스 빌드한다.
#
# 빌드는 RunPod의 "Deploy from GitHub repo" 기능으로 이 Dockerfile을 자동 빌드시키는
# 걸 권장 - 로컬에 Docker 설치/빌드/푸시 없이 RunPod 콘솔에서 전부 처리된다.
# (docs/runpod_deploy.md 참고)

FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ---- 시스템 패키지 ----
# ffmpeg/libsndfile1: librosa·soundfile·av(aiortc 의존) 오디오 처리에 필요.
# 나머지는 Python 3.13을 소스에서 빌드하기 위한 표준 build deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential wget curl git ca-certificates pkg-config \
    zlib1g-dev libssl-dev libffi-dev libbz2-dev libreadline-dev \
    libsqlite3-dev libncurses5-dev libgdbm-dev liblzma-dev tk-dev uuid-dev \
    ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# ---- Python 3.13 소스 빌드 (--enable-shared: 팀 데스크탑과 동일 방식) ----
# --enable-optimizations(PGO/LTO)는 뺐다 - 빌드 시간이 수십 분 늘어나는데, 이 앱은
# GPU-bound 추론이 대부분이라 인터프리터 자체 속도 이득이 체감상 크지 않다고 판단.
ARG PYTHON_VERSION=3.13.9
RUN wget -q https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz \
    && tar xzf Python-${PYTHON_VERSION}.tgz \
    && cd Python-${PYTHON_VERSION} \
    && ./configure --enable-shared --with-ensurepip=install \
    && make -j"$(nproc)" \
    && make altinstall \
    && cd .. && rm -rf Python-${PYTHON_VERSION} Python-${PYTHON_VERSION}.tgz \
    && ldconfig

RUN ln -sf /usr/local/bin/python3.13 /usr/local/bin/python \
    && ln -sf /usr/local/bin/pip3.13 /usr/local/bin/pip

# ---- cloudflared ----
RUN curl -fsSL -o /usr/local/bin/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    && chmod +x /usr/local/bin/cloudflared

WORKDIR /app

# ---- Python 의존성 ----
# README 실행 방법 그대로: requirements.txt(HF Spaces용 최소, streamlit·supabase·
# faster-whisper 등)와 requirements-main.txt(transformers·peft·bitsandbytes·qwen-tts
# 등 모델 로딩 스택)를 둘 다 깔아야 앱이 뜬다. torch는 cu124 인덱스로 별도 설치.
COPY requirements.txt requirements-main.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install \
        torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 \
        --index-url https://download.pytorch.org/whl/cu124 \
    && python -m pip install -r requirements.txt -r requirements-main.txt

# ---- 앱 코드 ----
COPY . .

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Cloudflare Tunnel이 아웃바운드로만 연결하므로 인바운드 포트를 공개할 필요는 없지만,
# RunPod 콘솔에서 직접 HTTP 프록시로 디버깅하고 싶을 때를 위해 남겨둔다.
EXPOSE 8501

ENTRYPOINT ["/entrypoint.sh"]
