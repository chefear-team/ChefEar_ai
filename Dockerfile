# ChefEar RunPod GPU Pod 배포용 이미지.
#
# 팀 GPU 데스크탑(run_local.sh)과 동일한 조건을 맞추려고 한다:
#   - CUDA 12.4 (faster-whisper/ctranslate2가 libcublas.so.12를 요구하는데,
#     nvidia-cu13 pip 패키지만 있으면 못 찾아서 죽었던 문제 - run_local.sh 주석 참고.
#     torch를 cu124 인덱스로 설치하면 nvidia-*-cu12 계열이 같이 깔려서 이 문제를
#     원천적으로 피해간다는 게 이 선택의 근거다 - 2026-08-31 실제 빌드/GHCR push까지
#     검증 완료, run 성공: github.com/minhahamin/cookEar_ai/actions/runs/33386662996)
#   - Python 3.13 고정 (streamlit-webrtc가 의존하는 aioice가 3.14 미지원 - 팀이 실측
#     확인한 이슈, run_local.sh 주석 참고). 베이스 이미지에 3.13이 없어서 소스 빌드한다.
#   - torch/torchvision/torchaudio == 2.6.0/0.21.0/2.6.0 (cu124). 처음엔 팀이 검증한
#     2.5.1/0.20.1/2.5.1로 시도했으나 cu124+Python 3.13(cp313) 휠이 torchvision
#     0.20.1엔 없어서 빌드 실패(Actions run #1) - download.pytorch.org 인덱스 확인해
#     cp313 휠이 있는 조합(2.6.0 매트릭스)으로 정정.
#
# ---- 이미지 용량 최적화 (2026-08-31) ----
# Python 3.13을 소스에서 빌드하려면 build-essential(gcc 등) + CUDA devel 베이스가
# 필요한데, 정작 컨테이너를 "실행"할 땐 둘 다 필요 없다(torch는 이미 컴파일된 wheel,
# nvcc로 뭘 컴파일하지도 않음) - 그래서 멀티스테이지로 분리한다:
#   1) python-builder 스테이지: devel 베이스 + 컴파일러로 Python 3.13만 빌드
#   2) 최종 스테이지: runtime 베이스(devel 대비 CUDA 툴킷/헤더가 빠져 수 GB 가벼움)에
#      빌드된 Python(/usr/local)만 COPY - gcc/make/binutils 같은 빌드 툴체인 자체가
#      최종 이미지 레이어에 아예 안 들어간다(레이어 뒤에서 apt remove 하는 것과 달리
#      실제로 용량이 빠진다 - Docker 레이어는 누적이라 나중에 지워도 이전 레이어 용량은
#      그대로 남기 때문).
# av(aiortc 의존) 같은 패키지가 혹시 소스 빌드될 경우를 대비해 최종 스테이지에도 동일한
# -dev 패키지 목록을 유지한다(2026-08-31 빌드 로그 기준 av==17.1.0은 prebuilt wheel로
# 설치돼 실제로는 필요 없었지만, 다음 Python 패치버전 등에서 wheel이 없어질 가능성에
# 대비해 안전하게 유지 - 헤더 용량 자체는 작아서 이걸 남기는 비용은 미미함).

