"""ChefEar STT/TTS 연결(speak/listen) — src/app.py에서 분리(2026-08-22, 화면 컴포넌트화).

세션 상태는 ui/session.py, 발화 디스패처는 ui/dispatch.py, 화면별 함수는 ui/screens/ 참고.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import soundfile as sf
import streamlit as st

from orchestration import gpu_worker_pool
from orchestration.db import load_env
from orchestration.term_dict import resolve_for_tts
from theme import render_audio_autoplay, render_audio_player, render_loading_overlay, render_processing_chime

# stt/infer.py·tts/infer.py·llm/infer.py와 같은 이유(각 모듈이 독립적으로 .env를 읽어야
# app.py 없이도, 또는 import 순서와 무관하게 TURN_HOST 등 환경변수를 쓸 수 있음) —
# 2026-08-23, _ice_servers()의 TURN_* 조회를 위해 추가.
load_env()

# 2026-08-23 임시 진단 로그 — "Connection is taking longer than expected"(WebRTC 연결
# 실패) 원인 파악용. aioice가 실제로 어떤 ICE 후보를 모으고 연결성 검사(connectivity
# check)가 왜 실패하는지 콘솔에 찍는다. 원인 확인되면 지울 것(상시로 켜두면 로그가
# 너무 많아짐).
if os.environ.get("WEBRTC_DEBUG"):
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("aioice").setLevel(logging.DEBUG)
    logging.getLogger("aiortc").setLevel(logging.DEBUG)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# 2026-08-26 요청 — 서버 콘솔에 "Task was destroyed but it is pending!"이 마이크가
# 재연결될 때마다 반복 실측 확인. 원인: aioice(site-packages/aioice/turn.py의
# TurnTransport.sendto())가 매 전송마다 asyncio.create_task()로 send_data()를 던져놓고
# 아무도 참조를 안 든다 — 그 코루틴이 channel_bind()를 기다리는 도중(아래
# _cloudflare_turn_ice_servers() 문서의 "CHANNEL_BIND 400 Bad Request" 실측과 같은
# 원인으로 추정, 아직 미확정) RTCPeerConnection이 닫히면 참조를 잃은 채로 GC돼서
# asyncio가 이 경고를 찍는다. 실제 오디오는 이 TURN 채널을 안 타고 STUN/host 후보로
# 흐르고 있어서(_ice_transport_policy()가 항상 None을 돌려줘 relay를 강제 안 함)
# 기능상 영향이 없다고 이미 확인된 상태다 — asyncio 표준 로거("asyncio", asyncio 내부가
# 이 경고를 찍을 때 쓰는 로거 이름)에 이 문구 하나만 걸러내는 필터를 달아 콘솔 스팸만
# 없앤다. 근본 원인(aioice ↔ Cloudflare TURN 서버 사이의 channel_bind 호환성 문제로
# 추정)은 그대로 열려 있고 고친 게 아니다 — 무해하다고 확인된 경고를 안 보이게 할 뿐,
# 다른 asyncio 에러/경고는 그대로 다 찍힌다.
class _SuppressBenignTurnTaskDestroyedWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Task was destroyed but it is pending" not in record.getMessage()


logging.getLogger("asyncio").addFilter(_SuppressBenignTurnTaskDestroyedWarning())


# 2026-08-26 — Cloudflare Realtime TURN 자격증명 캐시. generate-ice-servers 호출마다
# 새 자격증명이 발급되는데(TTL 있음), _ice_servers()가 webrtc_streamer()를 부르는
# 거의 매 rerun마다 불려서 그때마다 새로 발급받으면 API 호출이 낭비되고, rtc_configuration
# 값이 rerun마다 바뀌면 이미 연결된 컴포넌트가 불필요하게 재협상할 위험도 있다(1번 섹션
# "checking 중 rerun이 끼면 연결이 죽는다" 문제와 같은 종류). TTL 안에서는 같은 값을
# 계속 재사용한다.
_CF_TURN_CACHE: dict = {}


def _cloudflare_turn_ice_servers() -> list[dict] | None:
    """Cloudflare Realtime TURN에서 짧게 유효한 iceServers를 발급받는다(2026-08-26 추가).

    배경 — 기존 TURN_HOST(아래 _ice_servers() 참고)는 이 데스크탑에 직접 띄운 coturn을
    Tailscale 전용 IP(100.108.102.44)로만 리슨하게 한 것이라, chefear.store(Cloudflare
    Tunnel)로 공개 인터넷에서 들어오는 방문자는 애초에 그 IP에 닿을 수가 없다(Tailscale
    tailnet 멤버만 라우팅됨). 집 라우터에 포트포워딩을 여는 대신, 공인 IP를 이미 갖고
    있는 Cloudflare 쪽 TURN 서비스를 쓴다 — 집 네트워크는 전혀 안 건드린다.

    .env의 CF_TURN_KEY_ID/CF_TURN_KEY_API_TOKEN이 둘 다 있을 때만 시도한다(없으면
    조용히 None — 호출부가 기존 TURN_HOST 경로로 폴백). 발급 실패(네트워크 문제, 키
    만료 등)도 예외를 삼키고 None만 돌려준다(EC-05와 같은 정신 — 마이크 연결 자체가
    STUN만으로도 되는 경우가 많아서, TURN 발급 실패로 마이크 기능 전체가 죽으면 안 됨).
    """
    key_id = os.environ.get("CF_TURN_KEY_ID")
    api_token = os.environ.get("CF_TURN_KEY_API_TOKEN")
    if not key_id or not api_token:
        return None

    import time

    now = time.monotonic()
    if _CF_TURN_CACHE.get("servers") and now < _CF_TURN_CACHE.get("expires_at", 0.0):
        return _CF_TURN_CACHE["servers"]

    import json
    import urllib.error
    import urllib.request

    ttl_seconds = 24 * 3600  # 넉넉히 하루 — 발급 API 호출 자체를 자주 안 하려는 목적
    url = f"https://rtc.live.cloudflare.com/v1/turn/keys/{key_id}/credentials/generate-ice-servers"
    request = urllib.request.Request(
        url,
        data=json.dumps({"ttl": ttl_seconds}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # 2026-08-26 실측 확인 — urllib 기본 User-Agent("Python-urllib/3.x")로 호출하면
            # Cloudflare 엣지 WAF가 "error code: 1010"(브라우저 시그니처 기반 차단)으로
            # 요청 자체를 거부한다(자격증명 문제가 아니었음 — 같은 키로 브라우저 UA를
            # 달아 보내니 201로 정상 발급됨). 일반 브라우저처럼 보이는 UA를 명시해서 우회.
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — EC-05, 실패해도 기존 STUN/TURN_HOST로 폴백
        print(f"[voice_io] Cloudflare TURN 자격증명 발급 실패(폴백): {exc!r}", flush=True)
        return None

    ice_servers = payload.get("iceServers")
    if not ice_servers:
        print(f"[voice_io] Cloudflare TURN 응답에 iceServers 없음(폴백): {payload!r}", flush=True)
        return None

    # 실제 만료 시점보다 60초 일찍 캐시를 비운다 — 자격증명이 딱 만료되는 순간에 걸쳐
    # 새 연결 협상이 시작되는 레이스를 피하기 위한 여유.
    _CF_TURN_CACHE["servers"] = ice_servers
    _CF_TURN_CACHE["expires_at"] = now + ttl_seconds - 60
    return ice_servers


def _ice_servers() -> list[dict]:
    """WebRTC(상시 마이크)의 ICE 서버 목록.

    2026-08-26 — Cloudflare Realtime TURN이 설정돼 있으면(.env의 CF_TURN_KEY_ID/
    CF_TURN_KEY_API_TOKEN, _cloudflare_turn_ice_servers() 참고) 그걸 우선 쓴다 — 공인
    인터넷 어디서든 닿는 TURN이라 Cloudflare Tunnel로 들어오는 방문자도 문제없다.
    구글 공개 STUN도 항상 같이 넣어둔다(무료라 손해볼 게 없고, STUN만으로 뚫리는
    네트워크는 TURN 릴레이 비용 자체가 안 든다).

    Cloudflare 쪽이 설정 안 됐거나 발급 실패면, 기존 방식(2026-08-23 추가)으로
    폴백한다 — .env에 TURN_HOST/TURN_USERNAME/TURN_PASSWORD가 있으면 그 TURN(이
    데스크탑에 직접 띄운 coturn, 기본은 Tailscale 전용 IP)을 추가로 넣는다. STUN만으로는
    이 데스크탑처럼 WSL2가 Windows 뒤에 NAT로 숨어있는 환경에서, 이중 NAT를 못 뚫는
    방문자의 WebRTC(UDP) 연결이 실측으로 확인된 적 있다("Connection is taking longer
    than expected" 에러) — 아무 TURN도 안 잡히면 조용히 STUN만 쓰는 것으로 폴백한다
    (같은 기기 브라우저에서 테스트할 땐 STUN만으로도 충분함).
    """
    cf_servers = _cloudflare_turn_ice_servers()
    if cf_servers:
        return cf_servers + [{"urls": ["stun:stun.l.google.com:19302"]}]

    servers: list[dict] = [{"urls": ["stun:stun.l.google.com:19302"]}]

    if _turn_configured():
        turn_host = os.environ.get("TURN_HOST")
        turn_port = os.environ.get("TURN_PORT") or "3478"
        servers.append(
            {
                "urls": [f"turn:{turn_host}:{turn_port}"],
                "username": os.environ.get("TURN_USERNAME"),
                "credential": os.environ.get("TURN_PASSWORD"),
            }
        )
    return servers


def _turn_configured() -> bool:
    """.env에 TURN_HOST/TURN_USERNAME/TURN_PASSWORD가 다 채워져 있는지."""
    return bool(
        os.environ.get("TURN_HOST") and os.environ.get("TURN_USERNAME") and os.environ.get("TURN_PASSWORD")
    )


def _ice_transport_policy() -> str | None:
    """2026-08-25 추가, 2026-08-26 두 번 되돌림 — 이 데스크탑의 여러 가상 네트워크
    인터페이스(WSL 브릿지, Docker, link-local 등)가 전부 ICE host candidate로 잡혀서
    STUN 연결성 검사가 수천 건까지 폭증하는 게 실측 확인됐다(WEBRTC_DEBUG 로그로 확인 —
    발화 하나 없이 순수 협상만으로 3500개 넘는 STUN BINDING REQUEST). 이 정도 동시
    요청량에서 aioice/aiortc의 알려진(2022년부터 미해결, streamlit-webrtc#845/aiortc#85)
    asyncio 이벤트루프 정리 버그가 거의 매번 재현돼서 연결이 느려지거나 최악엔 영영
    안 붙는다 — `iceTransportPolicy: "relay"`로 STUN/host candidate 탐색 자체를 건너뛰고
    TURN 릴레이만 쓰게 강제하면 후보 개수가 줄어서 이 버그를 피할 수 있을 것으로
    기대했었다.

    **두 번 시도했고 두 번 다 되돌렸다** — 이 정책은 지금까지 실전에서 안전했던 적이
    없다:
    1. 2026-08-25 — TURN_HOST(이 데스크탑 coturn, Tailscale 전용 IP)를 조건으로 걸었다가
       되돌림. Tailscale 밖 방문자에겐 그 TURN 자체가 안 닿아서, relay 전용 강제 시
       후보가 하나도 안 남아 연결이 완전히 막혔다.
    2. 2026-08-26 — Cloudflare Realtime TURN(_cloudflare_turn_ice_servers())으로 바꾸면
       1번 문제는 해소된다고 판단해 다시 켰다가, **곧바로 실사용 재현으로 되돌림**:
       TURN 자격증명 발급 자체는 성공했지만(API 실측 확인), 실제 릴레이 채널을 여는
       단계(`CHANNEL_BIND`)가 Cloudflare TURN 서버에서 `400 Bad Request`로 거부되는
       게 재현됐다(`aioice.stun.TransactionFailed: STUN transaction failed (400 - )`,
       `aioice/turn.py::channel_bind()`). 자격증명 발급과 실제 릴레이 채널 개통은
       완전히 다른 단계라, API 테스트 성공이 이 단계까지 보장하지 못했다 — aioice의
       TURN 클라이언트 구현과 Cloudflare TURN 서버 사이의 구체적인 호환성 문제로
       추정(원인 미확정). relay 전용 강제는 TURN이 유일한 경로가 되므로, 이 버그가
       있는 한 강제할수록 오히려 연결이 더 잘 막힌다.

    결론 — **이 함수는 당분간 항상 None을 반환한다.** STUN/host candidate까지 다 열어둬서
    (기존 동작) TURN 채널 문제를 웬만하면 안 거치고 넘어가게 한다. Cloudflare TURN
    자체(비강제, iceServers 목록에 넣어두는 것)는 계속 쓴다 — 자격증명 발급은 정상이라
    STUN이 막힌 네트워크에서 폴백으로 시도라도 해볼 여지는 남겨둔다. CHANNEL_BIND
    400 원인을 밝히기 전까지는 relay 강제를 다시 켜지 말 것.
    """
    return None


def _rtc_configuration() -> dict:
    """webrtc_streamer()에 넘길 RTCConfiguration을 조립한다(2026-08-26 추가) — _ice_servers()
    와 _ice_transport_policy() 둘을 한 곳에서 합쳐서, 정책이 None일 때 그 키 자체를 아예
    안 넣게 한다(WebRTC 표준상 iceTransportPolicy의 기본값이 "all"이라, 명시적으로 None을
    넣는 것보다 키 자체를 생략하는 쪽이 더 안전 — 브라우저/streamlit-webrtc가 None을
    "all"로 정확히 해석해준다는 보장이 없어서다)."""
    config: dict = {"iceServers": _ice_servers()}
    policy = _ice_transport_policy()
    if policy:
        config["iceTransportPolicy"] = policy
    return config

# 2026-08-21: st.audio()는 Streamlit이 rerun마다 <audio> 태그를 새로 만드는 방식이라
# 자동재생은 물론 수동 재생 버튼도 안 먹히는 문제가 실측으로 확인됐다(브라우저에서 재생
# 버튼을 눌러도 반응 없음). 대신 ui/streamlit_screens/cooking_step.py에서 이미 실제로
# 잘 작동하는 render_audio_player()(진짜 <audio autoplay> + JS 우회)를 그대로 쓴다 —
# 그 화면이 쓰는 것과 같은 ui/assets/audio/ 경로를 그대로 재사용해서, 같은 레시피의
# 조리 단계 음성 캐시를 두 앱이 같이 쓸 수 있게 한다(2026-08-20 실측: 문장당 최대
# 4분 걸리는 로컬 CPU 합성을 두 번 반복하지 않아도 됨).
_AUDIO_DIR = PROJECT_ROOT / "ui" / "assets" / "audio"

# 2026-08-22: TTS 합성 자체는 GPU에서도 문장 길이에 따라 3~9초 걸리는 게 실측으로 확인됐고
# (docs/decisions.md #2), torch.compile 등으로 더 줄이려는 시도는 재컴파일 스톨 위험이 더
# 커서 보류했다(합성 속도 자체는 그대로 두기로 함) — 대신 남은 조리 단계 음성을 사용자가
# 지금 단계를 듣고 있는 동안 백그라운드에서 순서대로 계속 미리 합성해둬서, 실제 "다음"
# 발화 시점엔 이미 캐싱돼 있게 만든다(prefetch_remaining_steps_audio() 참고). 이 락은 백그라운드 프리페치와
# speak()의 실시간 합성이 동시에 같은 GPU 모델 인스턴스를 호출하는 걸 막는다 — qwen_tts
# 모델이 동시 호출에 안전한지 보장이 없어서, 항상 한 번에 하나씩만 GPU에 올리게 직렬화한다.
#
# 2026-08-24 — 원래 이름은 _TTS_LOCK(TTS 호출끼리만 직렬화)이었는데, 실사용 중 "STT는
# 됐는데 그 다음부터 터미널 로그(WRTCDBG 등 평소 계속 찍히는 것들)까지 전부 멈춘다"는
# 리포트를 재현/분석한 결과 원인이 이 락의 범위 밖에 있었다 — STT(faster-whisper)·
# 임베딩(sentence-transformers, classify_intent())·로컬 LLM(EXAONE, extract_intent_llm())
# 이 셋 다 같은 GPU를 쓰는데 서로 간엔 아무 직렬화가 없었다. TTS 전용이던 이 락을 GPU를
# 쓰는 모든 추론 호출(STT/임베딩/LLM/TTS)로 넓혀서 _GPU_LOCK(threading.Lock) 단일 락으로
# 항상 한 번에 하나씩만 GPU에 올라가게 했었다(2026-08-24~2026-08-26).
#
# 2026-08-26 실험적 완화 — 모델 종류별로 락을 4개로 쪼개 동시 사용자를 처리해보려
# 했다가 "Queue overflow" 경고가 재현돼 다음날 되돌렸다: 파이썬 스레드는 전부 같은
# GIL을 공유해서, GPU 호출 여러 개가 겹치면 그 GIL 경합 때문에 상시 마이크 오디오
# 드레인 루프가 제때 못 돌았다.
#
# 2026-09-01 — 그래서 "스레드 락을 어떻게 쪼개느냐" 자체를 그만두고, 별도 프로세스
# 여러 개(각자 자기 GIL)로 바꿨다. 이 파일의 GPU 호출 지점들은 이제 _GPU_LOCK 대신
# orchestration.gpu_worker_pool의 submit_*()가 돌려주는 Future를 기다린다 — 자세한
# 설계 배경은 그 모듈의 docstring 참고.

def _common_audio_path(message: str) -> Path:
    """조리 단계처럼 recipe_id/step_number가 없는 1회성 문구(확인 질문·안내 등)의
    캐시 경로 — 문구 자체의 해시를 키로 쓴다. speak()와 _render_cached_speech()가
    같은 문구에 대해 항상 같은 경로를 계산해야 캐시가 서로 맞물린다."""
    import hashlib

    digest = hashlib.sha1(message.encode("utf-8")).hexdigest()[:16]
    return _AUDIO_DIR / "_common" / f"{digest}.wav"


# 2026-09-02 실측 리포트 — "끝음절이 자꾸 잘린다"의 진짜 원인 확정. 같은 세션 안에서
# prefetch_remaining_steps_audio()의 백그라운드 스레드와 speak()의 실시간 합성이
# 같은 audio_path(예: <recipe_id>/02.wav)를 동시에 노릴 수 있다 — 사용자가 프리페치가
# 그 단계까지 끝나기 전에 "다음"이라고 말하면, 둘 다 "파일 있어?"(audio_path.exists())를
# 각자 확인해서 둘 다 False를 보고, 둘 다 GPU로 합성해서 둘 다 sf.write(audio_path, ...)를
# 부른다 — 실측 로그로 확인(같은 문장의 [TTS_DEBUG]가 13초 간격으로 두 번, 뒤이어
# "[PERF] TTS 18.09s"). sf.write()는 원자적이지 않아서(먼저 열어 자르고 데이터를 쓰는
# 방식), 한쪽이 쓰는 도중 다른 쪽이 같은 파일을 다시 열어 써버리면 그 사이 재생을 시작한
# 브라우저가 아직 다 안 쓰인/잘린 파일을 읽을 수 있다 — 매번 재현되지 않고("가끔"만
# 잘림) 재현될 때마다 정확히 끝부분만 없는 것과 정확히 들어맞는다.
#
# audio_path별로 락을 하나씩 둬서 직렬화한다 — 먼저 온 쪽이 실제로 합성/저장하고, 나중에
# 온 쪽은 락을 기다렸다가(먼저 온 쪽이 끝난 뒤) 다시 exists()를 확인해서 "이미 만들어져
# 있네"로 조용히 넘어간다(중복 GPU 합성도 같이 없어짐 — 덤). 이 프로젝트는 세션 여럿이
# 같은 Streamlit 서버 프로세스 안에서 스레드로 도므로(각 세션의 백그라운드 합성 스레드
# 포함), 이 프로세스 전역 딕셔너리 하나로 세션 내부(프리페치 vs 실시간)뿐 아니라 여러
# 사용자가 같은 표준 레시피의 같은 단계를 비슷한 시점에 처음 여는 경우까지 같이 막아준다.
# audio_path마다 Lock 객체가 하나씩 쌓여 프로세스 수명 내내 안 지워지지만(정리 로직
# 없음), Lock 객체 자체가 아주 가벼워서 실제 배포 규모(레시피 수 x 단계 수 + 1회성
# 문구 수)에서는 무시할 만한 메모리다.
_synthesis_locks: dict[Path, threading.Lock] = {}
_synthesis_locks_guard = threading.Lock()


def _get_synthesis_lock(audio_path: Path) -> threading.Lock:
    with _synthesis_locks_guard:
        lock = _synthesis_locks.get(audio_path)
        if lock is None:
            lock = threading.Lock()
            _synthesis_locks[audio_path] = lock
        return lock


def _write_wav_atomic(audio_path: Path, waveform, sample_rate: int) -> None:
    """sf.write(audio_path, ...)를 직접 부르는 대신 이 함수를 쓴다.

    2026-09-02 — 위 _get_synthesis_lock() 락은 "쓰기 vs 쓰기"(prefetch와 실시간 합성이
    같은 파일에 동시에 써서 서로 덮어쓰는 것)만 막는다 — "읽기 vs 쓰기"는 안 막는다.
    render_audio_player()/_wav_bytes_with_lead_silence()(재생용 바이트를 만들려고
    sf.read()로 이 파일을 읽음)나 _arm_tts_mute()(sf.info()로 길이만 읽음), 심지어
    _compute_wave_bars()까지 — 이 파일을 읽는 모든 경로가 락 없이 그냥 읽는다.
    sf.write()는 파일을 열어서 자르고 그 자리에 데이터를 순서대로 쓰는 방식이라
    (원자적이지 않음), 쓰는 도중에(특히 아직 GPU 워커 프로세스 결과를 디스크에
    옮겨적는 몇백 ms~1초 사이) 다른 스레드가 같은 파일을 읽으면 헤더의 선언된
    길이보다 실제로는 덜 쓰인, 잘린 데이터를 읽을 수 있다 — 매번 재현 안 되고
    ("가끔"만) 재현될 때마다 정확히 끝부분만 없는 리포트와 정확히 들어맞는다.
    실측으로 최종 디스크 파일 자체는 무음으로 깨끗하게 끝나있는 걸 확인했다(레이스가
    지나가면 마지막에 쓴 쪽이 온전한 파일을 남김) — 그러니 문제는 "언젠가 잘린 파일이
    영구히 남는다"가 아니라 "쓰는 그 순간에 누군가 읽으면 그 찰나엔 잘린 걸 본다"는
    쪽이다.

    고전적인 "임시 파일에 다 쓴 뒤 최종 경로로 원자적 교체"로 고친다 — 같은
    파일시스템 안에서 os.replace()(POSIX rename, 커널이 보장하는 원자적 교체)는
    "전혀 다른 파일이 없던 상태"에서 "완전히 새 파일이 생긴 상태"로 순간적으로
    바뀌는 것처럼 보인다 — 그 사이의 "쓰다 만" 중간 상태 자체가 그 최종 경로에서는
    아예 관측될 수 없다. 그래서 읽는 쪽(render_audio_player() 등) 전부를 락으로
    감쌀 필요 없이, 쓰는 쪽만 이렇게 고치면 모든 읽기 경로가 자동으로 안전해진다.
    임시 파일명에 pid+스레드id를 섞어서 동시에 여러 쓰기가 진행 중이어도(위 락으로
    보통은 직렬화되지만 최후의 안전장치로) 서로 다른 임시 파일을 쓴다.
    """
    tmp_path = audio_path.with_name(f".{audio_path.name}.tmp{os.getpid()}-{threading.get_ident()}")
    try:
        # 2026-09-04 — 실사용 리포트: "No format specified and unable to get format
        # from file extension: '.../<해시>.wav.tmp<pid>-<쓰레드id>'". sf.write()는
        # format=을 안 넘기면 경로의 "확장자"로 포맷을 추측하는데, 이 tmp_path는
        # 끝이 ".wav"가 아니라 ".tmp<pid>-<쓰레드id>"라 확장자 추측이 실패한다 —
        # 최종 경로(audio_path)는 항상 .wav로 끝나서 이 문제가 없었는데, 임시
        # 파일명에 접미사를 붙이면서 새로 생긴 회귀. format="WAV"를 명시해서
        # 파일명이 뭐든(확장자와 무관하게) 항상 WAV로 쓰게 고정한다.
        sf.write(tmp_path, waveform, sample_rate, format="WAV")
        os.replace(tmp_path, audio_path)  # 같은 디렉터리 안이므로 원자적 교체
    except BaseException:
        tmp_path.unlink(missing_ok=True)  # 실패 시 임시 파일 흔적을 안 남긴다
        raise


def _arm_tts_mute(audio_path: Path) -> None:
    """이 오디오가 재생되는 동안 상시 마이크가 자기 목소리를 다시 주워듣지 않게,
    "지금부터 대략 이 길이만큼은 마이크 입력을 무시하라"는 시각을 세션에 남긴다
    (2026-08-23, 상시 마이크 도입과 함께 추가).

    TTS 재생은 실제로는 브라우저에서 <audio autoplay>가 재생하는 동안 일어나는데,
    파이썬 쪽은 그 재생이 끝나는 시점을 알 방법이 없다(자바스크립트 콜백을 다시
    서버로 보내는 별도 컴포넌트 없이는). 대신 이미 손에 쥐고 있는 정보로 근사한다 —
    합성된 wav 파일 자체의 길이(`soundfile.info().duration`)는 정확히 알 수 있으므로,
    "지금(재생 시작 시점 근사) + 오디오 길이 + 약간의 여유"까지를 무시 구간으로 잡는다.
    `_run_mic_loop()`가 프레임을 받을 때마다 이 시각과 비교해서, 아직 안 지났으면 프레임을
    받아도 VAD/STT에 넘기지 않고 버린다.
    """
    import time

    try:
        duration = sf.info(audio_path).duration
    except Exception:
        duration = 3.0  # 길이를 못 읽으면 최소한의 안전 여유만 둔다
    # 2.1초 = 재생 시작 지연 등 기존 여유(0.6초) + ui/theme.py::_wav_bytes_with_lead_silence()의
    # 끝 무음 패딩(tail_ms=1500ms, 2026-09-03 500ms->1500ms 재조정 — "끝음절 잘림" 안전망,
    # 그쪽 문서 참고). 이 함수가 재는 duration은 디스크 원본 파일 기준(패딩 전)이라, 실제
    # 재생은 시작+끝 패딩만큼 더 길어진다 — 마이크가 그 패딩이 아직 재생 중인데 먼저
    # 풀리지 않게 맞춘다.
    mute_until = time.monotonic() + duration + 2.1
    st.session_state["_tts_mute_until"] = max(st.session_state.get("_tts_mute_until", 0.0), mute_until)


def _render_cached_speech(message: str, *, nonce: int | str = 0) -> None:
    """speak()로 이미 이 문구를 말한 적 있다면(캐시 존재) 음성만 자동재생한다(재생바는 없음).

    screen_cooking_step()과 같은 이유로 필요하다 — speak()가 그 자리에서 그리는
    재생 위젯은 바로 뒤따르는 goto()의 st.rerun()에 지워진다. 그래서 이 문구로
    전환해 들어온 화면 자신이 매번 다시 그려질 때도 캐시를 직접 찾아 재생해야
    실제로 음성이 나온다. 캐시가 아직 없으면(예: speak() 실패) 조용히 아무것도 안
    한다 — 화면 텍스트는 이미 위에 따로 표시돼 있어서다.

    2026-08-21: "저장이 완료됐어요!" 화면에서 재생바(원형 버튼+파형)는 안 보이고
    음성만 나오면 좋겠다는 요청으로 render_audio_player() 대신 화면 없는
    render_audio_autoplay()를 쓴다.

    nonce(2026-08-23 추가) — cooking_step의 "다시"(_audio_replay_nonce)와 같은 이유:
    파일 경로가 안 바뀌면 프론트엔드가 "이미 로드된 오디오"로 보고 autoplay를 다시
    실행하지 않는다. recipe_confirm처럼 같은 화면에 계속 머문 채로 "다시 말해줘"를
    받아 같은 문구를 한 번 더 들려줘야 하는 화면은 호출부가 이 값을 올려서 넘겨야 한다.
    """
    path = _common_audio_path(message)
    if path.exists():
        _arm_tts_mute(path)
        render_audio_autoplay(path, nonce=nonce)


# 2026-08-26 요청 — 기본 문구를 "다음으로 넘어가고 있어요..."(진행 케이스 전용) →
# "처리하고 있어요..."(render_loading_overlay() 자신의 기본값, 그런데 시스템 관점 문구라
# "사용자 입장에서 봐야지"라는 재지적) → 최종적으로 이걸로 확정했다. 이 함수는 조회/
# 진행/재청취/이전/취소/등록 등 결과가 뭐가 될지 모르는 모든 처리 대기 구간에 공통으로
# 쓰여서 특정 동작을 전제로 한 문구는 안 맞고, "내 말을 들었다"는 확인 + "기다려달라"는
# 요청, 이 두 가지가 사용자가 실제로 궁금해하는 것이라는 판단으로 골랐다.

_LOADING_OVERLAY_SHOW_DELAY_S = 0.4
_LOADING_OVERLAY_MIN_VISIBLE_S = 0.3


class _LoadingOverlay:
    """_drain_mic_while() 호출 여러 번에 걸쳐 로딩 팝업 하나를 이어 쓰기 위한 핸들.

    2026-09-01 리포트 — "무엇을 만들고 싶으세요?에서 왜 조회 로딩이 두번 돌까"/
    "로딩바가 두 번 켜졌다 꺼진다": 발화 한 번 처리에 실제로 블로킹 대기 구간이
    두 번(1. process_utterance()의 LLM 추출+handle_utterance, 2. speak()의 TTS
    합성) 있는데, 각자 자기 몫의 _drain_mic_while()을 따로 호출해서 각자 팝업을
    한 번씩 껐다 켰다 하고 있었다 — 두 구간 사이는 세션 갱신 등 순수 파이썬 코드라
    실제로는 수십~수백 ms뿐인데도 그 잠깐 사이에 껐다 켜지는 게 "깜박깜박 두 번
    뜬다"로 눈에 띄었다. 이 핸들을 process_utterance()가 첫 대기 구간에서 만들어
    speak() 호출까지 그대로 넘기면, 두 구간이 팝업 하나(같은 st.empty() 슬롯, 같은
    "떴다"/"떴던 시각" 상태)를 이어서 쓰게 되어 중간에 꺼졌다 켜지는 순간이 없어진다.
    """

    __slots__ = ("slot", "shown", "shown_at", "start")

    def __init__(self) -> None:
        import time

        self.slot = st.empty()
        self.shown = False
        self.shown_at = 0.0
        self.start = time.monotonic()


def _close_loading_overlay(overlay: "_LoadingOverlay") -> None:
    """열려 있는 로딩 팝업을 닫는다 — _drain_mic_while(close=True)가 스스로 부르는
    것과 같은 로직이라 별도 함수로 뺐다. close=False로 팝업을 열어둔 채 반환받은
    호출부가, 결국 다음 _drain_mic_while() 단계 없이(예: speak() 없이 바로 goto())
    끝나는 분기에서 직접 불러 마무리를 책임진다 — 안 그러면 팝업이 화면에 계속
    남는다.

    2026-09-02 자체 재검토 — 닫은 뒤 overlay.shown을 다시 False로 되돌린다. 원래는
    한 번 닫으면 그걸로 끝(같은 overlay를 또 닫을 일이 없다는 전제)이라 안 건드렸는데,
    process_utterance()에 안전망으로 추가한 try/finally(아래 dispatch.py 참고)가 이미
    정상적으로 닫힌 overlay를 또 한 번 닫을 수 있어 이 함수 자체를 멱등하게(두 번
    불러도 안전하게) 만들 필요가 생겼다 — shown을 False로 되돌리면 두 번째 호출은
    `if overlay.shown:` 자체가 걸리지 않아 그냥 조용히 아무 것도 안 한다.
    """
    import time

    if overlay.shown:
        remaining = _LOADING_OVERLAY_MIN_VISIBLE_S - (time.monotonic() - overlay.shown_at)
        if remaining > 0:
            time.sleep(remaining)
        overlay.slot.empty()
        overlay.shown = False
        # 2026-08-25 리포트 — 아래 _drain_mic_while()의 같은 주석 참고("지워라"/
        # "다시 그려라" 신호가 너무 붙어 도착하면 잔상이 남는 문제) — 임시 완화책.
        time.sleep(0.05)


def _drain_mic_while(
    job: dict,
    *,
    loading_message: str | None = "말씀 잘 들었어요, 잠시만요...",
    overlay: "_LoadingOverlay | None" = None,
    close: bool = True,
) -> "_LoadingOverlay":
    """job["done"]가 True가 될 때까지 상시 마이크(webrtc)의 오디오 큐를 계속 비워준다.

    2026-08-23 리포트 실측 확인 — "된장찌개 레시피 알려줘"로 recipe_confirm까지는
    잘 넘어가는데 그 화면에서 마이크가 죽어있다는 것을 서버 로그(WEBRTC_DEBUG)로
    확인해보니, speak()의 TTS 합성(3~9초, GPU 블로킹) 동안 아무도 get_frames()를
    안 불러서 그 몇 초 사이에 브라우저가 스스로 연결을 끊었다
    (`DTLS shutdown by remote party` → `iceConnectionState completed -> closed`).
    STT 처리 중엔 이미 이 문제를 피하려고 계속 프레임을 뽑아내고 있었는데
    (_run_mic_loop() 안쪽 STT 대기 루프 참고), speak()의 TTS 합성 구간은 그 드레인
    루프 *바깥*(listen()이 텍스트를 반환하고 돌아온 뒤, process_utterance() 안)에서
    일어나서 똑같은 보호가 없었다. 이 함수를 speak()의 합성 대기 구간에도 똑같이
    적용해서, 메인 스레드가 몇 초씩 블로킹되는 동안에도 큐가 계속 비워지게 한다
    (그러면 aiortc의 ICE/RTCP 유지보수 스레드도 GIL을 계속 얻어서 제때 돌 수 있다).

    loading_message(2026-08-23 추가) — "발화 인식되고 다음 화면 준비하는 동안 다른 걸
    못 하게 로딩 팝업을 띄워달라"는 요청. 이 함수가 실제로 몇 초씩 블로킹되는 구간을
    독점하고 있으므로(speak()의 TTS 합성, dispatch.process_utterance()의 LLM/DB 조회
    둘 다 이 함수를 거침), 여기 한 군데서 팝업을 그리면 두 경우 다 자동으로 덮인다.
    None을 넘기면 팝업 없이 조용히 드레인만 한다(현재는 항상 기본 메시지로 부름).

    2026-08-24 리포트 — 이 팝업이 다음 화면까지 잔상으로 남고, 그 상태에서 계속
    진행하면 오디오가 두 개 겹쳐 들리는 문제 실측 확인. st.markdown()으로 그냥 그리기만
    하면 그 엘리먼트가 이 스크립트 실행이 끝날 때까지(그리고 다음 rerun이 완전히
    반영될 때까지) DOM에 남아있는데, 화면 전환 시점에 rerun이 연달아 겹치면(마이크
    재연결 강제 rerun 등) 프론트엔드가 이 잔상을 제때 못 지우는 것으로 보인다.
    st.empty()로 자리를 직접 잡아두고, 대기가 끝나는 즉시(다음 코드로 넘어가기 *전에*)
    명시적으로 비워서 — 다음 rerun의 DOM 정리에 기대지 않고 이 함수 안에서 스스로
    정리를 끝낸다.

    2026-08-25 리포트 — "메롱"처럼 결국 미분류로 아무 일도 안 하는 발화에도 이 팝업이
    똑같이 뜬다는 지적. process_utterance()는 결과(진행/미분류 등)를 미리 알 수
    없어서 LLM/임베딩 호출을 항상 먼저 해야 하지만, 그 자체가 항상 몇 초씩 걸리는 건
    아니다(GPU가 이미 데워져 있으면 미분류 판정까지 수백 ms 안에 끝나는 경우도 많음).
    처리 시작하자마자 무조건 팝업부터 띄우는 대신, `_SHOW_DELAY_S`(0.4초)보다 오래
    걸릴 때만 뒤늦게 띄운다 — 빨리 끝나는 처리(성공이든 미분류든)는 팝업이 아예 안
    보이고, 진짜 오래 걸리는 처리만 "넘어가고 있어요" 안내를 받는다.

    2026-08-26 재요청 — "자꾸 깜박깜박거려서 불편하다": LLM 추출(extract_intent_llm())은
    결과가 뭐든(미분류 포함) 항상 먼저 거쳐야 하고 그 자체가 이미 _SHOW_DELAY_S를 자주
    넘겨서, 처리가 딱 0.4초를 살짝 넘긴 시점에 job이 끝나버리면 팝업이 몇십~몇백 ms만
    떴다 사라지는 "반짝임"이 됐다. render_loading_overlay()에 페이드인을 추가해 나타날
    때는 부드럽게 만들었고, 여기서는 한번 뜬 이상 최소 `_MIN_VISIBLE_S`만큼은 붙어있게
    보장한다 — 뜨자마자 바로 지워지는 경우가 없어져서 눈에 실제로 "안내가 있었다"고
    인지할 시간을 준다. 표시 여부(뜨는 시점)는 안 건드린다 — 처리 시간 자체를 더
    기다리게 만드는 게 아니라, 이미 뜨기로 결정된 뒤의 "얼마나 오래 보이는가"만 바꾼다.

    overlay/close(2026-09-01 추가, "로딩바가 두 번 켜졌다 꺼진다" 리포트 대응) — 위
    _LoadingOverlay 문서 참고. overlay를 안 넘기면(기본값) 지금까지와 완전히 같게
    이 호출 안에서 팝업을 새로 만들고 끝날 때 스스로 닫는다. 이전 단계가 만든
    _LoadingOverlay를 넘기면 그 슬롯/표시 상태를 그대로 이어 쓴다 — close=False면
    끝나도 닫지 않고 그대로 반환하므로, 이어받은 다음 단계(speak() 등)가 마무리
    책임을 진다. 반환값은 항상 이번에 실제로 쓴 _LoadingOverlay(새로 만들었든
    넘겨받았든)라, 호출부가 close=False로 부른 뒤 그대로 다음 단계에 넘기면 된다.
    """
    import queue
    import time

    if overlay is None:
        overlay = _LoadingOverlay()

    while not job["done"]:
        if (
            loading_message
            and not overlay.shown
            and (time.monotonic() - overlay.start) >= _LOADING_OVERLAY_SHOW_DELAY_S
        ):
            with overlay.slot:
                render_loading_overlay(loading_message)
            # 2026-08-26 요청 — 화면을 안 보고 있어도(핵심 컨셉이 "화면 안 보고 음성만으로")
            # 처리 중이라는 걸 알 수 있게, 같은 지점에서 짧은 효과음도 한 번 같이 울린다
            # (render_processing_chime() 문서 참고). start(이 드레인 호출의 시작 시각)를
            # nonce로 그대로 넘기면 호출마다 자연히 값이 달라져 autoplay가 매번 재실행된다.
            render_processing_chime(nonce=overlay.start)
            overlay.shown = True
            overlay.shown_at = time.monotonic()

        context = st.session_state.get(_mic_component_key())
        receiver = getattr(context, "audio_receiver", None) if context is not None else None
        if receiver is None:
            time.sleep(0.1)
            continue
        try:
            receiver.get_frames(timeout=0.2)
        except queue.Empty:
            pass
        except AttributeError:
            # _run_mic_loop()의 같은 레이스와 같은 이유 — 드레인 도중 연결이 끊기면
            # audio_receiver가 None으로 바뀔 수 있다. 조용히 다음 루프에서 다시 확인.
            pass

    if close:
        _close_loading_overlay(overlay)
    return overlay


def speak(
    message: str,
    *,
    recipe_id: str | None = None,
    step_number: int | None = None,
    hidden: bool = False,
    _loading_overlay: "_LoadingOverlay | None" = None,
) -> None:
    """TTS로 응답을 재생하고 채팅 로그에 남긴다. 합성 실패는 조용히 삼키지 않는다(EC-05) —
    화면 텍스트는 항상 남고, 음성만 실패했다는 걸 사용자에게 알린다.

    _loading_overlay(2026-09-01 추가, "로딩바가 두 번 켜졌다 꺼진다" 리포트 대응) —
    process_utterance()가 자신의 LLM/DB 대기 단계에서 만든 _LoadingOverlay를 넘겨
    받으면, 이 함수의 TTS 합성 대기도 같은 팝업을 이어 쓰고 여기서 마지막으로 닫는다
    (voice_io._LoadingOverlay/_drain_mic_while() 문서 참고). 기본값 None은 지금까지
    처럼 이 함수 혼자 팝업을 만들고 닫는 단독 호출이다 — dispatch.py 외 다른
    호출부(cooking.py/register.py 등)는 이 인자를 안 넘겨서 동작이 그대로다.

    2026-08-21: st.audio()는 Streamlit이 rerun마다 <audio> 태그를 새로 만드는 방식이라
    자동재생·수동 재생 버튼 둘 다 안 먹히는 문제가 실측으로 확인됐다(브라우저에서 재생
    버튼을 눌러도 무반응). 대신 ui/streamlit_screens/cooking_step.py에서 이미 실제로
    잘 작동하는 render_audio_player()(진짜 <audio autoplay> + JS 우회)를 그대로 쓴다.

    recipe_id·step_number가 둘 다 주어지면(=이 메시지가 특정 레시피의 특정 조리 단계
    안내문일 때) ui/assets/audio/<recipe_id>/<step:02d>.wav로 캐싱한다 — cooking_step.py와
    같은 경로 규칙이라 두 화면이 같은 캐시를 공유한다. 그 외(확인 메시지·에러 안내 등
    1회성 문구)는 문구 자체의 해시를 캐시 키로 써서, 자주 반복되는 고정 문구
    ("1단계예요, 이전 단계가 없어요." 등)도 같이 재사용된다. 둘 다 로컬 CPU 기준
    문장당 최대 몇 분 걸리는 재합성을 피하기 위함이다(2026-08-20 실측).

    hidden=True: register_steps의 "네, 저장할게요"처럼 speak() 직후 바로 goto()로
    다른 화면으로 넘어가는 호출부에서 쓴다. render_audio_player()(재생바)로 그려도
    goto()의 st.rerun()이 곧장 화면을 바꿔버려서 재생바가 "떴다가 사라지는" 것처럼
    보일 뿐 실제로 남지도 않는데, 그 순간 그려지는 재생바 자체가 화면 깜빡임으로
    보인다는 지적(2026-08-21)으로 추가됨 — 합성/캐싱은 그대로 하되 화면에는
    render_audio_autoplay()(화면 없는 자동재생)만 그린다. 도착 화면이 같은 문구를
    _render_cached_speech()로 다시 찾아 들려주는 경우, 실제로 들리는 소리는 그쪽이다.

    2026-08-22엔 여기서 합성 대기 중 로딩바(GIF → SVG 마스코트로 두 번 갈아탐)를
    보여줬는데, 2026-08-23 사용자 확인 결과 0.2초마다 placeholder를 다시 그리는 폴링
    루프 자체가 오히려 렉처럼 느껴진다는 지적으로 걷어냈다 — 로딩바 없이 그냥
    블로킹으로 기다린다(합성 자체는 GPU 기준 문장당 3~9초, docs/decisions.md #2).
    그래서 이제 show_loading 파라미터도 없다(있으나 마나였던 옵션이라 같이 정리).
    """
    st.session_state.chat_log.append(("ai", message))
    try:
        if recipe_id and step_number:
            audio_path = _AUDIO_DIR / str(recipe_id) / f"{step_number:02d}.wav"
        else:
            audio_path = _common_audio_path(message)

        # [PERF] — speak() 호출마다 캐시 히트/미스를 한 줄로 남긴다(캐시 미스 쪽
        # 실제 합성 시간은 아래 _run_synthesis()의 [PERF] TTS 로그가 별도로 남김).
        print(f"[PERF] TTS cache {'HIT' if audio_path.exists() else 'MISS'} path={audio_path.name}", flush=True)

        if not audio_path.exists():
            # 2026-08-23 — GPU 합성(3~9초) 자체는 백그라운드 스레드로 돌리고, 메인
            # 스레드는 그동안 _drain_mic_while()로 마이크 큐를 계속 비운다(위 함수
            # 문서 참고 — 안 그러면 이 블로킹 구간 동안 상시 마이크 연결이 브라우저
            # 쪽에서 스스로 끊긴다). 2026-09-01 — 실제 GPU 호출은 gpu_worker_pool의
            # 별도 프로세스로 보내고 이 스레드는 그 Future가 끝나길 기다리기만 한다
            # (gpu_worker_pool.py 문서 참고 — prefetch_remaining_steps_audio()와의
            # 직렬화는 이제 프로세스 풀 자체의 워커 수만큼만 자연히 제한됨).
            job: dict = {"done": False, "error": None}
            # 2026-09-02 — 세션 짧은 식별자(ui.session.init_state() 문서 참고)를 배경
            # 스레드 시작 전에 메인 스레드에서 미리 읽어 클로저 기본값으로 넘긴다 —
            # st.session_state를 배경 스레드에서 직접 읽는 건 이 파일 다른 곳(job/
            # steps_cache 등)과 같은 이유로 위험한 패턴이라서다. gpu_worker_pool은
            # 별도 프로세스라 session_state 자체에 접근 못 하므로, 이 값을 인자로
            # 명시적으로 넘겨야 그 프로세스 안의 [TTS_DEBUG] 로그에도 찍힌다.
            _sid = st.session_state.get("_sid")

            def _run_synthesis(job=job, sid=_sid) -> None:
                import time

                try:
                    # 2026-09-02 — _get_synthesis_lock() 문서 참고. 실측 확인된 원인:
                    # 이 실시간 합성과 prefetch_remaining_steps_audio()의 백그라운드
                    # 합성이(또는 같은 표준 레시피를 비슷한 시점에 연 다른 사용자의
                    # 실시간 합성이) 같은 audio_path에 락 없이 동시에 쓰면서, sf.write()가
                    # 원자적이지 않아 재생 시점에 아직 다 안 쓰인/잘린 파일을 읽는
                    # 경우가 있었다("끝음절이 자꾸 잘린다" 리포트) — 락으로 직렬화하고,
                    # 락을 기다리는 동안 다른 쪽이 이미 만들었으면 조용히 건너뛴다.
                    with _get_synthesis_lock(audio_path):
                        if not audio_path.exists():
                            # [PERF] 태그 설명은 _run_stt() 문서 참고. 캐시 히트면 이 분기
                            # 자체를 안 타서(위 audio_path.exists() 검사) 로그가 안 찍히는데,
                            # 그게 정상이다 — "찍혀야 하는데 안 찍힌다"면 캐시가 실제로 안
                            # 먹고 있다는 신호이므로 이 로그의 유무 자체가 캐시 히트/미스
                            # 판별에도 쓰인다.
                            _tts_t0 = time.monotonic()
                            waveform, sample_rate = gpu_worker_pool.submit_tts(message, session_id=sid).result()
                            print(f"[PERF] TTS {time.monotonic() - _tts_t0:.2f}s (cache miss)", flush=True)
                            audio_path.parent.mkdir(parents=True, exist_ok=True)
                            _write_wav_atomic(audio_path, waveform, sample_rate)
                except Exception as exc:  # noqa: BLE001 — 아래에서 다시 던져서 기존 except가 처리
                    job["error"] = exc
                finally:
                    job["done"] = True

            threading.Thread(target=_run_synthesis, daemon=True).start()
            # 2026-09-01 — 이 대기가 process_utterance()의 앞 단계(LLM/DB)와 이어붙는
            # 두 번째 단계일 수 있다(_loading_overlay 문서 참고) — 넘겨받았으면 그
            # 팝업을 그대로 이어 쓰고, 여기가(TTS 합성이) 항상 마지막 단계이므로
            # close=True로 여기서 닫는다.
            _drain_mic_while(job, overlay=_loading_overlay, close=True)
            if job["error"] is not None:
                raise job["error"]
        elif _loading_overlay is not None:
            # 2026-09-01 — TTS 캐시 히트라 이 함수 안에서는 대기가 필요 없지만, 호출부가
            # 앞 단계에서 열어둔 팝업을 이 speak() 호출이 마지막 단계로서 닫아줄 걸로
            # 기대하고 있다(process_utterance() 각 분기 참고) — 여기서 대신 닫는다.
            _close_loading_overlay(_loading_overlay)

        # 2026-08-25 — hidden=True에서도 render_audio_autoplay()로 실제로 한 번 틀고
        # 있었다. hidden=True는 항상 "이 문구를 goto() 직전에 미리 합성/캐싱만 해두고,
        # 실제 재생은 도착 화면이 _render_cached_speech()/render_step_card()로 같은
        # 캐시를 다시 찾아 들려준다"는 용도로만 쓰인다(모든 호출부 확인 — dispatch.py의
        # 조회/진행, register.py의 저장완료 등 전부 도착 화면이 재생을
        # 담당). 그런데 goto()의 st.rerun()이 이 iframe을 지우기 전 아주 짧게라도
        # 브라우저가 재생을 시작해버리면, 도착 화면이 같은 파일을 처음부터 다시 재생할
        # 때 "음성이 두 번 겹쳐 들린다"는 실측 리포트(2026-08-25)로 확인됐다. 이 자리
        # (hidden 쪽)는 애초에 들려줄 필요가 없어서 render_audio_autoplay() 호출만
        # 없앤다 — _arm_tts_mute()는 그대로 둔다. render_step_card()(cooking_step
        # 도착 화면)는 자기 스스로 뮤트를 걸지 않고 이 speak(hidden=True) 호출의
        # _arm_tts_mute() 부작용에 기대는 구조라(theme.py에 별도 뮤트 호출이 없음,
        # 2026-08-25 확인), 여기서 뮤트까지 같이 없애면 그 경로에서 TTS가 자기
        # 목소리를 마이크로 다시 주워듣는 회귀가 생긴다.
        _arm_tts_mute(audio_path)
        if not hidden:
            render_audio_player(audio_path)
    except Exception as exc:  # noqa: BLE001 — 사용자에게 보여줄 실패이지 숨길 실패가 아님
        st.warning(f"음성 재생에 실패했어요(텍스트는 위에 표시돼요): {exc}")


def _synthesize_and_cache(text: str, audio_path: Path, session_id: str | None = None) -> None:
    """백그라운드 스레드에서 실행되는 합성 함수 — speak()와 캐싱 규칙은 같지만 st.* API를
    전혀 안 쓴다(Streamlit 위젯 호출은 ScriptRunContext가 있는 메인 스레드에서만 안전해서,
    백그라운드 스레드에서 st.spinner/st.warning 등을 쓰면 경고가 뜨거나 깨질 수 있음).
    실패해도 조용히 넘어간다 — 프리페치일 뿐이라 실패하면 나중에 speak()가 그 자리에서
    다시 시도한다(EC-05는 speak() 쪽에서 이미 담당).

    session_id(2026-09-02) — 호출부(prefetch_remaining_steps_audio())가 메인 스레드에서
    미리 읽어 넘긴 세션 짧은 식별자. 이 스레드 자신은 st.session_state에 접근 못 하므로
    (ScriptRunContext 필요, 위 문서와 같은 이유) 직접 읽을 수 없다 — gpu_worker_pool
    워커 프로세스 안의 [TTS_DEBUG] 로그에 찍히게 그대로 전달만 한다."""
    if audio_path.exists():
        return
    # 2026-09-02 — _get_synthesis_lock() 문서 참고. speak()의 실시간 합성과 이 경로가
    # 같은 audio_path를 동시에 쓰는 걸 막는다.
    with _get_synthesis_lock(audio_path):
        try:
            if audio_path.exists():  # 락을 기다리는 동안 다른 쪽이 이미 만들었을 수 있음
                return
            waveform, sample_rate = gpu_worker_pool.submit_tts(text, session_id=session_id).result()
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            _write_wav_atomic(audio_path, waveform, sample_rate)
        except Exception:  # noqa: BLE001 — 프리페치 실패는 speak()가 다시 시도하므로 조용히 넘어감
            pass


def prefetch_remaining_steps_audio(view: dict, step_number: int) -> None:
    """지금 보고 있는 조리 단계 화면에서, 다음 단계부터 마지막 단계까지 전부 백그라운드에서
    순서대로 미리 합성해 캐싱해둔다(2026-08-22 요청 — "1페이지를 보고 있는 동안 2/3/4
    페이지 오디오가 눈에 안 보이지만 계속 만들어지게"). TTS 합성 자체는 GPU에서도 문장
    길이에 따라 3~9초 걸리는 게 실측됐고(docs/decisions.md #2), 더 줄이려던 torch.compile
    시도는 재컴파일 스톨 위험으로 보류했다(2026-08-22) — 그래서 합성 속도 자체 대신,
    사용자가 화면을 보고 있는 시간 동안 쉬지 않고 뒷단계들을 계속 만들어둬서, 뒤로 갈수록
    "다음"이라고 말했을 때 기다리는 시간이 거의 사라지게 한다.

    한 번에 여러 스레드를 띄우는 대신 스레드 하나가 남은 단계를 순서대로 도는 구조다.
    2026-09-01 — GPU 호출 자체는 이제 gpu_worker_pool의 프로세스 풀로 가지만, 이
    프리페치는 여전히 "지금 당장 필요 없는 낮은 우선순위 작업"이라 일부러 순차로
    돈다 — 한꺼번에 여러 단계를 동시에 던지면 워커를 다 차지해버려서, 그 사이
    들어오는 실시간 사용자 요청(speak()의 실시간 합성, STT 등)이 워커 풀에서
    대기해야 하는 역효과가 생긴다.

    레시피 하나당(recipe_id 기준) 세션에서 딱 한 번만 이 백그라운드 작업을 시작한다
    (st.session_state의 "_full_prefetch_started" 집합으로 추적) — screen_cooking_step()이
    매 rerun(마이크 입력 대기 등)마다 다시 호출돼도 중복으로 스레드가 쌓이지 않게 한다.
    이미 캐싱된 단계는 _synthesize_and_cache() 안의 존재 확인으로 건너뛰므로, 사용자가
    이미 지나간 단계를 다시 합성하는 낭비는 없다.

    2026-08-22 추가 — 사용자가 이 레시피를 완주하지 않고 처음 화면으로 돌아가면
    버려진 레시피의 남은 단계를 계속 만들면 안 된다는 지적으로, 매 단계 합성
    전에 "지금도 이 레시피가 활성 상태인지"를
    확인해서 아니면 그 자리에서 멈춘다. st.session_state를 백그라운드 스레드에서
    직접 읽는 건 Streamlit이 지원하지 않는 패턴이라(ScriptRunContext 필요), 대신
    st.session_state["_active_recipe_box"](평범한 dict, src/app.py::main()이 매
    rerun마다 pipeline_session["current_recipe_id"]로 갱신)의 참조만 스레드에
    넘겨서 그 dict만 읽는다 — dict 읽기/쓰기는 스레드 안전이라 문제없다.
    """
    recipe_id = view["recipe_id"]
    started = st.session_state.setdefault("_full_prefetch_started", set())
    if recipe_id in started:
        return
    started.add(recipe_id)

    remaining = view["steps"][step_number:]  # steps는 0-indexed라 step_number가 곧 "다음 단계"부터
    if not remaining:
        return

    active_recipe_box = st.session_state.setdefault("_active_recipe_box", {"recipe_id": recipe_id})
    # 2026-09-02 — _synthesize_and_cache() 문서 참고. 스레드 시작 전 메인 스레드에서 미리 읽는다.
    _sid = st.session_state.get("_sid")

    def _run(sid=_sid) -> None:
        import time

        for step in remaining:
            if active_recipe_box.get("recipe_id") != recipe_id:
                return  # 사용자가 이 레시피를 떠났음 — 남은 단계는 만들지 않고 중단
            step_num = step.get("step_number")
            audio_path = _AUDIO_DIR / str(recipe_id) / f"{step_num:02d}.wav"
            # 2026-09-01 — step["text"]는 [TERM:용어] 태그가 남은 원본이다(term_dict.py
            # 참고). 이 프리페치가 speak()보다 먼저 이 경로에 캐시 파일을 써버리면(사용자가
            # 이 화면에 들어오자마자 백그라운드로 바로 시작), speak()는 audio_path.exists()만
            # 보고 재합성을 건너뛰므로 여기서 원본 태그를 안 풀면 dispatch.py의
            # resolve_for_tts() 적용이 무의미해진다 — 나중에 어떤 경로로 speak()가
            # 불려도 항상 이 캐시가 먼저 이긴다. 반드시 여기서 미리 풀어서 캐싱한다.
            _synthesize_and_cache(resolve_for_tts(step["text"]), audio_path, session_id=sid)
            # 2026-08-28 — 한 단계 합성이 끝나면 다음 단계로 바로 안 넘어가고 잠깐 쉰다.
            # 2026-09-01 — 이제 GPU 호출은 gpu_worker_pool의 프로세스 풀로 가지만, 워커
            # 개수는 유한하다(GPU_WORKER_COUNT). 이 프리페치가 쉬지 않고 계속 다음
            # submit_tts()를 던지면 워커를 계속 붙잡아서, 그 사이 도착한 사용자 발화의
            # STT/실시간 speak()가 빈 워커를 못 찾고 대기열에서 밀릴 수 있다("다음"이라고
            # 했는데 전사부터 몇 초 걸리는 리뷰 지적). 이 유휴 구간 동안엔 프리페치가
            # 워커를 안 건드리므로 대기 중인 실시간 작업이 확실히 먼저 잡는다.
            time.sleep(0.6)

    threading.Thread(target=_run, daemon=True).start()


# 2026-08-23 — 상시 마이크(실시간 스트리밍 인식). 예전엔 st.audio_input()으로 "녹음 시작
# 버튼 → 말하기 → 정지 버튼"을 매 발화마다 눌러야 했다(EC-04 폴백은 여전히 텍스트 입력).
# 이제는 세션당 한 번만 마이크를 켜면(브라우저 권한 요청은 사용자 클릭이 있어야만 가능해서
# 최초 1번은 여전히 필요함, streamlit-webrtc의 기본 Start 버튼) 그다음부터는 계속 듣고
# 있다가 ui/mic_vad.py의 MicVadSegmenter(silero-vad)가 "말하다가 조용해지면 거기까지 한
# 발화"로 자동으로 잘라 바로 인식한다 — 화면이 바뀌어도(다른 screens/*.py로 이동해도)
# 같은 키(_MIC_KEY)로 계속 같은 연결을 쓰므로 끊기지 않는다.
#
# 화면마다 다른 이름의 위젯 키를 쓰던 옛 설계(show_mic로 중복 녹음 위젯을 숨김)와 달리,
# 이제는 세션 전체가 마이크 연결 하나를 공유해야 해서 listen()을 부르는 모든 화면이 매번
# 이 컴포넌트를 렌더링해야 한다(안 그리면 그 화면에 머무는 동안 연결이 끊긴 걸로 보임).
_MIC_KEY = "chefear_mic"

# 2026-08-23 임시 진단 변수(위 _run_mic_loop() 안의 [FRAME_DEBUG] 출력용) — 원인 확인되면 지울 것.
_FRAME_DEBUG_COUNT = 0


def _get_segmenter():
    """세션당 하나의 MicVadSegmenter를 재사용한다 — 화면이 바뀌어도(재실행마다 새로
    안 만들어야) 문장 중간에 잘려서 상태(현재 발화 중인지 등)가 리셋되지 않는다."""
    if "_mic_segmenter" not in st.session_state:
        from mic_vad import MicVadSegmenter  # 지연 import 이유는 stt.infer와 동일(파일 상단 참고)

        st.session_state["_mic_segmenter"] = MicVadSegmenter()
    return st.session_state["_mic_segmenter"]


def _mic_component_key() -> str:
    """지금 세대(generation)의 webrtc_streamer() 컴포넌트 key — 아래 _recover_dead_mic()
    참고. 세대가 올라가면 완전히 새 컴포넌트로 취급돼(streamlit_webrtc 입장에선 이전
    연결과 아무 관계 없는 최초 마운트) 강제로 처음부터 다시 연결을 시도한다."""
    return f"{_MIC_KEY}_{st.session_state.get('_mic_gen', 0)}"


def _mic_truly_alive(context) -> bool:
    """context.state.playing만 믿지 않고, 실제 워커(오디오 수신기)가 살아있는지까지
    같이 확인한다(2026-08-23 추가).

    실측 확인(WEBRTC_DEBUG 로그) — 연결이 끊긴 직후 한동안 `state.playing=True`인데
    `has_worker=False`인 "유령" 상태가 나타난다. streamlit-webrtc가 워커를 약한 참조
    (weakref)로만 들고 있어서(설치된 패키지 주석: "the worker is held via a weakref on
    the enclosing context, so it can also disappear under us") 워커의 백그라운드
    스레드가 먼저 조용히 끝나버리고, 프론트엔드가 그 사실을 새 컴포넌트 값으로 아직
    보고하지 않은 그 사이엔 state.playing이 낡은 True 값 그대로 남는다. context.audio_receiver
    (워커가 사라지면 None을 돌려주는 공개 프로퍼티)까지 같이 확인해야 이 "유령" 상태를
    "아직 살아있다"고 착각하지 않는다."""
    state = getattr(context, "state", None)
    playing = bool(getattr(state, "playing", False))
    has_worker = getattr(context, "audio_receiver", None) is not None
    return playing and has_worker


def _rate_limited_rerun(min_interval_s: float = 1.0) -> None:
    """st.rerun()을 바로 부르지 않고, 마지막으로 부른 지 min_interval_s 이상 지났을
    때만 부른다(2026-08-23 추가).

    "연결이 죽은 채 저절로 안 돌아옴" 안전장치(_recover_dead_mic()/_run_mic_loop())가
    st.rerun()으로 재실행을 강제하는데, 세대를 아직 못 바꾼 채(예: 진짜 협상 중이라
    signalling=True라서 _recover_dead_mic()이 아직 세대를 안 바꿈) 계속 "안 살아있음"
    으로 보이면 아무 지연 없이 재실행만 반복하는 바쁜 루프가 될 수 있다 — 원래 이
    저장소가 처음부터 피하려던 문제(협상 중인 연결을 재실행이 방해해서 죽이는 것)와
    같은 종류라 조심스럽게 다룬다. 최소 간격을 둬서 정상적인 협상 진행 시간을 뺏지
    않으면서도, 결국엔 다음 판정 기회를 계속 준다."""
    import time

    now = time.monotonic()
    last = st.session_state.get("_mic_last_forced_rerun", 0.0)
    if now - last >= min_interval_s:
        st.session_state["_mic_last_forced_rerun"] = now
        st.rerun()


def mic_is_playing() -> bool:
    """상시 마이크(webrtc_streamer())가 지금 실제로 연결돼 있는지 — start 화면의
    render_big_mic()이 "준비 상태" 색 표시에 쓴다(2026-08-23 추가).

    _run_mic_loop()을 다시 부르지 않고도 확인할 수 있다 — streamlit_webrtc가 연결
    상태를 st.session_state[key]에 저장해두므로(component.py의 WebRtcStreamerContext),
    그 값을 그냥 읽기만 한다. 아직 한 번도 연결을 시도한 적 없는 세션(해당 키 자체가
    없음)이면 조용히 False."""
    return _mic_truly_alive(st.session_state.get(_mic_component_key()))


# 2026-09-01 — 아래 _recover_dead_mic() 문서 참고. "죽었다" 판정을 debounce하는
# 최소 지속 시간 — 이보다 짧게 죽어있다 살아나면(정상 재협상 중이었던 것) 세대를
# 아예 안 올린다.
_MIC_DEAD_DEBOUNCE_S = 2.0


def _recover_dead_mic() -> None:
    """한 번은 정상 연결됐던 마이크가 완전히 끊긴 채(_mic_truly_alive()가 False —
    "checking" 중이 아니라 진짜 종료됐거나 워커가 사라진 상태) 저절로 안 돌아오면,
    컴포넌트 key 자체를 새로 바꿔서 다음 webrtc_streamer() 호출이 완전히 새 컴포넌트로
    (이전 연결과 무관하게) 마운트되게 강제한다(2026-08-23 추가).

    desired_playing_state=True가 이론상 STOPPED 상태에서 알아서 재시작해야 하는데
    (streamlit_webrtc 프론트엔드 소스 실측: desiredPlayingState=true면 STOPPED일 때
    start()를 다시 부름), 실사용에서는 화면 전환 직후 끊긴 뒤 브라우저 주소창의 마이크
    사용 아이콘까지 사라진 채 저절로 안 돌아오는 게 실측 확인됐다(정확한 프론트엔드
    내부 조건은 미확인). 그 자동 재시작 경로를 완전히 믿는 대신, 아예 새 컴포넌트
    인스턴스를 만들어 강제로 처음부터 다시 시작시키는 더 확실한 방법을 쓴다 — 이미
    한 번 연결에 성공했던 세션에서만 적용한다(아직 한 번도 연결 안 된 상태, 즉 최초
    로딩 중이거나 사용자가 권한을 아직 안 줬을 뿐인 정상 대기 상태를 오작동으로 착각해
    불필요하게 재마운트하지 않기 위함).

    2026-09-01 추가 — "Cannot create so many PeerConnections" 크래시 원인 규명.
    login/my_recipes/edit_recipe/signup에서 register_ingredients와 똑같이
    listen_for_speech=False로 마이크를 계속 그렸는데도(app.py::main()의 해당 분기 옛
    주석, login.py 문서 참고 — register_steps는 listen_for_speech를 안 넘겨서 실제로는
    STT까지 계속 돌리고 결과만 버리는 더 무거운 경로라 정확히 같은 패턴은 아니다) 실사용
    중 이 크래시가 재현돼 결국 마이크 자체를 안 그리는 쪽으로 후퇴했었다.
    streamlit_webrtc 프론트엔드 소스를 직접 읽어 확인한 진짜 메커니즘: 이 넷은 이
    프로젝트에서 유일하게 사용자가 "처음 화면으로"/"내 정보" 버튼으로 짧은 간격에
    반복해서 왔다갔다 하는 화면들이다(등록 화면들은 순서대로 한 번만 지나감). WebRTC
    재협상은 몇 초 걸릴 수 있는데(RunPod 배포 환경의 ICE/TURN 왕복), 그 몇 초 사이에
    또 다른 화면으로 나갔다 돌아오면 이 함수가 "아직 재협상 중이라 안 죽었다"와 "진짜
    죽었다"를 구분 못 하고 바로 세대를 올렸다 — 세대가 바뀌면 _mic_component_key()가
    이전에 한 번도 쓰인 적 없는 새 문자열을 돌려줘서, component.py::
    _get_or_create_context()가 그 key를 st.session_state에서 못 찾고 완전히 새
    WebRtcStreamerContext를 만든다(같은 key가 잠시 안 그려졌다 다시 그려질 때 도는
    "orphan-reset" 분기와는 다른, 더 확실한 "그냥 처음 보는 key" 경로다) — 결국 새
    RTCPeerConnection이 만들어진다는 결론은 같다. 이 왕복이 반복될수록(브라우저가 이전
    연결들을 완전히 정리하는 속도보다 빠르게) 연결이 계속 쌓여 결국 브라우저의
    PeerConnection 개수 상한에 부딪혔다.

    "죽었다"는 판정을 한 번의 관측이 아니라 _MIC_DEAD_DEBOUNCE_S만큼 계속 죽어있는
    상태가 이어질 때만 확정하도록 바꾼다 — 진짜 재협상 중이면 그 사이 다시 살아있는
    걸로 관측되는 순간(아래 _mic_truly_alive() 분기) 바로 리셋된다.

    2026-09-02 자체 재검토(서브에이전트 리뷰)로 찾은 한계 — 아래 마지막 문단은 원래
    "실제로 끊긴 경우도 여전히 정상적으로(그냥 몇 초 늦게) 세대를 올려 복구한다"고
    적었는데, 정확하지 않다. _run_mic_loop()이 연결 안 됨을 감지하면 매번
    _rate_limited_rerun()(1초당 최대 1회)으로 재실행을 강제하는데, 이 debounce 로직이
    "죽었다"를 확정하려면 그 재실행이 최소 두 번 더(_mic_dead_since가 찍힌 뒤 2초 이상
    지나서) 일어나야 한다 — 그런데 _rate_limited_rerun()이 첫 재실행을 곧바로 걸고 나면
    그 직후 재실행에서는 "마지막 강제 재실행 뒤 1초가 안 지났다"는 이유로 더 이상
    재실행을 걸지 않는다. 이후로는 브라우저(프론트엔드)가 스스로 새 컴포넌트 값을
    보내와 on_change 콜백이 재실행을 걸어주는 경우에만 이 함수가 다시 불려서 2초
    debounce를 마저 채울 수 있다 — 마이크 연결이 사용자 상호작용도, 프론트엔드 쪽
    상태 변화 이벤트도 전혀 없이 완전히 조용한 채로 죽어있으면(예: 로그인 화면에서
    비밀번호를 입력하는 동안 네트워크가 끊긴 경우), 이 함수가 다시 불릴 계기 자체가
    당분간 없어서 세대 교체가 늦어질 수 있다(무한정 멈추는 건 아니다 — 사용자가 아무
    조작이나 하면 그 rerun이 다시 이 함수를 부른다). st.fragment(run_every=...)로
    확실한 폴링을 붙이는 방안도 검토했으나, 이 라이브러리는 st.fragment 자체가 연결을
    죽이는 걸로 이미 확인된 바 있어(_run_mic_loop() 문서의 2026-08-23 리포트 참고) 그
    방향은 피했다 — 실측 재현 없이 이 타이밍 메커니즘을 더 손대는 위험을 감수하기보다,
    이 한계를 있는 그대로 남겨둔다.
    """
    import time

    context = st.session_state.get(_mic_component_key())
    state = getattr(context, "state", None)
    signalling = bool(getattr(state, "signalling", False))

    if _mic_truly_alive(context):
        st.session_state["_mic_ever_connected"] = True
        st.session_state["_mic_dead_since"] = None
        return

    if st.session_state.get("_mic_ever_connected") and not signalling:
        dead_since = st.session_state.get("_mic_dead_since")
        if dead_since is None:
            # 이번이 "죽어있다"는 첫 관측 — 바로 세대를 올리지 않고 시각만 남겨둔다.
            st.session_state["_mic_dead_since"] = time.monotonic()
            return
        if time.monotonic() - dead_since < _MIC_DEAD_DEBOUNCE_S:
            # 아직 debounce 창 안 — 재협상이 정상적으로 진행 중일 수 있으니 좀 더 지켜본다.
            return
        st.session_state["_mic_gen"] = st.session_state.get("_mic_gen", 0) + 1
        st.session_state["_mic_ever_connected"] = False
        st.session_state["_mic_dead_since"] = None
        # 2026-08-28 — 세대별 임시 타이밍 키(_mic_connect_start_<gen>/_mic_connect_logged_<gen>,
        # _run_mic_loop() 참고)가 재연결마다 2개씩 session_state에 쌓이기만 하고 아무도 안
        # 지웠다("화면 전환마다 재연결"이라 한 세션에 수십 개). 세대가 바뀌는 지금 옛 세대
        # 키를 정리한다 — 현재/새 세대 키는 _run_mic_loop()가 필요할 때 다시 만든다.
        for _k in [k for k in st.session_state if k.startswith(("_mic_connect_start_", "_mic_connect_logged_"))]:
            del st.session_state[_k]
        # 2026-08-26 실측 리포트 — "된장찌개"라고 한 번만 말했는데 STT가 두 번(예: '단지게'
        # + '된장찌개') 잡히는 문제. _get_segmenter()의 MicVadSegmenter는 세션 전체에서
        # 하나만 재사용하는데(위 문서 — 화면 전환마다 새로 안 만드는 게 원래 목적), 마이크
        # 재연결(세대 교체)은 이 세그먼터를 안 건드리고 지나갔다. 그래서 연결이 끊기기
        # 직전까지 쌓여있던 "말하는 중" 상태(_in_speech/_speech_chunks_raw 등, silero-vad
        # VADIterator 자체의 내부 hidden state 포함)가 새 연결의 첫 프레임들과 그대로
        # 이어붙어서, 몇 초짜리 프레임 공백(재협상 시간) 뒤에 도착한 진짜 새 발화를 VAD가
        # "이미 말하던 중이던 게 계속됨" 또는 "중간에 끊긴 것처럼" 오판해 하나의 발화를
        # 둘로 쪼개는 것으로 보인다. 마이크가 완전히 새로 연결되는 시점이니 이전 연결의
        # VAD 상태도 같이 버리는 게 맞다 — reset()으로 처음부터 다시 시작하게 한다.
        _get_segmenter().reset()
        # 2026-08-25 요청 — 재연결 자체(WebRTC 재협상)는 몇 초~수십 초 걸리는 걸
        # 못 없애지만, "끊어져서 다시 연결 중"이라고 대놓고 알리는 경고 배너가
        # 오히려 더 느리고 눈에 띄게 느껴지게 만든다는 지적으로 조용히 지운다 —
        # 화면 자체의 "마이크 연결 중..." 표시(render_mic_bar 등)가 이미 그
        # 역할을 하고 있어서 중복이기도 하다.


def _mic_muted() -> bool:
    """speak()/_render_cached_speech()가 _arm_tts_mute()로 잡아둔 시각이 아직 안
    지났으면 True — AI가 말하는 동안엔 마이크가 자기 목소리를 다시 인식하지 않게
    한다(2026-08-23 요청, barge-in 없음)."""
    import time

    return time.monotonic() < st.session_state.get("_tts_mute_until", 0.0)


def _run_mic_loop(*, drain_only: bool = False) -> str | None:
    """webrtc_streamer()를 딱 1번만 부르고, 연결돼 있는 동안 블로킹 루프를 돌며 프레임을
    계속 뽑아 VAD에 먹인다 — 발화 하나가 완성되면 그 텍스트를 반환하고 끝난다(마이크
    연결 자체는 끊지 않음 — 다음 listen() 호출 때 이 함수가 다시 불려서 이어서 듣는다).

    drain_only=True (2026-08-28 추가) — webrtc_streamer() 렌더링(상시 연결 유지)과 프레임
    드레인만 하고 VAD 세그멘테이션·STT·텍스트 반환은 전부 건너뛴다. register_ingredients
    처럼 화면 자체가 텍스트 폼 전용이라 음성으로 처리할 게 없는 화면 전용
    (listen(listen_for_speech=False)). 이 화면들도 예전엔 일반 모드로 이 함수를 불러서
    마이크로 계속 듣고 STT까지 돌린 뒤 결과만 버렸는데(GPU 낭비 + "Queue overflow"),
    이 플래그로 그 낭비만 없앤다 — webrtc_streamer() 호출/재협상 동작은 일반 모드와
    100% 동일해서 마이크 재협상을 새로 유발하지 않는다(사용자 명시 요건).

    2026-08-23 리포트(실사용 + WEBRTC_DEBUG=1 로그로 원인 확정) — 처음엔 st.fragment
    (run_every=0.3)로 프레임만 폴링하고 웹RTC 연결 자체는 화면 흐름에서 정상 빈도로
    부르게 분리했었는데, 그래도 계속 iceConnectionState가 checking에서 곧장 closed로
    끊겼다. streamlit_webrtc.component 소스를 직접 읽어보고서야 이유를 확정: 그
    라이브러리는 "프론트엔드가 playing도 signalling도 아니다"라고 보고하면 기존 연결을
    바로 초기화(reset)한다(component.py `_reconcile_worker`의 "--- Stop ---" 분기). 그런데
    ICE가 "checking" 단계(offer 보내고 아직 연결 확정 전)일 때는 프론트엔드 값이 원래
    playing=False·signalling=False로 보고된다 — 즉 "checking" 도중에 스크립트가 단 한
    번이라도 다시 실행돼서 webrtc_streamer()가 또 불리면, 라이브러리가 자체적으로 그
    연결을 죽여버리는 구조다. `st.fragment`는 이론상 프래그먼트 스코프만 다시 실행한다고
    문서화돼 있지만 실측으로는 이 컴포넌트의 재초기화를 유발했다(정확한 내부 메커니즘은
    불명, streamlit-webrtc가 st.fragment 도입 이전 시대 라이브러리라 호환성 문제로 추정).

    그래서 이 저장소에 원래 있던 프로토타입(ui/streamlit_screens/stt_tts_test.py의
    `_render_always_on_mic()`)이 처음부터 왜 블로킹 while 루프를 썼는지 이제 이해된다 —
    연결이 끝날 때까지 스크립트가 아예 다시 실행되지 않아야 이 문제를 원천적으로 피할 수
    있어서다. 검증된 그 방식을 그대로 따른다: webrtc_streamer()를 1번 부르고, 그 이후는
    같은 스크립트 실행 안에서 while 루프로 프레임을 계속 뽑는다(다른 위젯/재실행 없이).

    STT는 백그라운드 스레드로 돌린다(2026-08-22 리포트) — 안 그러면 GPU 추론(1~2초+)
    도는 동안 get_frames() 호출이 멈춰서 STUN keepalive가 밀리고 연결이 끊긴다. 스레드가
    끝날 때까지도 계속 get_frames()로 프레임을 드레인하며 기다린다.
    """
    try:
        from streamlit_webrtc import WebRtcMode, webrtc_streamer
    except Exception:
        return None

    # 2026-08-25 추가 — "마이크 연결이 왜 이렇게 느리냐"는 지적에 실측 데이터로 답하기
    # 위한 임시 타이밍 로그(원인 확인되면 지울 것). 세대(_mic_gen)가 바뀔 때마다(=새
    # 컴포넌트가 처음부터 다시 연결을 시도할 때마다) 시작 시각을 한 번만 기록해두고,
    # 그 세대가 처음으로 playing=True에 도달하는 순간까지 걸린 시간을 정확히 잰다 —
    # 그동안은 로그에 타임스탬프가 없는 줄들뿐이라 "몇 초 걸렸다"를 추측만 하고 있었다.
    import time as _time

    _gen = st.session_state.get("_mic_gen", 0)
    _start_key = f"_mic_connect_start_{_gen}"
    st.session_state.setdefault(_start_key, _time.monotonic())

    # 화면 전환 중 끊긴 채 저절로 안 돌아오는 문제의 안전장치 — _recover_dead_mic() 문서 참고.
    _recover_dead_mic()

    # EC-04(마이크 권한 거부/오디오 입력 없음)와 같은 정신 — webrtc_streamer() 자체가
    # 실제 브라우저 세션이 아니면 예외를 던질 수 있다(실측 확인 — AppTest의 모킹된
    # 런타임에서 `Mock object has no attribute '_session_mgr'`). 조용히 포기하고
    # listen()의 텍스트 입력 폴백으로 넘어간다.
    try:
        webrtc_ctx = webrtc_streamer(
            key=_mic_component_key(),
            mode=WebRtcMode.SENDONLY,
            # 2026-08-24 — "Queue overflow. Consider to set receiver size bigger."
            # 경고 실측 확인. 256(약 5초, 20ms/프레임 기준)로는 부족했다 — speak()가
            # TTS 합성(3~9초+, docs/decisions.md #2)부터 재생까지 도는 동안은 이
            # _run_mic_loop()를 아예 안 돌고 있어서 get_frames()를 아무도 안 부르고,
            # 그동안 도착한 프레임이 전부 receiver 내부 큐에 쌓이기만 하다가 다음
            # listen() 호출 때야 다시 드레인된다. handle_utterance() DB 조회 + TTS
            # 합성 + 화면 재렌더 왕복을 넉넉히(약 20초) 버틸 수 있게 1024로 올린다.
            audio_receiver_size=1024,
            # 2026-08-23 — noiseSuppression/autoGainControl을 껐던 시도는 되돌림. 실측
            # 로그로 확인해보니 autoGainControl을 끄는 순간 캡처 레벨 자체가 확 낮아졌다
            # (rms 0.07대 -> 0.013대, 약 1/5) — 이 마이크/방 환경은 원래 입력 자체가 작아서
            # AGC가 그걸 보정해주고 있었던 것. AGC 없이는 오히려 더 안 들려서 인식이 더
            # 나빠짐(실측: "지게버지게 알려줘" 등 이전보다 더 심하게 깨짐). noiseSuppression
            # 단독으로 껐을 때 도움이 되는지는 아직 따로 검증 안 됐음 — 다음에 바꿀 땐 한
            # 번에 하나씩만 바꿔서 확인할 것.
            #
            # 2026-09-01 — "noiseSuppression만 단독으로" 실험하려면 실제 마이크로 들어보며
            # 판단해야 해서(코드만 보고 여기서 값을 정할 수 없음, 위 AGC 사례처럼 잘못
            # 짐작하면 오히려 인식이 나빠질 위험), 브라우저 기본값(True, 암묵적으로 on)에
            # 기대는 대신 명시적인 constraints로 바꾸고 env로 토글 가능하게 했다 — 재배포
            # 없이 RunPod Pod 환경변수만 바꿔서 켜고 끄며 실측 비교할 수 있다.
            # WEBRTC_NOISE_SUPPRESSION을 "false"로 주면 끔(AGC/에코제거는 절대 안 건드림 —
            # 위 AGC 사례 재현 방지). 기본값은 지금과 동일하게 켜짐(noiseSuppression=True).
            media_stream_constraints={
                "video": False,
                "audio": {
                    "noiseSuppression": os.environ.get("WEBRTC_NOISE_SUPPRESSION", "true").lower()
                    != "false",
                    "autoGainControl": True,  # 위 2026-08-23 실측 때문에 항상 True로 고정, 건드리지 말 것
                    "echoCancellation": True,
                },
            },
            # 2026-08-25 — iceTransportPolicy="relay" 강제를 시도했다가 되돌렸었다(그때
            # TURN이 Tailscale 전용 IP라 안 닿는 방문자에겐 후보가 하나도 안 남았음).
            # 2026-08-26 — Cloudflare Realtime TURN으로 바꾸면서 그 이유가 해소돼 다시
            # 켰다 — _ice_transport_policy() 문서 참고, Cloudflare TURN이 실제로 발급된
            # 경우에만 "relay"를 반환하고 그 외엔 None이라 아래서 키 자체를 뺀다.
            rtc_configuration=_rtc_configuration(),
            # 2026-08-23 추가 — "페이지 로드하면 바로 준비 상태여야 한다"는 요청. 이 값이
            # 없으면 streamlit-webrtc가 자기 기본 UI("SELECT DEVICE"/Start 버튼)를 그려서
            # 사용자가 매번 눌러야 연결이 시작된다. desired_playing_state=True를 주면
            # 컴포넌트가 마운트되자마자 알아서 연결을 시도한다(streamlit_webrtc 프론트엔드
            # 소스 실측 확인 — desiredPlayingState가 True이고 webRtcState가 STOPPED일 때
            # 곧장 start()를 호출) — 브라우저가 이 사이트에 마이크 권한을 이미 내준 적
            # 있으면 클릭 없이 바로 연결되고, 처음이면 그 권한 팝업만 뜬다(그건 브라우저
            # 보안 정책상 피할 수 없음, EC-04와도 무관 — 팝업에서 거부해도 텍스트 입력
            # 폴백은 그대로 동작).
            desired_playing_state=True,
        )
    except Exception:
        return None

    if not webrtc_ctx.state.playing or webrtc_ctx.audio_receiver is None:
        # 2026-08-23 추가 — 바로 위 _recover_dead_mic()이 세대를 이미 새로 바꿨다면
        # (그 경우 _mic_ever_connected는 방금 False로 리셋됨) 이 새 컴포넌트는 그냥
        # 정상적으로 처음 연결 중인 것뿐이라 아무것도 안 하고 조용히 기다린다. 그게
        # 아니라(_mic_ever_connected가 아직 True인데도 여기 온) 세대를 안 바꿨는데도
        # 여기 왔다면 _recover_dead_mic()의 판정 자체가 아직 못 따라잡은 찰나의 레이스
        # — 다음 실행에서라도 확실히 다시 판정받을 수 있게 강제로 재실행시킨다.
        if st.session_state.get("_mic_ever_connected"):
            _rate_limited_rerun()
        return None  # 아직 연결 안 됐거나(Start 버튼 전) 꺼짐 — 블로킹 없이 바로 반환

    # _recover_dead_mic()가 "이 세대가 한 번은 연결에 성공했었는지"를 다음 호출에서
    # 바로 알 수 있게, 성공 확인 즉시 표시해둔다(다음 호출까지 기다릴 필요 없음).
    st.session_state["_mic_ever_connected"] = True

    # 위 타이밍 로그 마무리 — 이 세대가 처음으로 여기 도달한 순간(=진짜 playing=True를
    # 확인한 순간)까지 걸린 시간을 한 번만 찍는다(_mic_connect_logged_* 플래그로 이후
    # 호출에선 중복 출력 안 함).
    _logged_key = f"_mic_connect_logged_{_gen}"
    if not st.session_state.get(_logged_key):
        st.session_state[_logged_key] = True
        _elapsed = _time.monotonic() - st.session_state.get(_start_key, _time.monotonic())
        print(f"[MIC_TIMING] gen={_gen} 연결 성공까지 {_elapsed:.2f}초", flush=True)

    import queue

    segmenter = _get_segmenter()

    # 2026-08-24 — audio_receiver_size를 256->1024로 올려도 "Queue overflow" 경고가
    # 반복되는 게 실측 확인됨. 근본 원인은 버퍼 크기가 아니라 드레인 공백 자체다 —
    # speak()가 도는 동안(handle_utterance() DB 조회 + TTS 합성 3~9초+, docs/decisions.md
    # #2 + 화면 재렌더) 이 함수가 아예 안 불려서 get_frames()가 전혀 호출되지 않는데,
    # 그동안도 브라우저는 계속 프레임을 보내고 있어 큐에 쌓인다. 버퍼를 아무리 키워도
    # "재개했을 때 밀린 걸 프레임 단위로 하나씩 처리하며 따라잡으려는" 방식 자체가
    # 실시간 도착 속도를 못 이기면 다시 꽉 차서 반복된다. 게다가 이 프로젝트는 barge-in을
    # 지원하지 않기로 했으므로(_mic_muted() 문서 참고) AI가 말하는 동안 들어온 오디오는
    # 어차피 처리 대상이 아니다 — 그래서 밀린 걸 따라잡으려 하지 않고, 재개하자마자
    # 큐에 쌓여있던 프레임을 전부 논블로킹으로 비워서(버려서) 항상 "지금부터"만
    # 실시간으로 처리한다. 이러면 큐가 다시 꽉 찰 일이 없다.
    try:
        while True:
            webrtc_ctx.audio_receiver.get_frames(timeout=0)
    except queue.Empty:
        pass
    except AttributeError:
        pass

    # 2026-08-23 리포트(헤드리스 브라우저 자동 테스트로 재현) — 루프를 도는 도중 연결이
    # 끊기면(탭 닫힘, 네트워크 끊김, 마이크 장치 분리 등) webrtc_ctx.audio_receiver
    # 자체가 None으로 바뀔 수 있다(state.playing 체크만으론 못 잡는 경우가 실측 확인됨 —
    # AttributeError: 'NoneType' object has no attribute 'get_frames'). EC-04와 같은
    # 정신으로, 화면이 죽는 대신 조용히 루프를 빠져나가 listen()의 텍스트 입력
    # 폴백으로 넘어가게 한다.
    while webrtc_ctx.state.playing and webrtc_ctx.audio_receiver is not None:
        try:
            frames = webrtc_ctx.audio_receiver.get_frames(timeout=1)
        except queue.Empty:
            continue
        except AttributeError:
            break  # 위 주석과 같은 레이스 — get_frames() 호출 순간 None이 된 경우

        if drain_only:
            # 2026-08-28 요청 — register_ingredients처럼 화면이 텍스트 폼 전용이라
            # 음성으로 처리할 게 없는 화면. webrtc_streamer()는 위에서 이미 렌더링해
            # 상시 마이크 연결은 그대로 살아있고(마이크 재협상을 절대 유발하지 않는다는
            # 사용자 요건), 여기서는 VAD/STT를 아예 안 돌리고 방금 꺼낸 프레임을 그냥
            # 버려서 receiver 내부 큐만 계속 비운다("Queue overflow" 경고 방지). 사용자가
            # 이 화면에서 뭔가 조작하면(입력/버튼) 그 rerun이 이 실행을 대체하며 빠져나온다.
            continue

        if _mic_muted():
            continue  # 프레임은 이미 꺼냈으니 밀리지 않음 — VAD엔 안 먹이고 버림

        for frame in frames:
            _arr = frame.to_ndarray()
            # 2026-08-23 임시 진단 — "내 목소리가 아님" 리포트 원인 파악용. mic_vad.py에
            # 닿기 전, av.AudioFrame이 실제로 뭘 주는지(샘플레이트/모양/dtype/샘플수)를
            # 처음 몇 프레임만 찍어서 frame.sample_rate와 배열 크기가 서로 맞는지 확인한다.
            # 원인 확인되면 지울 것.
            global _FRAME_DEBUG_COUNT
            if _FRAME_DEBUG_COUNT < 8:
                _FRAME_DEBUG_COUNT += 1
                print(
                    f"[FRAME_DEBUG] sample_rate={frame.sample_rate} shape={_arr.shape} "
                    f"dtype={_arr.dtype} frame.samples={getattr(frame, 'samples', None)} "
                    f"layout={getattr(frame.layout, 'name', None)} format={getattr(frame.format, 'name', None)}",
                    flush=True,
                )
            # 2026-08-23 — "내 목소리가 아님"(음이 낮고 늘어져 들림) 리포트 원인 확정 —
            # FRAME_DEBUG로 실측: layout=stereo인데 frame.to_ndarray()가 (채널,샘플)이
            # 아니라 (1, 샘플수*채널수)짜리 인터리브 한 줄로 옴. mic_vad.py가 배열 모양만
            # 보고 채널을 못 갈라내서 L/R이 순서대로 이어진 모노처럼 처리돼 실제 시간의
            # 2배짜리 가짜 파형이 만들어졌던 것 — 실제 채널 수를 frame.layout에서 알아내
            # 넘겨줘서 mic_vad.py가 제대로 나눠 평균내게 한다.
            _channels = len(frame.layout.channels) if frame.layout is not None else 1
            utterance_audio = segmenter.feed(_arr, frame.sample_rate, channels=_channels)
            if utterance_audio is None:
                continue

            job: dict = {"done": False, "text": ""}
            # 2026-09-02 — 세션 짧은 식별자를 스레드 시작 전(여기는 아직 메인 스레드,
            # _run_mic_loop() 자체가 main() 호출 흐름 안에서 블로킹 도는 함수라서
            # st.session_state 접근이 안전함) 미리 읽어 넘긴다 — _synthesize_and_cache()
            # 문서와 같은 이유.
            _sid = st.session_state.get("_sid")

            def _run_stt(audio=utterance_audio, job=job, sid=_sid) -> None:
                # 백그라운드 스레드 — voice_io._synthesize_and_cache()와 같은 이유로
                # st.* API를 전혀 안 쓴다.
                import time

                try:
                    # 2026-08-23 진단(마이크 인식 문제) — 오디오 크기/레벨 + STT 결과.
                    # 2026-08-28: 매 발화마다 stdout에 찍히고 stt_text는 사용자 발화 전문이라
                    # CHEFEAR_DEBUG가 설정된 경우에만 남긴다.
                    _mic_dbg = bool(os.environ.get("CHEFEAR_DEBUG"))
                    if _mic_dbg:
                        print(
                            f"[MIC_DEBUG] samples={len(audio)} dur={len(audio) / 16000:.2f}s "
                            f"max_amp={float(__import__('numpy').abs(audio).max()):.4f} "
                            f"rms={float(__import__('numpy').sqrt((audio ** 2).mean())):.4f}",
                            flush=True,
                        )
                    # 2026-08-23 추가, 2026-08-25 제거 — 매 발화마다 STT 입력 오디오를
                    # ui/assets/_mic_debug_dumps/에 파일로 남기던 임시 진단 코드였다("녹음된
                    # 게 내 목소리가 아니다" 리포트 원인 파악용). 그 원인은 바로 위 채널
                    # 인터리브 처리 수정으로 이미 확정/해결됐고(2026-08-23), 이후로도 계속
                    # 남아있어서 하룻밤 새 550개/82MB까지 쌓인 게 실측 확인됨(2026-08-25) —
                    # 목적을 다했으니 코드와 쌓인 파일 둘 다 정리한다.
                    # 2026-08-26 재요청 — vad_filter=True로 되돌림. 원래 False로 바꾼 이유는
                    # 위 stt_transcribe() 문서 참고("이중 VAD로 조용한 실제 발화가 stt_text=''로
                    # 사라짐") — 이 되돌림은 그 문제를 다시 불러올 수 있다는 걸 알고 하는
                    # 요청이라 그대로 반영한다.
                    # 2026-09-01 — 승욱님 실측 리포트("전체 왕복이 어마무시하게 느리다")
                    # 진단용 타이밍 로그. 각 단계(STT/LLM/handle_utterance/TTS)가 얼마나
                    # 걸리는지 실측 없이는 어디가 병목인지 추측만 하게 되므로, 이 넷을
                    # 전부 같은 [PERF] 태그로 남겨서 나중에 grep 한 번으로 비교할 수
                    # 있게 한다. 상시로 켜둔다(CHEFEAR_DEBUG 게이트 없음) — 한 줄짜리라
                    # 로그 스팸 우려가 적고, 지금 당장 진단이 필요한 값이라서다.
                    _stt_t0 = time.monotonic()
                    job["text"] = (
                        gpu_worker_pool.submit_stt(
                            audio, sample_rate=16000, vad_filter=True, session_id=sid
                        )
                        .result()
                        .strip()
                    )
                    print(f"[PERF] STT {time.monotonic() - _stt_t0:.2f}s", flush=True)
                    if _mic_dbg:
                        print(f"[MIC_DEBUG] stt_text={job['text']!r}", flush=True)
                except Exception as exc:  # noqa: BLE001 — 실패해도 조용히 넘어감
                    print(f"[MIC_DEBUG] stt exception: {exc!r}", flush=True)
                    job["text"] = ""
                finally:
                    job["done"] = True

            threading.Thread(target=_run_stt, daemon=True).start()

            # STT가 끝날 때까지도 계속 프레임을 드레인한다(연결 keepalive 유지) —
            # 마이크가 꺼지면 기다림을 포기하고 바깥 while 조건에서 자연스럽게 빠진다.
            while not job["done"] and webrtc_ctx.state.playing and webrtc_ctx.audio_receiver is not None:
                try:
                    webrtc_ctx.audio_receiver.get_frames(timeout=0.5)
                except queue.Empty:
                    pass
                except AttributeError:
                    break

            # 연결이 끊긴 채로 STT만 끝나길 기다리는 걸 막기 위한 안전판 — job이 아직
            # 안 끝났어도(연결 끊김으로 above while을 빠져나온 경우) 이미 시작된
            # 백그라운드 스레드 자체는 계속 돌게 두고(daemon=True라 프로세스 종료는
            # 안 막음), 여기서는 그냥 다음 발화를 기다리지 않고 함수를 빠져나간다.

            if job["text"]:
                return job["text"]
            # 빈 문자열(인식 실패)이면 계속 듣는다 — 바깥 while로 돌아감

    # 2026-08-23 추가 — 바로 위 while을 "발화를 다 들어서"가 아니라 "연결이 끊겨서"
    # 빠져나온 경우(이 지점에 도달했다는 건 위 조건 검사에서 이미 playing=True였다가
    # 여기 오는 사이 끊겼다는 뜻 — 함수 진입 시 안 연결된 경우는 그 전에 이미 return됨).
    # 실측 확인(WEBRTC_DEBUG 로그) — 연결이 끊겨도 프론트엔드 쪽 컴포넌트 값 변경 알림이
    # 항상 새 스크립트 실행을 트리거해주는 게 아니라서, 아무 반응 없이 그대로 멈춰있는
    # 경우가 있었다("응"/"다음" 등을 말해도 반응 없음 리포트). 여기서 직접 st.rerun()을
    # 불러서 다음 실행을 강제로 시작시키면, 그 실행의 _recover_dead_mic()이 죽은 연결을
    # 감지해서 새 컴포넌트로 재연결을 시도한다.
    if st.session_state.get("_mic_ever_connected"):
        _rate_limited_rerun()

    return None


def listen(
    key_prefix: str,
    *,
    show_mic: bool = True,
    mic_enabled: bool = True,
    listen_for_speech: bool = True,
    show_text_fallback: bool = True,
) -> str | None:
    """상시 마이크(실시간 스트리밍 인식) 또는 텍스트 입력으로 발화 하나를 받는다.

    반환값이 None이면 아직 입력이 없거나(정상) 무음/인식 실패(EC-01)라는 뜻 — 호출부는
    아무 것도 안 하고 다음 rerun을 기다리면 된다. 마이크 권한이 없거나 연결이 안 되도
    텍스트 입력으로 그대로 진행할 수 있다(EC-04).

    show_mic 파라미터는 2026-08-23부터 더 이상 동작에 영향을 주지 않는다(과거엔 화면마다
    중복되는 녹음 위젯을 숨기는 용도였는데, 지금은 모든 화면이 상시 마이크 연결 하나를
    공유해야 해서 항상 렌더링해야 한다) — 호출부(screens/*.py) 코드를 안 건드리려고
    시그니처만 남겨뒀다.

    mic_enabled=False (2026-08-23 추가) — _run_mic_loop()을 아예 안 부른다, 즉 이 화면이
    그려지는 동안은 webrtc_streamer() 컴포넌트 자체가 렌더링되지 않는다. "초기 화면(start)에
    있는 동안엔 상시 마이크를 꺼두고, 그 다음부터는(사용자가 뭔가 말하거나 입력해서 다음
    화면으로 넘어가면) 계속 연결돼 있게 해달라"는 요청(2026-08-23)으로 추가 — 이 컴포넌트가
    화면에 안 그려지면(다른 위젯/재실행 없이 조건 없이 매번 그려야 하는 이유는 위
    _run_mic_loop() 주석 참고) 연결이 자연히 끊긴다. start만 이걸로 마이크를 끄고, 그 외
    모든 화면은 기본값(True)으로 계속 같은 연결을 공유한다.

    listen_for_speech=False (2026-08-28 추가) — mic_enabled=False와 달리 webrtc_streamer()는
    그대로 렌더링해서 상시 마이크 연결을 유지하되(마이크 재협상 금지 요건), _run_mic_loop()
    안의 VAD 세그멘테이션·STT만 건너뛴다(_run_mic_loop(drain_only=True), 프레임은 계속
    드레인해서 "Queue overflow" 방지). register_ingredients처럼 화면이 텍스트 폼 전용이라
    음성 입력이 필요 없는데, 예전엔 일반 listen()을 불러 마이크로 계속 듣고 STT까지 돌린 뒤
    반환값만 버리고 있었다(불필요한 GPU 사용). 마이크 반환값은 항상 None이라 show_text_fallback
    처리만 이어진다.

    show_text_fallback=False (2026-08-23 추가) — register_ingredients/register_steps처럼
    화면 자신이 이미 목적이 뚜렷한 텍스트 입력칸("재료 추가"/"순서 추가")을 갖고 있는
    화면에서, listen()이 덧붙이는 범용 "또는 텍스트로 입력" 칸까지 같이 뜨면 입력창이
    세 개(화면 자체 폼 + listen()의 텍스트 대체 + 마이크)로 겹쳐 보인다. 마이크 연결은
    (연결 유지 목적으로) 계속 살려두되, 이 중복 텍스트 칸만 끈다 — 그 화면들은 mic_text가
    있을 때 "취소"/"처음" 같은 소수의 안전한 단어만 직접 확인하고 그 외엔 무시한다(자유
    발화를 재료/순서 항목으로 잘못 등록하면 안 되므로, register_ingredients/steps는 여전히
    구조화된 텍스트 폼이 주 입력 수단이다).
    """
    turn = st.session_state.input_turn

    mic_text = _run_mic_loop(drain_only=not listen_for_speech) if mic_enabled else None
    if mic_text:
        st.session_state.input_turn += 1  # 다음 rerun에서 새 텍스트 위젯 키를 쓰게 함
        return mic_text

    if not show_text_fallback:
        return None

    typed = st.text_input(
        "또는 텍스트로 입력",
        key=f"{key_prefix}_typed_{turn}",
        placeholder="마이크 대신 직접 타이핑해도 돼요",
    )
    if typed and typed.strip():
        st.session_state.input_turn += 1
        return typed.strip()

    return None
