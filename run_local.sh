#!/usr/bin/env bash
# 로컬 GPU 데스크탑에서 Streamlit 앱을 실행하는 스크립트.
#
# 이 저장소 폴더(프로젝트 루트)는 네트워크 공유 드라이브라 wook/kswook30 두 계정(데스크탑/
# 노트북)이 같이 쓴다. venv는 각 계정의 $HOME 밑에 로컬로 따로 설치돼 있어서 공유되지
# 않는다 — 한쪽 계정 이름으로 하드코딩하면(예: ~/tf-env-312) 다른 계정에선 그 venv가 없어서
# 깨진다(2026-08-21 실제로 겪음). 그래서 후보 경로를 순서대로 찾아 존재하는 첫 번째 걸 쓴다.
#
# faster-whisper(ctranslate2)가 device="cuda"일 때 libcublas.so.12/libcudnn을
# 찾는데 CUDA 13만 깔려있으면 못 찾아서 죽는 문제가 있었음(2026-08-20 실측,
# "Library libcublas.so.12 is not found"). 아래 후보 venv들엔 nvidia-cu13
# 계열(libcublas.so.13)과 cudnn 9(libcudnn.so.9)만 있고 .so.12는 없어서,
# 아래 LD_LIBRARY_PATH를 잡아줘도 ctranslate2가 여전히 libcublas.so.12를
# 요구한다면 이 문제가 재현될 수 있다 — 실행해서 직접 확인 필요.
#
# 사용법:
#   ./run_local.sh                     # 기본값: src/app.py(실제 서비스 앱) 실행
#   ./run_local.sh tests/test_ui.py    # STT->LLM->DB->TTS 수동 확인용 테스트 화면
#
# 새 계정에서 처음 돌리는데 아래 후보 중 아무것도 없다고 나오면, streamlit/faster-whisper/
# torch가 깔린 venv를 하나 만들고 이 배열에 경로를 추가할 것.
#
# 2026-08-23 — chefear-py313을 최우선으로 둔다. 상시 마이크(streamlit-webrtc) 기능이
# Python 3.14(예: recipe-stt venv)에서는 안 붙는다 — 원인은 이 프로젝트 코드가 아니라
# aioice(streamlit-webrtc의 ICE 구현 의존성)가 아직 Python 3.14를 공식 지원 안 해서다
# (PyPI 기준 최신 aioice==0.10.2조차 classifier가 3.13까지만 명시, 2025-11-28 릴리스로
# 3.14가 이미 나온 뒤인데도 그럼 — 업스트림 미해결). 헤드리스 브라우저(playwright,
# --use-fake-device-for-media-stream)로 실측 확인: 3.14에서는 iceConnectionState가
# checking에서 곧장 closed로 끊기고, 소스에서 빌드한 Python 3.13.9(--enable-shared,
# ~/python3.13)로 만든 이 venv에서는 completed까지 정상 도달. Python 3.13이 aioice가
# 공식 지원하는 마지막 버전이라 이걸 새 기본값으로 삼는다 — aioice가 3.14를 지원하게
# 되면(업스트림 릴리스 확인 후) 이 우선순위를 다시 정리할 것.
set -euo pipefail

CANDIDATES=(
    "$HOME/.venvs/chefear-py313"
    "$HOME/.venvs/chefear"
    "$HOME/.venvs/recipe-stt"
    "$HOME/tf-env-312"
)

VENV=""
for candidate in "${CANDIDATES[@]}"; do
    if [ -x "$candidate/bin/streamlit" ]; then
        VENV="$candidate"
        break
    fi
done

if [ -z "$VENV" ]; then
    echo "streamlit이 깔린 venv를 못 찾음 — 다음 경로들을 확인했음:" >&2
    printf '  %s\n' "${CANDIDATES[@]}" >&2
    echo "새 계정이면 venv를 만들고 run_local.sh의 CANDIDATES에 경로를 추가할 것." >&2
    exit 1
fi

# nvidia 라이브러리 경로는 파이썬 버전에 따라 site-packages 밑 경로가 달라져서(예:
# python3.12 vs python3.14) glob으로 찾는다.
NVIDIA_LIB="$(echo "$VENV"/lib/python3.*/site-packages/nvidia)"

export LD_LIBRARY_PATH="$NVIDIA_LIB/cu13/lib:$NVIDIA_LIB/cudnn/lib:${LD_LIBRARY_PATH:-}"

TARGET="${1:-src/app.py}"

echo "venv: $VENV" >&2

exec "$VENV/bin/streamlit" run "$TARGET"
