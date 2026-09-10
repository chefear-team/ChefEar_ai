"""ChefEar 관리자 페이지 2FA — 2차(화자검증 + 랜덤 단어 챌린지)."""
from __future__ import annotations

import io
import re
import secrets
import threading
import time

import streamlit as st

# 2~3음절 흔한 명사. 서로 발음이 겹치지 않게 고름(동음이의/유사발음 배제). 매 시도
# 3개를 뽑으므로 조합은 40*39*38 ≈ 5.9만 — 재생 공격(과거 녹음)엔 그 조합의 녹음이
# 있어야 하므로 충분하다. 풀을 늘리면 조합도 늘어난다.
_WORD_POOL: tuple[str, ...] = (
    "사자", "여우", "토끼", "다람쥐", "거북이", "고양이", "강아지", "원숭이",
    "바다", "하늘", "구름", "바람", "나무", "바위", "계곡", "무지개",
    "책상", "의자", "연필", "지우개", "가방", "우산", "시계", "안경",
    "사과", "딸기", "포도", "수박", "참외", "당근", "오이", "감자",
    "학교", "병원", "시장", "공원", "기차", "자전거", "도서관", "놀이터",
)
_N_WORDS = 3
_NEED_MATCH = 2          # 3개 중 2개 이상 맞으면 통과(STT 1개 실수 허용)
_MAX_ATTEMPTS = 5
_COOLDOWN_S = 60

_rate_lock = threading.Lock()
_rate: dict = {}  # ip -> {"fails": [monotonic timestamps], "locked_until": float}


def _client_ip() -> str:
    """Cloudflare Tunnel 뒤라 실제 방문자 IP는 CF-Connecting-IP 헤더에 있다. 없으면
    X-Forwarded-For(첫 항목) / X-Real-IP. 헤더 자체를 못 읽는 로컬 개발 등에선 '_local'."""
    try:
        h = st.context.headers
        ip = (
            h.get("cf-connecting-ip")
            or (h.get("x-forwarded-for") or "").split(",")[0].strip()
            or h.get("x-real-ip")
        )
        return ip or "_local"
    except Exception:  # noqa: BLE001
        return "_local"


def _prune_rate(now: float) -> None:
    """만료된 IP 항목 삭제(락 안에서 호출). 최근 60초 밖의 실패 타임스탬프는 버리고,
    잠금도 안 걸려 있고 최근 실패도 없으면 항목 자체를 없앤다."""
    for ip in list(_rate):
        e = _rate[ip]
        e["fails"] = [t for t in e["fails"] if now - t < _COOLDOWN_S]
        if e.get("locked_until", 0.0) <= now and not e["fails"]:
            del _rate[ip]


def _cooldown_remaining(ip: str, now: float) -> float:
    with _rate_lock:
        _prune_rate(now)
        e = _rate.get(ip)
        if e and now < e.get("locked_until", 0.0):
            return e["locked_until"] - now
        return 0.0


def _record_failure(ip: str, now: float) -> None:
    with _rate_lock:
        e = _rate.setdefault(ip, {"fails": [], "locked_until": 0.0})
        e["fails"] = [t for t in e["fails"] if now - t < _COOLDOWN_S]
        e["fails"].append(now)
        if len(e["fails"]) >= _MAX_ATTEMPTS:
            e["locked_until"] = now + _COOLDOWN_S
            e["fails"] = []


def _forget_ip(ip: str) -> None:
    with _rate_lock:
        _rate.pop(ip, None)


def _new_challenge() -> list[str]:
    return list(secrets.SystemRandom().sample(_WORD_POOL, _N_WORDS))


def _normalize(text: str) -> str:
    """공백·문장부호·조사 제거해 한글/영숫자만 남긴다."""
    return re.sub(r"[^\w가-힣]+", "", text or "").replace("_", "")


def _transcript_matches(transcript: str, challenge: list[str]) -> tuple[bool, int]:
    norm = _normalize(transcript)
    hits = sum(1 for w in challenge if _normalize(w) in norm)
    return hits >= _NEED_MATCH, hits


def _decode_audio(uploaded) -> "tuple":
    import numpy as np
    import soundfile as sf

    wav, sr = sf.read(io.BytesIO(uploaded.getvalue()), dtype="float32", always_2d=False)
    if getattr(wav, "ndim", 1) > 1:
        wav = wav.mean(axis=1)
    return np.ascontiguousarray(wav, dtype=np.float32), int(sr)


