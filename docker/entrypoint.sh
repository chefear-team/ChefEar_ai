#!/usr/bin/env bash
# RunPod Pod의 컨테이너 시작 시(=Pod Start 버튼) 자동 실행되는 진입점.
# Pod를 Stop하면 이 프로세스와 함께 cloudflared·Streamlit 둘 다 같이 내려간다.
# 즉 로컬에서 run_local.sh 같은 걸 따로 실행할 필요가 없다 - RunPod 콘솔의
# Start/Stop이 전부다 (docs/runpod_deploy.md 참고).
set -euo pipefail

# ---- ctranslate2(faster-whisper)의 libcublas.so.12 워크어라운드 ----
# run_local.sh가 팀 데스크탑에서 쓰던 것과 같은 방식: pip가 설치한 nvidia-*-cu12
# 패키지들의 lib 디렉터리를 LD_LIBRARY_PATH에 얹는다. Dockerfile을 CUDA 12.4
# 베이스로 맞춰서 이 문제가 애초에 안 생길 가능성이 높지만, 혹시 재현되더라도
# 바로 대응 가능하게 방어적으로 남겨둔다.
NVIDIA_LIB_DIR="$(python -c 'import nvidia, os; print(os.path.dirname(nvidia.__file__))' 2>/dev/null || true)"
if [ -n "$NVIDIA_LIB_DIR" ]; then
    EXTRA_LIBS="$(echo "$NVIDIA_LIB_DIR"/*/lib 2>/dev/null | tr ' ' ':')"
    export LD_LIBRARY_PATH="${EXTRA_LIBS}:${LD_LIBRARY_PATH:-}"
fi

# ---- Cloudflare Tunnel ----
# 방식 A(권장) - Cloudflare Zero Trust 대시보드에서 만든 원격관리형 터널의 토큰을
#   CLOUDFLARE_TUNNEL_TOKEN 환경변수로 RunPod Pod 설정에 넣어두면 그걸로 붙는다.
#   Public Hostname(chefear.store -> http://localhost:8501) 라우팅도 같은 대시보드
#   화면에서 설정 - 로컬 파일이 전혀 필요 없다.
# 방식 B - 기존에 CLI(cloudflared tunnel create)로 만든 로컬관리형 터널이면
#   credentials.json + config.yml을 RunPod Network Volume에 올려두고 경로를 알려준다.
if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
    echo "[entrypoint] cloudflared: 토큰 방식으로 터널 실행" >&2
    cloudflared tunnel run --token "${CLOUDFLARE_TUNNEL_TOKEN}" &
elif [ -f "${CLOUDFLARED_CONFIG:-/workspace/cloudflared/config.yml}" ]; then
    echo "[entrypoint] cloudflared: config.yml 방식으로 터널 실행 (${CLOUDFLARED_CONFIG:-/workspace/cloudflared/config.yml})" >&2
    cloudflared tunnel --config "${CLOUDFLARED_CONFIG:-/workspace/cloudflared/config.yml}" run &
else
    echo "[entrypoint] 경고: CLOUDFLARE_TUNNEL_TOKEN도 config.yml도 없음 - cloudflared를 안 띄웁니다." \
        "chefear.store 연결 없이 RunPod 프록시 URL로만 접근 가능합니다." >&2
fi

# cloudflared가 백그라운드에서 죽으면(&) 컨테이너가 조용히 터널 없이 계속 도는 걸
# 막기 위해 짧게 기동을 기다렸다가 살아있는지 한 번 확인한다.
sleep 3
if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}${CLOUDFLARED_CONFIG:-}" ] && ! jobs %% >/dev/null 2>&1; then
    echo "[entrypoint] 경고: cloudflared가 시작 직후 종료된 것으로 보입니다 - 로그를 확인하세요." >&2
fi

