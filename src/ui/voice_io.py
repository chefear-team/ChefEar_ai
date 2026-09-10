"""ChefEar 음성 입출력 — 상시 마이크(WebRTC+VAD) 연결과 STT/TTS 호출(`listen`/`speak`), TTS 캐시·프리페치."""
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

load_env()

if os.environ.get("WEBRTC_DEBUG"):
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("aioice").setLevel(logging.DEBUG)
    logging.getLogger("aiortc").setLevel(logging.DEBUG)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _SuppressBenignTurnTaskDestroyedWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Task was destroyed but it is pending" not in record.getMessage()


logging.getLogger("asyncio").addFilter(_SuppressBenignTurnTaskDestroyedWarning())


_CF_TURN_CACHE: dict = {}


def _cloudflare_turn_ice_servers() -> list[dict] | None:
    """Cloudflare Realtime TURN에서 짧게 유효한 iceServers를 발급받는다."""
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
    """WebRTC(상시 마이크)의 ICE 서버 목록."""
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
    """ 두 번 되돌림 — 이 데스크탑의 여러 가상 네트워크
    인터페이스(WSL 브릿지, Docker, link-local 등)가 전부 ICE host candidate로 잡혀서
    STUN 연결성 검사가 수천 건까지 폭증하는 게 실측 확인됐다(WEBRTC_DEBUG 로그로 확인 —
    발화 하나 없이 순수 협상만으로 3500개 넘는 STUN BINDING REQUEST). 이 정도 동시
    요청량에서 aioice/aiortc의 알려진(2022년부터 미해결, streamlit-webrtc#845/aiortc#85)
    asyncio 이벤트루프 정리 버그가 거의 매번 재현돼서 연결이 느려지거나 최악엔 영영
    """
    return None


def _rtc_configuration() -> dict:
    """webrtc_streamer에 넘길 RTCConfiguration을 조립한다 — _ice_servers
    와 _ice_transport_policy 둘을 한 곳에서 합쳐서, 정책이 None일 때 그 키 자체를 아예
    안 넣게 한다(WebRTC 표준상 iceTransportPolicy의 기본값이 "all"이라, 명시적으로 None을
    넣는 것보다 키 자체를 생략하는 쪽이 더 안전 — 브라우저/streamlit-webrtc가 None을
    "all"로 정확히 해석해준다는 보장이 없어서다).
    """
    config: dict = {"iceServers": _ice_servers()}
    policy = _ice_transport_policy()
    if policy:
        config["iceTransportPolicy"] = policy
    return config

_AUDIO_DIR = PROJECT_ROOT / "ui" / "assets" / "audio"


def _common_audio_path(message: str) -> Path:
    """조리 단계처럼 recipe_id/step_number가 없는 1회성 문구(확인 질문·안내 등)의
    캐시 경로 — 문구 자체의 해시를 키로 쓴다. speak()와 _render_cached_speech()가
    같은 문구에 대해 항상 같은 경로를 계산해야 캐시가 서로 맞물린다."""
    import hashlib

    digest = hashlib.sha1(message.encode("utf-8")).hexdigest()[:16]
    return _AUDIO_DIR / "_common" / f"{digest}.wav"


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
    """sf.write(audio_path, ...)를 직접 부르는 대신 이 함수를 쓴다."""
    tmp_path = audio_path.with_name(f".{audio_path.name}.tmp{os.getpid()}-{threading.get_ident()}")
    try:
        sf.write(tmp_path, waveform, sample_rate, format="WAV")
        os.replace(tmp_path, audio_path)  # 같은 디렉터리 안이므로 원자적 교체
    except BaseException:
        tmp_path.unlink(missing_ok=True)  # 실패 시 임시 파일 흔적을 안 남긴다
        raise


def _arm_tts_mute(audio_path: Path) -> None:
    """이 오디오가 재생되는 동안 상시 마이크가 자기 목소리를 다시 주워듣지 않게,
    "지금부터 대략 이 길이만큼은 마이크 입력을 무시하라"는 시각을 세션에 남긴다
    """
    import time

    try:
        duration = sf.info(audio_path).duration
    except Exception:
        duration = 3.0  # 길이를 못 읽으면 최소한의 안전 여유만 둔다
    mute_until = time.monotonic() + duration + 0.6
    st.session_state["_tts_mute_until"] = max(st.session_state.get("_tts_mute_until", 0.0), mute_until)


def _render_cached_speech(message: str, *, nonce: int | str = 0) -> None:
    """speak()로 이미 이 문구를 말한 적 있다면(캐시 존재) 음성만 자동재생한다(재생바는 없음)."""
    path = _common_audio_path(message)
    if path.exists():
        _arm_tts_mute(path)
        render_audio_autoplay(path, nonce=nonce)