def _warm_models_once() -> None:
    """챌린지 화면이 처음 뜰 때 STT(faster-whisper)·화자모델을 백그라운드로 미리 로드한다.
    관리자 페이지는 _start_model_warmup()을 안 타서, 이게 없으면 첫 검증에서 두 모델
    콜드 로드(각 수십 초)를 그 자리에서 물고 기다려야 한다. 사용자가 챌린지를 읽고
    녹음하는 ~10초 동안 로드가 끝나 있게 한다."""
    if st.session_state.get("_admin_warm_started"):
        return
    st.session_state["_admin_warm_started"] = True

    def _run() -> None:
        for label, loader in (("STT", _load_stt), ("speaker", _load_speaker)):
            try:
                loader()
            except Exception as exc:  # noqa: BLE001
                print(f"[admin_auth] {label} 워밍업 실패(검증 시점 재시도): {exc!r}", flush=True)

    threading.Thread(target=_run, daemon=True).start()


def _load_stt():
    from stt.infer import load_ct2_model

    return load_ct2_model()


def _load_speaker():
    from orchestration.speaker_verify import load_speaker_model

    return load_speaker_model()


def render_voice_challenge() -> None:
    ss = st.session_state
    _warm_models_once()
    st.markdown("## 🔒 관리자 음성 인증")

    now = time.monotonic()
    ip = _client_ip()
    remaining = _cooldown_remaining(ip, now)
    if remaining > 0:
        st.warning(f"시도가 많아 잠시 잠겼어요. 약 {int(remaining) + 1}초 후 다시 시도해 주세요.")
        st.button("새로고침")  # 누르면 rerun → 남은 시간 갱신
        return

    if "_admin_challenge" not in ss:
        ss["_admin_challenge"] = _new_challenge()
    challenge: list[str] = ss["_admin_challenge"]

    st.write("아래 **세 단어**를 또박또박 읽고 녹음해 주세요.")
    st.markdown(
        f"<div style='font-size:30px;font-weight:800;letter-spacing:2px;text-align:center;"
        f"padding:18px 0;'>{'  ·  '.join(challenge)}</div>",
        unsafe_allow_html=True,
    )

    turn = ss.get("_admin_voice_turn", 0)
    uploaded = st.audio_input("녹음", key=f"admin_voice_{turn}", label_visibility="collapsed")
    if uploaded is None:
        return

    transcript, word_ok, hits, speaker_ok, name, score = "", False, 0, False, None, 0.0
    try:
        wav, sr = _decode_audio(uploaded)
        from orchestration import gpu_worker_pool, speaker_verify

        transcript = gpu_worker_pool.submit_stt(wav, sample_rate=sr).result()
        word_ok, hits = _transcript_matches(transcript, challenge)
        speaker_ok, name, score = speaker_verify.verify(wav, sample_rate=sr)
    except Exception as exc:  # noqa: BLE001 — 인증 인프라 실패는 fail-closed(spec EC-11)
        print(f"[admin_auth] 검증 중 오류(fail-closed): {exc!r}", flush=True)

    passed = word_ok and speaker_ok

    if passed:
        ss["_admin_verified"] = name
        ss.pop("_admin_challenge", None)
        _forget_ip(ip)  # 성공 시 이 IP는 즉시 잊는다
        print(f"[admin] {name} 음성 인증 통과 (유사도 {score:.3f})", flush=True)
        st.rerun()

    # 실패 — 사유는 화면에 노출하지 않고(공격자 힌트 금지) 콘솔에만 남긴다. IP는
    # 로그에 안 남긴다(개인정보 최소 보유 — _rate 메모리 dict에만, 최대 60초).
    _record_failure(ip, now)
    print(
        f"[admin_auth] 인증 실패 "
        f"transcript={transcript!r} word_hits={hits}/{_N_WORDS} "
        f"speaker_ok={speaker_ok} score={score:.3f} name={name}",
        flush=True,
    )
    ss["_admin_challenge"] = _new_challenge()
    ss["_admin_voice_turn"] = turn + 1  # audio_input 위젯 리셋
    st.error("인증에 실패했어요. 새 단어로 다시 시도해 주세요.")
    st.rerun()