# ---- 구글 OAuth 로그인(docs/specs/user_accounts_google_login.md) ----
# st.login()은 환경변수가 아니라 .streamlit/secrets.toml 파일의 [auth] 섹션만 읽는다.
# 그런데 이 파일은 스펙 문서에 "커밋 금지"로 돼 있어서(비밀값이라 .gitignore) Docker
# 이미지에 안 들어있다 - Supabase 키처럼 RunPod 환경변수만 넣어선 절대 안 읽힌다.
# cloudflared 토큰 방식과 같은 패턴: RunPod Pod의 "Environment Variables" 화면에
# 아래 4개 변수만 넣어두면, 컨테이너가 뜰 때마다 이 스크립트가 secrets.toml을 대신
# 생성해준다 - 비밀값 자체는 이 코드 어디에도 안 남고, git에도 안 올라간다.
if [ -n "${GOOGLE_OAUTH_CLIENT_ID:-}" ] && [ -n "${GOOGLE_OAUTH_CLIENT_SECRET:-}" ]; then
    echo "[entrypoint] 구글 OAuth: 환경변수로부터 .streamlit/secrets.toml 생성" >&2
    mkdir -p .streamlit
    cat > .streamlit/secrets.toml <<EOF
[auth]
redirect_uri = "${GOOGLE_OAUTH_REDIRECT_URI:-https://chefear.store/oauth2callback}"
cookie_secret = "${GOOGLE_OAUTH_COOKIE_SECRET:?GOOGLE_OAUTH_COOKIE_SECRET 환경변수가 비어있음 - secrets.token_urlsafe(32)로 생성해서 RunPod Pod 환경변수에 넣을 것}"
client_id = "${GOOGLE_OAUTH_CLIENT_ID}"
client_secret = "${GOOGLE_OAUTH_CLIENT_SECRET}"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
EOF
else
    echo "[entrypoint] 경고: GOOGLE_OAUTH_CLIENT_ID/SECRET 없음 - 구글 로그인 버튼을 누르면" \
        "StreamlitAuthError가 납니다(로컬 아이디/비밀번호 로그인은 정상 동작)." >&2
fi

# ---- 셀프 워밍업 트리거 (2026-09-04) ----
# STT/TTS/LLM 워밍업(src/app.py::_start_model_warmup())은 Streamlit이 세션을
# 시작해야만(=브라우저가 실제로 접속해야만) 도는 코드다 — Pod만 Start하고 아무도
# 접속 안 하면 컨테이너가 아무리 오래 떠있어도 모델을 안 받는다는 걸 실측 확인함
# (부팅 후 20초+ 지나도 [gpu_worker_pool] 로그 0건). "누군가 접속해야 시작"이라는
# 전제 자체는 어쩔 수 없지만(Streamlit 구조), 그 "누군가"를 사람 대신 컨테이너
# 자신으로 만들어본다 — Streamlit 준비되는 대로 접근 게이트 토큰을 붙여 자기
# 자신에게 한 번 접속한다(_access_gate_ok()가 이 토큰을 요구함, app.py 참고).
#
# 미검증 부분(1.5 원칙) — curl은 순수 HTTP GET이고, Streamlit의 실제 스크립트
# 실행은 이후 브라우저 JS가 여는 WebSocket 세션에서 일어나는 것으로 알려져 있어
# (내부 프로토콜, 공식 문서화된 부분 아님), 이 curl 한 번만으로 main()이 실제로
# 끝까지 실행돼 워밍업까지 도달하는지는 배포 후 로그로 확인해야 안다. 안 되면
# (gpu_worker_pool 로그가 여전히 안 뜨면) 이 블록은 효과 없는 것으로 보고 지우거나,
# 진짜 브라우저 세션을 흉내내는 다른 방법으로 바꿀 것.
(
    for _i in $(seq 1 60); do
        if curl -sf "http://localhost:8501/_stcore/health" >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    curl -s "http://localhost:8501/?key=${ACCESS_GATE_TOKEN:-}" -o /dev/null 2>&1 || true
    echo "[entrypoint] 셀프 워밍업 요청 보냄 (실제로 모델 로딩까지 트리거됐는지는 로그로 확인 필요)" >&2
) &

# ---- Streamlit (포그라운드 - 이 프로세스가 컨테이너의 생명주기가 된다) ----
exec python -m streamlit run src/app.py
