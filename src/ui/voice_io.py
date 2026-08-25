"""ChefEar STT/TTS 연결(speak/listen) — src/app.py에서 분리(2026-08-22, 화면 컴포넌트화).

세션 상태는 ui/session.py, 발화 디스패처는 ui/dispatch.py, 화면별 함수는 ui/screens/ 참고.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import soundfile as sf
import streamlit as st

from orchestration.db import load_env
from theme import render_audio_autoplay, render_audio_player, render_loading_overlay

# stt/infer.py·tts/infer.py·llm/infer.py와 같은 이유(각 모듈이 독립적으로 .env를 읽어야
# app.py 없이도, 또는 import 순서와 무관하게 TURN_HOST 등 환경변수를 쓸 수 있음) —
# 2026-08-23, _ice_servers()의 TURN_* 조회를 위해 추가.
load_env()

# 2026-08-23 임시 진단 로그 — "Connection is taking longer than expected"(WebRTC 연결
# 실패) 원인 파악용. aioice가 실제로 어떤 ICE 후보를 모으고 연결성 검사(connectivity
# check)가 왜 실패하는지 콘솔에 찍는다. 원인 확인되면 지울 것(상시로 켜두면 로그가
# 너무 많아짐).
if os.environ.get("WEBRTC_DEBUG"):
    import logging

    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("aioice").setLevel(logging.DEBUG)
    logging.getLogger("aiortc").setLevel(logging.DEBUG)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _ice_servers() -> list[dict]:
    """WebRTC(상시 마이크)의 ICE 서버 목록 — 구글 공개 STUN은 항상 넣고, .env에
    TURN_HOST/TURN_USERNAME/TURN_PASSWORD가 있으면 TURN도 같이 넣는다(2026-08-23).

    STUN만으로는 이 데스크탑처럼 WSL2가 Windows 뒤에 NAT로 숨어있는 환경에서, Tailscale
    등으로 접속하는 다른 기기가 오디오용 WebRTC(UDP) 연결을 못 뚫는 게 실측으로 확인됐다
    ("Connection is taking longer than expected" 에러). TURN은 양쪽이 TURN 서버로
    나가기만 하면 되므로 이런 이중 NAT에서도 거의 항상 통한다 — 이 데스크탑에 coturn을
    직접 띄우고 그 값을 .env에 채워두면 자동으로 쓰인다. 값이 없으면 조용히 STUN만
    쓰는 것으로 폴백한다(같은 기기 브라우저에서 테스트할 땐 STUN만으로도 충분함).
    """
    servers: list[dict] = [{"urls": ["stun:stun.l.google.com:19302"]}]

    turn_host = os.environ.get("TURN_HOST")
    turn_username = os.environ.get("TURN_USERNAME")
    turn_password = os.environ.get("TURN_PASSWORD")
    if turn_host and turn_username and turn_password:
        turn_port = os.environ.get("TURN_PORT") or "3478"
        servers.append(
            {
                "urls": [f"turn:{turn_host}:{turn_port}"],
                "username": turn_username,
                "credential": turn_password,
            }
        )
    return servers

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
# 이 셋 다 같은 GPU를 쓰는데 서로 간엔 아무 직렬화가 없었다. 평소엔 한 번에 하나씩만
# 발화가 처리돼 우연히 안 겹쳤겠지만, 겹치는 순간(예: 이전 발화 처리가 아직 안 끝났는데
# 새 발화의 STT/LLM 호출이 시작되는 경우) 같은 GPU에 동시에 여러 모델 추론이 들어가면서
# 멈추는 것으로 보인다 — 프로세스 전체가 멈춘 것처럼 보이는 것도 이 GPU 호출이 자바스크립트
# 스레드 GIL을 오래 붙들고 있어서일 가능성과 들어맞는다. TTS 전용이던 이 락을 GPU를
# 쓰는 모든 추론 호출(STT/임베딩/LLM/TTS)로 넓혀서, 항상 한 번에 하나씩만 GPU에
# 올라가게 한다.
_GPU_LOCK = threading.Lock()

def _common_audio_path(message: str) -> Path:
    """조리 단계처럼 recipe_id/step_number가 없는 1회성 문구(확인 질문·안내 등)의
    캐시 경로 — 문구 자체의 해시를 키로 쓴다. speak()와 _render_cached_speech()가
    같은 문구에 대해 항상 같은 경로를 계산해야 캐시가 서로 맞물린다."""
    import hashlib

    digest = hashlib.sha1(message.encode("utf-8")).hexdigest()[:16]
    return _AUDIO_DIR / "_common" / f"{digest}.wav"


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
    mute_until = time.monotonic() + duration + 0.6  # 0.6초: 재생 시작 지연 등 여유
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


def _drain_mic_while(job: dict, *, loading_message: str | None = "다음으로 넘어가고 있어요...") -> None:
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
    """
    import queue
    import time

    _SHOW_DELAY_S = 0.4

    overlay_slot = st.empty()
    overlay_shown = False
    start = time.monotonic()

    while not job["done"]:
        if loading_message and not overlay_shown and (time.monotonic() - start) >= _SHOW_DELAY_S:
            with overlay_slot:
                render_loading_overlay(loading_message)
            overlay_shown = True

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

    if overlay_shown:
        overlay_slot.empty()
        # 2026-08-25 리포트 — 이 함수를 부른 쪽(process_utterance()의 미분류 분기 등)이
        # 바로 다음 줄에서 st.rerun()을 부르는 경우, "지워라"(위 empty())와 "전체를 새로
        # 그려라"(뒤이은 rerun) 두 신호가 브라우저에 너무 붙어서 도착하면 첫 신호가 다
        # 반영되기 전에 두 번째가 덮쳐서 팝업이 지워지다 만 채로 남는 잔상이 실측
        # 확인됐다. 정확한 프론트엔드 내부 메커니즘은 확정 못 했지만(화면 전환 잔상
        # 전반과 같은 부류의 문제로 추정), 아주 짧은 간격을 둬서 "지워라" 델타가 먼저
        # 반영될 시간을 벌어주는 임시 완화책 — 근본 fix는 아니다.
        time.sleep(0.05)