_LOADING_OVERLAY_SHOW_DELAY_S = 0.4
_LOADING_OVERLAY_MIN_VISIBLE_S = 0.3


class _LoadingOverlay:
    """_drain_mic_while() 호출 여러 번에 걸쳐 로딩 팝업 하나를 이어 쓰기 위한 핸들."""

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
    """
    import time

    if overlay.shown:
        remaining = _LOADING_OVERLAY_MIN_VISIBLE_S - (time.monotonic() - overlay.shown_at)
        if remaining > 0:
            time.sleep(remaining)
        overlay.slot.empty()
        overlay.shown = False
        time.sleep(0.05)


def _drain_mic_while(
    job: dict,
    *,
    loading_message: str | None = "말씀 잘 들었어요, 잠시만요...",
    overlay: "_LoadingOverlay | None" = None,
    close: bool = True,
) -> "_LoadingOverlay":
    """job["done"]가 True가 될 때까지 상시 마이크(webrtc)의 오디오 큐를 계속 비워준다."""
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
            job: dict = {"done": False, "error": None}
            _sid = st.session_state.get("_sid")

            def _run_synthesis(job=job, sid=_sid) -> None:
                import time

                try:
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
            _drain_mic_while(job, overlay=_loading_overlay, close=True)
            if job["error"] is not None:
                raise job["error"]
        elif _loading_overlay is not None:
            _close_loading_overlay(_loading_overlay)

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
    """
    if audio_path.exists():
        return
    with _get_synthesis_lock(audio_path):
        try:
            if audio_path.exists():  # 락을 기다리는 동안 다른 쪽이 이미 만들었을 수 있음
                return
            waveform, sample_rate = gpu_worker_pool.submit_tts(text, session_id=session_id).result()
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            _write_wav_atomic(audio_path, waveform, sample_rate)
        except Exception:  # noqa: BLE001 — 프리페치 실패는 speak()가 다시 시도하므로 조용히 넘어감
            pass


_PREFETCH_CONCURRENCY = 2


def prefetch_remaining_steps_audio(view: dict, step_number: int) -> None:
    """지금 보고 있는 조리 단계 화면에서, 다음 단계부터 마지막 단계까지 전부 백그라운드에서
    최대 _PREFETCH_CONCURRENCY개씩 동시에 미리 합성해 캐싱해둔다.
    TTS 합성 자체는 GPU에서도 문장 길이에 따라 3~9초 걸리는 게 실측됐고(docs/decisions.md
    #2), 더 줄이려던 torch.compile 시도는 재컴파일 스톨 위험으로 보류했다 —
    그래서 합성 속도 자체 대신, 사용자가 화면을 보고 있는 시간 동안 쉬지 않고 뒷단계들을
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
    _sid = st.session_state.get("_sid")

    def _synth_step(step: dict, sid: str | None) -> None:
        if active_recipe_box.get("recipe_id") != recipe_id:
            return  # 사용자가 이 레시피를 떠났음 — 이 단계는 만들지 않고 조용히 건너뜀
        step_num = step.get("step_number")
        audio_path = _AUDIO_DIR / str(recipe_id) / f"{step_num:02d}.wav"
        _synthesize_and_cache(resolve_for_tts(step["text"]), audio_path, session_id=sid)

    def _run(sid=_sid) -> None:
        from concurrent.futures import ThreadPoolExecutor

        # max_workers=_PREFETCH_CONCURRENCY(2)로 캡핑 — GPU_WORKER_COUNT(3)보다 작게
        # 잡아서 실시간 요청용 워커가 항상 최소 1개는 남게 한다(위 _PREFETCH_CONCURRENCY
        # 문서 참고). 각 _synth_step() 호출은 gpu_worker_pool.submit_tts().result()로
        # 블로킹되므로, 이 풀의 스레드 수 자체가 "동시에 실제로 GPU에 요청 중인 프리페치
        # 개수"의 상한이 된다.
        with ThreadPoolExecutor(max_workers=_PREFETCH_CONCURRENCY) as pool:
            list(pool.map(lambda step: _synth_step(step, sid), remaining))

    threading.Thread(target=_run, daemon=True).start()


_MIC_KEY = "chefear_mic"

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
    """context.state.playing만 믿지 않고, 실제 워커(오디오 수신기)가 살아있는지까지"""
    state = getattr(context, "state", None)
    playing = bool(getattr(state, "playing", False))
    has_worker = getattr(context, "audio_receiver", None) is not None
    return playing and has_worker


def _rate_limited_rerun(min_interval_s: float = 1.0) -> None:
    """st.rerun()을 바로 부르지 않고, 마지막으로 부른 지 min_interval_s 이상 지났을"""
    import time

    now = time.monotonic()
    last = st.session_state.get("_mic_last_forced_rerun", 0.0)
    if now - last >= min_interval_s:
        st.session_state["_mic_last_forced_rerun"] = now
        st.rerun()


def mic_is_playing() -> bool:
    """상시 마이크(webrtc_streamer())가 지금 실제로 연결돼 있는지 — start 화면의"""
    return _mic_truly_alive(st.session_state.get(_mic_component_key()))


_MIC_DEAD_DEBOUNCE_S = 2.0


def _recover_dead_mic() -> None:
    """한 번은 정상 연결됐던 마이크가 완전히 끊긴 채(_mic_truly_alive()가 False —
    "checking" 중이 아니라 진짜 종료됐거나 워커가 사라진 상태) 저절로 안 돌아오면,
    컴포넌트 key 자체를 새로 바꿔서 다음 webrtc_streamer() 호출이 완전히 새 컴포넌트로
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
        for _k in [k for k in st.session_state if k.startswith(("_mic_connect_start_", "_mic_connect_logged_"))]:
            del st.session_state[_k]
        _get_segmenter().reset()