# ---- Stage 1: Python 3.13 소스 빌드 전용(최종 이미지에 안 남음) ----
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04 AS python-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential wget pkg-config \
    zlib1g-dev libssl-dev libffi-dev libbz2-dev libreadline-dev \
    libsqlite3-dev libncurses5-dev libgdbm-dev liblzma-dev tk-dev uuid-dev \
    && rm -rf /var/lib/apt/lists/*

# --enable-optimizations(PGO/LTO)는 뺐다 - 빌드 시간이 수십 분 늘어나는데, 이 앱은
# GPU-bound 추론이 대부분이라 인터프리터 자체 속도 이득이 체감상 크지 않다고 판단.
ARG PYTHON_VERSION=3.13.9
RUN wget -q https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz \
    && tar xzf Python-${PYTHON_VERSION}.tgz \
    && cd Python-${PYTHON_VERSION} \
    && ./configure --enable-shared --with-ensurepip=install \
    && make -j"$(nproc)" \
    && make altinstall \
    && cd .. && rm -rf Python-${PYTHON_VERSION} Python-${PYTHON_VERSION}.tgz

# ---- Stage 2: 실제 서비스 이미지 ----
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg/libsndfile1: librosa·soundfile·av(aiortc 의존) 오디오 처리에 필요.
# -dev 계열: python-builder가 --enable-shared로 빌드한 Python이 런타임에 동적링크하는
# libssl/libsqlite3/libncurses 등을 위해 필요(주석 상단 참고 - 소스 빌드 대비용).
# build-essential(gcc 등)은 2026-08-31엔 "실행 땐 필요 없다"고 판단해서 뺐었는데,
# 2026-09-07 flash-attn 설치 이후 실측으로 틀렸다는 게 확인됨 — flash-attn이 물고
# 들어온 triton이 CudaUtils() 초기화 시 driver.c를 **런타임에 직접 컴파일**한다
# (triton/backends/nvidia/driver.py -> compile_module_from_src). 이 컴파일이
# LLM(EXAONE) 워커 초기화 안에서 일어나는데 gcc가 없어서 매번
# "RuntimeError: Failed to find C compiler"로 실패 -> 그 워커가 죽어서 GPU 풀
# 전체가 broken 상태가 되고, 이후 모든 STT/TTS/LLM 요청이 BrokenProcessPool로
# 실패하는 것까지 실사용 중 재현됨(자동복구가 재시도해도 매번 같은 이유로 또
# 실패). 그래서 gcc를 다시 넣는다 — 용량은 늘지만(수십MB) "빌드 툴체인은
# 런타임에 필요 없다"는 전제 자체가 flash-attn 도입으로 깨졌으니 정확성이
# 우선이다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git pkg-config gcc \
    zlib1g-dev libssl-dev libffi-dev libbz2-dev libreadline-dev \
    libsqlite3-dev libncurses5-dev libgdbm-dev liblzma-dev tk-dev uuid-dev \
    ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-builder /usr/local /usr/local
RUN ldconfig \
    && ln -sf /usr/local/bin/python3.13 /usr/local/bin/python \
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
        torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
        --index-url https://download.pytorch.org/whl/cu124 \
    && python -m pip install -r requirements.txt -r requirements-main.txt

# ---- flash-attn (2026-09-07, TTS 추론 속도 개선 시도) ----
# 공식(Dao-AILab) 배포엔 Python 3.13(cp313) + torch2.6 + cu124 조합 wheel이 없다
# (소스 빌드만 가능한데 컴파일이 무거워서 빌드 시간이 크게 늘고 실패 위험도 있음).
# 대신 커뮤니티 프로젝트 mjun0812/flash-attention-prebuild-wheels가 정확히 이
# 조합을 미리 빌드해서 배포하고 있어 그걸 그대로 설치한다(소스 빌드 없음, 빌드
# 시간 영향 거의 없음 — 다운로드만). tts/infer.py의 load_tts_model()이 이미
# `import flash_attn` try/except로 있으면 자동으로 attn_implementation=
# "flash_attention_2"를, 없으면 "sdpa"로 폴백하게 짜여 있어서 이 설치 외에 코드
# 변경은 필요 없다. 공식 배포가 아닌 개인 빌드 wheel이라는 점은 감안할 것 — 문제
# 생기면 이 줄만 지우면 기존 sdpa 경로로 그대로 돌아간다.
RUN python -m pip install \
    https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.7.16/flash_attn-2.6.3%2Bcu124torch2.6-cp313-cp313-linux_x86_64.whl

# ---- 앱 코드 ----
COPY . .

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Cloudflare Tunnel이 아웃바운드로만 연결하므로 인바운드 포트를 공개할 필요는 없지만,
# RunPod 콘솔에서 직접 HTTP 프록시로 디버깅하고 싶을 때를 위해 남겨둔다.
EXPOSE 8501

ENTRYPOINT ["/entrypoint.sh"]