def speak(
    message: str,
    *,
    recipe_id: str | None = None,
    step_number: int | None = None,
    hidden: bool = False,
) -> None:
    """TTS로 응답을 재생하고 채팅 로그에 남긴다. 합성 실패는 조용히 삼키지 않는다(EC-05) —
    화면 텍스트는 항상 남고, 음성만 실패했다는 걸 사용자에게 알린다.

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

        if not audio_path.exists():
            # 2026-08-23 — GPU 합성(3~9초) 자체는 백그라운드 스레드로 돌리고, 메인
            # 스레드는 그동안 _drain_mic_while()로 마이크 큐를 계속 비운다(위 함수
            # 문서 참고 — 안 그러면 이 블로킹 구간 동안 상시 마이크 연결이 브라우저
            # 쪽에서 스스로 끊긴다). 락(_GPU_LOCK)으로 prefetch_remaining_steps_audio()의
            # 백그라운드 스레드와 동시에 GPU 모델을 호출하지 않게 직렬화하는 건 그대로.
            job: dict = {"done": False, "error": None}

            def _run_synthesis(job=job) -> None:
                try:
                    with _GPU_LOCK:
                        if not audio_path.exists():
                            from tts.infer import tts_synthesize

                            waveform, sample_rate = tts_synthesize(message)
                            audio_path.parent.mkdir(parents=True, exist_ok=True)
                            sf.write(audio_path, waveform, sample_rate)
                except Exception as exc:  # noqa: BLE001 — 아래에서 다시 던져서 기존 except가 처리
                    job["error"] = exc
                finally:
                    job["done"] = True

            threading.Thread(target=_run_synthesis, daemon=True).start()
            _drain_mic_while(job)
            if job["error"] is not None:
                raise job["error"]

        # 2026-08-25 — hidden=True에서도 render_audio_autoplay()로 실제로 한 번 틀고
        # 있었다. hidden=True는 항상 "이 문구를 goto() 직전에 미리 합성/캐싱만 해두고,
        # 실제 재생은 도착 화면이 _render_cached_speech()/render_step_card()로 같은
        # 캐시를 다시 찾아 들려준다"는 용도로만 쓰인다(모든 호출부 확인 — dispatch.py의
        # 조회/진행/재료대체/취소, register.py의 저장완료 등 전부 도착 화면이 재생을
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


def _synthesize_and_cache(text: str, audio_path: Path) -> None:
    """백그라운드 스레드에서 실행되는 합성 함수 — speak()와 캐싱 규칙은 같지만 st.* API를
    전혀 안 쓴다(Streamlit 위젯 호출은 ScriptRunContext가 있는 메인 스레드에서만 안전해서,
    백그라운드 스레드에서 st.spinner/st.warning 등을 쓰면 경고가 뜨거나 깨질 수 있음).
    실패해도 조용히 넘어간다 — 프리페치일 뿐이라 실패하면 나중에 speak()가 그 자리에서
    다시 시도한다(EC-05는 speak() 쪽에서 이미 담당)."""
    if audio_path.exists():
        return
    try:
        with _GPU_LOCK:
            if audio_path.exists():
                return
            from tts.infer import tts_synthesize

            waveform, sample_rate = tts_synthesize(text)
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(audio_path, waveform, sample_rate)
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

    한 번에 여러 스레드를 띄우는 대신 스레드 하나가 남은 단계를 순서대로 도는 구조다 —
    _GPU_LOCK이 어차피 GPU 호출을 한 번에 하나씩만 허용하므로(speak()의 실시간 합성과
    직렬화), 스레드를 단계 수만큼 따로 만들어봐야 서로 락을 기다리기만 할 뿐이다.

    레시피 하나당(recipe_id 기준) 세션에서 딱 한 번만 이 백그라운드 작업을 시작한다
    (st.session_state의 "_full_prefetch_started" 집합으로 추적) — screen_cooking_step()이
    매 rerun(마이크 입력 대기 등)마다 다시 호출돼도 중복으로 스레드가 쌓이지 않게 한다.
    이미 캐싱된 단계는 _synthesize_and_cache() 안의 존재 확인으로 건너뛰므로, 사용자가
    이미 지나간 단계를 다시 합성하는 낭비는 없다.

    2026-08-22 추가 — 사용자가 이 레시피를 완주하지 않고 처음 화면으로 돌아가거나
    다른 레시피로 넘어가도(재료대체 포함) 버려진 레시피의 남은 단계를 계속 만들면
    안 된다는 지적으로, 매 단계 합성 전에 "지금도 이 레시피가 활성 상태인지"를
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

    def _run() -> None:
        for step in remaining:
            if active_recipe_box.get("recipe_id") != recipe_id:
                return  # 사용자가 이 레시피를 떠났음 — 남은 단계는 만들지 않고 중단
            step_num = step.get("step_number")
            audio_path = _AUDIO_DIR / str(recipe_id) / f"{step_num:02d}.wav"
            _synthesize_and_cache(step["text"], audio_path)

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
    불필요하게 재마운트하지 않기 위함)."""
    context = st.session_state.get(_mic_component_key())
    state = getattr(context, "state", None)
    signalling = bool(getattr(state, "signalling", False))

    if _mic_truly_alive(context):
        st.session_state["_mic_ever_connected"] = True
        return

    if st.session_state.get("_mic_ever_connected") and not signalling:
        st.session_state["_mic_gen"] = st.session_state.get("_mic_gen", 0) + 1
        st.session_state["_mic_ever_connected"] = False
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