def _mic_muted() -> bool:
    """speak()/_render_cached_speech()가 _arm_tts_mute()로 잡아둔 시각이 아직 안
    지났으면 True — AI가 말하는 동안엔 마이크가 자기 목소리를 다시 인식하지 않게
    """
    import time

    return time.monotonic() < st.session_state.get("_tts_mute_until", 0.0)


def _run_mic_loop(*, drain_only: bool = False) -> str | None:
    """webrtc_streamer()를 딱 1번만 부르고, 연결돼 있는 동안 블로킹 루프를 돌며 프레임을
    계속 뽑아 VAD에 먹인다 — 발화 하나가 완성되면 그 텍스트를 반환하고 끝난다(마이크
    연결 자체는 끊지 않음 — 다음 listen() 호출 때 이 함수가 다시 불려서 이어서 듣는다).
    """
    try:
        from streamlit_webrtc import WebRtcMode, webrtc_streamer
    except Exception:
        return None

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
            audio_receiver_size=1024,
            media_stream_constraints={
                "video": False,
                "audio": {
                    "noiseSuppression": os.environ.get("WEBRTC_NOISE_SUPPRESSION", "true").lower()
                    != "false",
                    "autoGainControl": True,
                    "echoCancellation": True,
                },
            },
            rtc_configuration=_rtc_configuration(),
            desired_playing_state=True,
        )
    except Exception:
        return None

    if not webrtc_ctx.state.playing or webrtc_ctx.audio_receiver is None:
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

    try:
        while True:
            webrtc_ctx.audio_receiver.get_frames(timeout=0)
    except queue.Empty:
        pass
    except AttributeError:
        pass

    while webrtc_ctx.state.playing and webrtc_ctx.audio_receiver is not None:
        try:
            frames = webrtc_ctx.audio_receiver.get_frames(timeout=1)
        except queue.Empty:
            continue
        except AttributeError:
            break  # 위 주석과 같은 레이스 — get_frames() 호출 순간 None이 된 경우

        if drain_only:
            continue

        if _mic_muted():
            continue  # 프레임은 이미 꺼냈으니 밀리지 않음 — VAD엔 안 먹이고 버림

        for frame in frames:
            _arr = frame.to_ndarray()
            global _FRAME_DEBUG_COUNT
            if _FRAME_DEBUG_COUNT < 8:
                _FRAME_DEBUG_COUNT += 1
                print(
                    f"[FRAME_DEBUG] sample_rate={frame.sample_rate} shape={_arr.shape} "
                    f"dtype={_arr.dtype} frame.samples={getattr(frame, 'samples', None)} "
                    f"layout={getattr(frame.layout, 'name', None)} format={getattr(frame.format, 'name', None)}",
                    flush=True,
                )
            _channels = len(frame.layout.channels) if frame.layout is not None else 1
            utterance_audio = segmenter.feed(_arr, frame.sample_rate, channels=_channels)
            if utterance_audio is None:
                continue

            job: dict = {"done": False, "text": ""}
            _sid = st.session_state.get("_sid")

            def _run_stt(audio=utterance_audio, job=job, sid=_sid) -> None:
                # 백그라운드 스레드 — voice_io._synthesize_and_cache()와 같은 이유로
                # st.* API를 전혀 안 쓴다.
                import time

                try:
                    _mic_dbg = bool(os.environ.get("CHEFEAR_DEBUG"))
                    if _mic_dbg:
                        print(
                            f"[MIC_DEBUG] samples={len(audio)} dur={len(audio) / 16000:.2f}s "
                            f"max_amp={float(__import__('numpy').abs(audio).max()):.4f} "
                            f"rms={float(__import__('numpy').sqrt((audio ** 2).mean())):.4f}",
                            flush=True,
                        )
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
    """상시 마이크(실시간 스트리밍 인식) 또는 텍스트 입력으로 발화 하나를 받는다."""
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