def _run_mic_loop() -> str | None:
    """webrtc_streamer()를 딱 1번만 부르고, 연결돼 있는 동안 블로킹 루프를 돌며 프레임을
    계속 뽑아 VAD에 먹인다 — 발화 하나가 완성되면 그 텍스트를 반환하고 끝난다(마이크
    연결 자체는 끊지 않음 — 다음 listen() 호출 때 이 함수가 다시 불려서 이어서 듣는다).

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
            media_stream_constraints={"video": False, "audio": True},
            rtc_configuration={"iceServers": _ice_servers()},
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

            def _run_stt(audio=utterance_audio, job=job) -> None:
                # 백그라운드 스레드 — voice_io._synthesize_and_cache()와 같은 이유로
                # st.* API를 전혀 안 쓴다.
                try:
                    from stt.infer import stt_transcribe

                    # 2026-08-23 임시 진단(마이크 인식 문제) — 실제로 넘어오는 오디오 크기/레벨과
                    # STT 최종 결과를 눈으로 확인하기 위함. 원인 확인되면 지울 것.
                    print(
                        f"[MIC_DEBUG] samples={len(audio)} dur={len(audio) / 16000:.2f}s "
                        f"max_amp={float(__import__('numpy').abs(audio).max()):.4f} "
                        f"rms={float(__import__('numpy').sqrt((audio ** 2).mean())):.4f}",
                        flush=True,
                    )
                    # 2026-08-23 추가 — 사용자가 매번 다시 말해보고 결과를 알려주는 왕복이
                    # 너무 느리다(피드백 한 번에 최소 수십 초). 실제로 STT에 들어가는 오디오
                    # 자체를 파일로 남겨서, 재현 요청 없이 바로 들어보고 분석할 수 있게 한다.
                    import time as _time

                    _dump_dir = PROJECT_ROOT / "ui" / "assets" / "_mic_debug_dumps"
                    _dump_dir.mkdir(parents=True, exist_ok=True)
                    _ts = f"{_time.time():.3f}"
                    sf.write(_dump_dir / f"{_ts}.wav", audio, 16000)
                    # 2026-08-23 추가 — "녹음된 게 내 목소리가 아니다" 리포트 원인 파악용.
                    # mic_vad.py가 리샘플링 등 가공을 하기 전 원본(raw, 원본 샘플레이트) 오디오도
                    # 같이 남겨서, 문제가 캡처 단계(브라우저/webrtc)인지 가공 단계(이 저장소
                    # 코드)인지 구분한다. 원인 확인되면 지울 것.
                    if segmenter.last_raw_utterance is not None:
                        sf.write(
                            _dump_dir / f"{_ts}_raw.wav",
                            segmenter.last_raw_utterance,
                            segmenter.last_raw_sample_rate,
                        )
                    with _GPU_LOCK:
                        job["text"] = stt_transcribe(audio, sample_rate=16000).strip()
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

    mic_text = _run_mic_loop() if mic_enabled else None
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
