"""STT/TTS 텍스트 테스트 화면 - 이 앱에서 유일하게 진짜 백엔드에 연결된 화면.

다른 ui/streamlit_screens 화면들은 전부 mock_data.py의 가짜 데이터로 동작하지만
(각 화면의 render()가 fresh_recipe() 등을 씀), 이 화면만 예외로 orchestration.
pipeline.handle_utterance()를 그대로 호출해서 진짜 Supabase(60,196건)를 조회한다.
마이크/STT가 아직 없어서 텍스트 입력으로 "STT가 이렇게 알아들었다"를 흉내 낸다.

TTS(실제 음성)는 "이 단계 음성으로 듣기" 버튼을 눌렀을 때만 tts_synthesize()를
호출한다(자동재생 아님) — 로컬 CPU 환경 실측 결과 문장 하나 합성에 239초가
걸려서(2026-08-20 확인), 여러 단계를 미리 다 합성해두거나 자동재생하면 기다리는
시간이 감당이 안 된다. 한 번 합성한 오디오는 (recipe_id, step_number)로
session_state에 캐싱해서, 같은 단계를 "이전"/"다음"으로 다시 돌아왔을 때 또
기다리지 않게 한다. 합성이 끝나는 즉시 wav 파일도 자동으로
results/tts/new_sentences_test/에 저장된다(_save_wav_to_new_sentences_folder,
2026-08-20 — 재생만 하고 디스크엔 안 남기던 것에서 변경, 다운로드 버튼이 아니라
합성되는 순간 자동 저장하는 방식으로 요청받음).

orchestration.pipeline/tts.infer는 전부 함수 안에서 지연 import한다(모듈 최상단이
아니라) — ui/app.py가 시작할 때 streamlit_screens 패키지 전체를 한꺼번에 import하는데
(app.py의 SCREENS 등록부 참고), 여기서 최상단 import를 쓰면 이 화면을 아예 안 쓰고
시작 화면만 봐도 sentence-transformers/torch가 매번 로딩돼서 다른 화면들까지 다 느려진다
(실측 확인: 2026-08-20, 이 문제로 시작 화면 첫 로딩이 25초 넘게 걸렸었음). db.get_client()가
supabase를 지연 import하는 것과 같은 이유.
"""
import re
from pathlib import Path

import streamlit as st

from nav import goto
from theme import render_back_link, render_badge, render_chat, render_step_card

TTS_WAIT_WARNING = "음성 합성 중이에요... 로컬 CPU라 오래 걸릴 수 있어요(실측 239초/문장, 2026-08-20 확인). 잠시만 기다려주세요."

PLACEHOLDER = "예: 부대찌개 어떻게 만들어? / 다음 / 다시 / 이전"

# 합성된 wav를 자동 저장할 폴더 — 부대찌개 TTS 데모 때(2026-08-19) 쓰던 그 폴더를
# 그대로 재사용한다(results/tts/new_sentences_test/, 파일명 규칙도 그때와 동일하게
# "00_정제된텍스트.wav"). 이 화면(ui/streamlit_screens/)에서 2단계 위가 프로젝트 루트다.
NEW_SENTENCES_DIR = Path(__file__).resolve().parents[2] / "results" / "tts" / "new_sentences_test"

# 2026-08-23 추가(사용자 요청) — 마이크로 테스트하는 오디오를 전부 남겨서 나중에 들어보고
# 분석할 수 있게 한다. src/ui/voice_io.py._run_mic_loop()가 실서비스 앱(src/app.py)에서
# 쓰는 것과 같은 경로(ui/assets/_mic_debug_dumps/) — 이 화면(ui/app.py, mock 프로토타입)으로
# 테스트하든 실서비스 앱으로 테스트하든 한곳에 다 모이게 통일한다.
MIC_DEBUG_DUMP_DIR = Path(__file__).resolve().parents[2] / "ui" / "assets" / "_mic_debug_dumps"


def _wav_path_for(step_number: int, text: str) -> Path:
    """저장/존재확인 둘 다에서 같은 파일명 규칙을 쓰려고 경로 계산만 따로 뺐다."""
    clean_text = re.sub(r"[\s,.!?]", "", text)[:20]
    return NEW_SENTENCES_DIR / f"{step_number:02d}_{clean_text}.wav"


def _save_wav_to_new_sentences_folder(step_number: int, text: str, waveform, sample_rate: int) -> Path:
    """합성 직후 자동으로 wav 파일을 디스크에 남긴다(재생만 하고 안 남기던 것에서 변경,
    2026-08-20 사용자 요청). 파일명은 기존 부대찌개 데모 파일들과 같은 규칙 —
    "00_김치두부떡을먹기좋은크기로썰어주세요.wav"처럼 공백/문장부호를 지운 본문 앞 20자.
    """
    import soundfile as sf  # 지연 import, 파일 상단 주석 참고(가벼운 패키지지만 통일)

    NEW_SENTENCES_DIR.mkdir(parents=True, exist_ok=True)
    path = _wav_path_for(step_number, text)
    sf.write(path, waveform, sample_rate)
    return path

# 하드코딩 테스트용 — 요리명 매칭(extract_dish_name) 단계를 건너뛰고, "이 UUID로
# recipe_steps를 바로 불러오는 게 되는지"만 따로 확인하고 싶을 때 쓴다(2026-08-20 실측
# 확인: recipes 테이블에 dish_name="순살갈비찜"인 행이 정확히 1건 있고, 이 id로
# recipe_steps에 8단계가 붙어있다). CSV/DB 재적재로 id가 바뀌면 이 값도 다시 확인해야 함.
HARDCODED_TEST_DISH_NAME = "순살갈비찜"
HARDCODED_TEST_RECIPE_ID = "0043bed8-35ad-404d-ab5a-cc3f12dcd619"


def _summarize(result: dict) -> str:
    """handle_utterance()의 응답 dict를 render_chat()에 넣을 짧은 문장으로 바꾼다."""
    intent = result.get("intent")
    if "message" in result:
        return result["message"]
    if intent == "조회":
        return f"'{result.get('dish_name')}' 레시피를 찾았어요. 아래에서 조리 단계를 확인하세요."
    if intent in ("진행", "재청취", "이전"):
        if result.get("no_previous"):
            return "1단계예요, 이전 단계가 없어요."
        step = result.get("step") or {}
        return step.get("text", "")
    if intent == "취소":
        return f"{result.get('dish_name')}(으)로 되돌렸어요." if result.get("rolled_back") else "되돌릴 대체가 없어요."
    if intent == "재료대체":
        return f"'{result.get('result_dish_name')}'(으)로 대체했어요."
    if intent == "등록":
        return result.get("prompt") or result.get("summary") or "등록을 진행할게요."
    return str(result)


def _ensure_state() -> None:
    # backend_session: handle_utterance()가 요구하는 그 세션 dict(진행 단계·현재 recipe_id 등).
    # ui/의 다른 mock 화면들이 쓰는 st.session_state.recipe/step_number와는 완전히 별개다 —
    # 진짜 오케스트레이션 로직이 기대하는 키(current_recipe_id, step_number, ...)를 그대로 쓴다.
    st.session_state.setdefault("stt_test_backend_session", {})
    st.session_state.setdefault("stt_test_chat", [])
    st.session_state.setdefault("stt_test_dish_name", "")
    # (recipe_id, step_number) -> (waveform, sample_rate). 같은 단계를 다시 방문했을 때
    # tts_synthesize()를 또 안 부르려고 세션 안에서만 캐싱한다(프로세스 재시작하면 사라짐).
    st.session_state.setdefault("stt_test_audio_cache", {})
    if "stt_test_client" not in st.session_state:
        # get_client()는 부를 때마다 새 객체를 만든다(db.py 설계) — Streamlit은 상호작용마다
        # 스크립트를 전부 다시 실행하므로, 매번 새로 부르면 extract_dish_name()의 요리명 캐시
        # (client 객체별 lru_cache, recipe_search.py)가 매번 새 키를 받아 절대 재사용되지
        # 않는다. session_state에 담아 같은 세션 안에서는 항상 같은 client를 재사용한다.
        from orchestration.db import get_client  # 지연 import, 파일 상단 주석 참고

        st.session_state.stt_test_client = get_client()


def _render_always_on_mic(backend_session: dict, client, process_utterance) -> None:
    """webrtc_streamer()로 브라우저 마이크를 실시간으로 받아, MicVadSegmenter로
    "한 발화"를 잘라내고, stt.infer.stt_transcribe()로 텍스트로 바꾼 뒤
    process_utterance()(=handle_utterance()와 동일 처리)에 넘긴다.

    streamlit-webrtc의 표준 실시간 처리 패턴을 그대로 따른다 — webrtc가 재생 중인
    동안 이 함수 안에서 while 루프를 돌며 계속 프레임을 받는다. 이 루프가 도는
    동안은 render() 나머지 부분(하드코딩 목록·전체 조리순서 등)이 실행되지
    않는다 — 그래서 상태 표시(듣는 중/인식 중)와 대화 로그를 이 함수 안에서
    st.empty() 플레이스홀더로 자체적으로 그린다. 마이크를 끄면 루프가 끝나고
    스크립트가 계속 진행돼 나머지 화면이 정상적으로 그려진다.
    """
    from streamlit_webrtc import WebRtcMode, webrtc_streamer

    webrtc_ctx = webrtc_streamer(
        key="always_on_mic",
        mode=WebRtcMode.SENDONLY,
        audio_receiver_size=256,
        media_stream_constraints={"video": False, "audio": True},
        rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
    )

    status_ph = st.empty()
    chat_ph = st.empty()

    if not webrtc_ctx.state.playing:
        status_ph.caption("마이크가 꺼져 있어요. 위 Start를 눌러 켜주세요.")
        return

    if "mic_segmenter" not in st.session_state:
        from mic_vad import MicVadSegmenter

        st.session_state.mic_segmenter = MicVadSegmenter()
    segmenter = st.session_state.mic_segmenter

    import queue

    status_ph.info("🎙️ 듣고 있어요...")
    while webrtc_ctx.state.playing:
        if webrtc_ctx.audio_receiver is None:
            break
        try:
            audio_frames = webrtc_ctx.audio_receiver.get_frames(timeout=1)
        except queue.Empty:
            continue

        for frame in audio_frames:
            # 2026-08-23 — src/ui/voice_io.py._run_mic_loop()와 같은 수정(채널 수를
            # frame.layout에서 알아내 명시적으로 넘김, mic_vad.py::_to_mono_float32() 주석
            # 참고) — 여기도 같은 MicVadSegmenter.feed()를 쓰는 별도 호출부라 빠져 있으면
            # stereo/packed 프레임에서 "굵고 느린 목소리"(음이 낮고 늘어짐) 버그가 그대로 남는다.
            _channels = len(frame.layout.channels) if frame.layout is not None else 1
            utterance_audio = segmenter.feed(frame.to_ndarray(), frame.sample_rate, channels=_channels)
            if utterance_audio is None:
                continue

            # 2026-08-23 추가(사용자 요청) — src/ui/voice_io.py._run_mic_loop()와 같은 덤프.
            # 인식 성공 여부와 무관하게 VAD가 잘라낸 발화는 전부 저장한다(stt_transcribe()
            # 호출 *전에* 저장 — 인식이 실패해도 원인 분석용 오디오는 남아야 하므로). 가공 전
            # 원본(raw, 원본 샘플레이트)도 segmenter.last_raw_utterance에 있으면 같이 남긴다.
            import time as _time

            import soundfile as sf

            MIC_DEBUG_DUMP_DIR.mkdir(parents=True, exist_ok=True)
            _ts = f"{_time.time():.3f}"
            sf.write(MIC_DEBUG_DUMP_DIR / f"{_ts}.wav", utterance_audio, 16000)
            if segmenter.last_raw_utterance is not None:
                sf.write(
                    MIC_DEBUG_DUMP_DIR / f"{_ts}_raw.wav",
                    segmenter.last_raw_utterance,
                    segmenter.last_raw_sample_rate,
                )

            status_ph.info("🧠 인식 중...")
            from stt.infer import stt_transcribe

            # 2026-08-23: stt_transcribe()의 sample_rate는 키워드 전용 인자다(src/stt/infer.py
            # 이름 충돌 수정 참고) — 예전엔 이 파일 안에 같은 이름의 다른 함수(위치 인자 허용)가
            # 이 호출을 대신 받아서 위치 인자로도 동작했지만, 지금은 진짜 배포용 함수가 불려서
            # 위치 인자로 주면 TypeError가 난다.
            text = stt_transcribe(utterance_audio, sample_rate=16000)
            if text.strip():
                process_utterance(text)
                with chat_ph.container():
                    render_chat(st.session_state.stt_test_chat[-6:])
            status_ph.info("🎙️ 듣고 있어요...")

    status_ph.caption("마이크가 꺼졌어요.")


def render() -> None:
    from orchestration.pipeline import get_precomputed_steps, handle_utterance  # 지연 import, 파일 상단 주석 참고

    _ensure_state()

    if render_back_link():
        goto("start")

    st.markdown('<div class="ce-center"><h1>STT/TTS 텍스트 테스트</h1></div>', unsafe_allow_html=True)
    st.caption(
        "마이크 대신 텍스트로 발화를 흉내 냅니다. 실제 Supabase 데이터로 요리명 조회와 "
        "다음/다시/이전 진행을 검증합니다. 재료대체·신규등록은 이 화면에서 아직 지원하지 않습니다. "
        "음성은 자동재생이 아니라 단계마다 버튼을 눌러야 합성됩니다(로컬 CPU라 느림)."
    )

    backend_session = st.session_state.stt_test_backend_session
    client = st.session_state.stt_test_client

    with st.expander(f"🔧 하드코딩 테스트 — {HARDCODED_TEST_DISH_NAME}", expanded=False):
        st.caption("요리명 매칭(extract_dish_name) 단계를 건너뛰고, 미리 알고 있는 recipe_id(UUID)만으로 recipe_steps 조회가 되는지 확인합니다.")
        st.code(HARDCODED_TEST_RECIPE_ID, language=None)
        if st.button(f"이 UUID로 '{HARDCODED_TEST_DISH_NAME}' 조리순서 불러오기"):
            hardcoded_result = get_precomputed_steps(HARDCODED_TEST_RECIPE_ID, client=client)
            if hardcoded_result.get("available"):
                backend_session["current_recipe_id"] = HARDCODED_TEST_RECIPE_ID
                backend_session["step_number"] = 1
                st.session_state.stt_test_dish_name = HARDCODED_TEST_DISH_NAME
                st.session_state.stt_test_chat.append(("user", f"[하드코딩] recipe_id={HARDCODED_TEST_RECIPE_ID}로 직접 조회"))
                st.session_state.stt_test_chat.append(
                    ("ai", f"'{HARDCODED_TEST_DISH_NAME}' {len(hardcoded_result['steps'])}단계를 이 UUID로 불러왔어요.")
                )
            else:
                st.error(f"실패 — {hardcoded_result.get('message')} (recipe_id가 바뀌었을 수 있음)")

        if st.button(f"🔊 '{HARDCODED_TEST_DISH_NAME}' 전체 단계 음성 생성 및 저장", key="tts_btn_all_hardcoded"):
            from tts.infer import tts_synthesize  # 지연 import, 파일 상단 주석 참고

            all_result = get_precomputed_steps(HARDCODED_TEST_RECIPE_ID, client=client)
            if not all_result.get("available"):
                st.error(f"실패 — {all_result.get('message')}")
            else:
                all_steps = all_result["steps"]
                progress = st.progress(0.0, text=f"0 / {len(all_steps)}단계")
                for i, step in enumerate(all_steps, start=1):
                    audio_key = (HARDCODED_TEST_RECIPE_ID, step["step_number"])
                    existing_path = _wav_path_for(step["step_number"], step["text"])
                    if audio_key not in st.session_state.stt_test_audio_cache:
                        if existing_path.exists():
                            # 이전 실행에서 이미 저장된 파일이 있으면(디스크 기준) 다시
                            # 합성하지 않는다 — 문장 하나에 최대 몇 분씩 걸려서, 8단계를
                            # 여러 번 테스트할 때마다 매번 새로 만드는 건 낭비다. 다시 읽어서
                            # 세션 캐시(재생/다음/이전용)에만 채워 넣는다.
                            import soundfile as sf

                            waveform, sample_rate = sf.read(existing_path)
                        else:
                            progress.progress(
                                (i - 1) / len(all_steps),
                                text=f"{step['step_number']}단계 합성 중... ({i}/{len(all_steps)}, 로컬 CPU라 단계당 최대 몇 분 걸릴 수 있음)",
                            )
                            waveform, sample_rate = tts_synthesize(step["text"])
                            _save_wav_to_new_sentences_folder(step["step_number"], step["text"], waveform, sample_rate)
                        st.session_state.stt_test_audio_cache[audio_key] = (waveform, sample_rate)
                    progress.progress(i / len(all_steps), text=f"{i} / {len(all_steps)}단계 완료")
                st.success(f"전체 {len(all_steps)}단계 음성 생성·저장 완료 — {NEW_SENTENCES_DIR}")

        # 전체 목록을 그릴 "자리"만 여기서 미리 예약해둔다(화면상 위치는 버튼 바로 아래).
        # 실제 내용은 아래 발화 처리(폼 submit)가 끝나 step_number가 최신 상태가 된
        # *다음에* 채운다(스크립트 맨 아래 참고) — 여기서 바로 채우면 "다음"을 눌러도
        # 이 목록의 👉 마커가 폼 처리 전 값(한 턴 전 상태)을 보여주는 버그가 생긴다
        # (실측 확인: 2026-08-20, 배지는 2/8로 바뀌는데 이 목록만 1에 멈춰있었음 —
        # Streamlit은 스크립트를 위에서 아래로 한 번에 실행하므로, 이 블록이 폼 처리보다
        # 먼저 실행되면 아직 안 바뀐 값을 읽는다).
        hardcoded_list_slot = st.container()

    def process_utterance(text: str) -> dict:
        """텍스트 입력 폼과 마이크 루프가 똑같은 처리를 하도록 공통화한 것 —
        따로 두면 나중에 둘 중 하나만 고치고 다른 쪽을 깜빡하는 divergence가 생기기 쉽다."""
        result = handle_utterance(backend_session, text, client=client)
        if result.get("intent") == "조회" and result.get("dish_name"):
            st.session_state.stt_test_dish_name = result["dish_name"]
        st.session_state.stt_test_chat.append(("user", text))
        st.session_state.stt_test_chat.append(("ai", _summarize(result)))
        return result

    with st.form("stt_tts_test_form", clear_on_submit=True):
        utterance = st.text_input("발화 입력", placeholder=PLACEHOLDER)
        submitted = st.form_submit_button("전송")

    if submitted and utterance.strip():
        process_utterance(utterance)

    with st.expander("🎙️ 상시 마이크 (실험적 — streamlit-webrtc + VAD)", expanded=False):
        st.caption(
            "마이크를 켜두면 계속 듣고 있다가, 말이 끝나고 잠깐(약 0.6초) 조용해지면 그때까지를 "
            "한 발화로 잘라 인식합니다. STT는 배포용 파인튜닝 어댑터(stt_transcribe(), int8 CTranslate2)를 "
            "씁니다 — 2026-08-23 이전엔 이름 충돌로 원본 모델이 대신 불렸었지만 지금은 고쳐졌습니다"
            "(src/stt/README.md 2026-08-23 항목 참고). 원본 모델과 비교하려면 "
            "src/stt/compare_realtime_models.py를 참고하세요."
        )
        _render_always_on_mic(backend_session, client, process_utterance)

    # 이 하드코딩 레시피가 지금 활성 상태면(방금 위 버튼을 눌렀든, 그 전에 눌러놓고 아래
    # 발화 입력으로 "다음"/"이전"만 하고 있는 중이든) 현재 단계 하나만이 아니라 전체
    # 단계를 다 보여준다 — 일반 조회 흐름(아래 render_step_card)은 실제 제품처럼 한
    # 단계씩만 보여주는 게 맞지만, 이 하드코딩 테스트는 "UUID로 전체가 다 불러와지는지"
    # 자체를 눈으로 확인하려는 용도라 목적이 다르다. hardcoded_list_slot 컨테이너 덕분에
    # 여기서 채워도 화면상으로는 위쪽 expander 안(버튼 바로 아래)에 나타난다.
    if backend_session.get("current_recipe_id") == HARDCODED_TEST_RECIPE_ID:
        all_steps_result = get_precomputed_steps(HARDCODED_TEST_RECIPE_ID, client=client)
        if all_steps_result.get("available"):
            all_steps = all_steps_result["steps"]
            current = backend_session.get("step_number", 1)
            with hardcoded_list_slot:
                st.success(f"이 UUID로 전체 {len(all_steps)}단계 조회됨:")
                for step in all_steps:
                    marker = "👉 " if step["step_number"] == current else ""
                    st.write(f"{marker}{step['step_number']}. {step['text']}")

    if st.session_state.stt_test_chat:
        render_chat(st.session_state.stt_test_chat)

    recipe_id = backend_session.get("current_recipe_id")
    if recipe_id:
        steps_result = get_precomputed_steps(recipe_id, client=client)
        if steps_result.get("available"):
            steps = steps_result["steps"]
            total = len(steps)
            current_step_number = min(backend_session.get("step_number", 1), total)
            current_text = steps[current_step_number - 1]["text"]
            render_badge(f"{st.session_state.stt_test_dish_name} · {current_step_number} / {total} 단계")
            render_step_card(total, current_step_number, current_text, show_player=False)

            audio_key = (recipe_id, current_step_number)
            cached = st.session_state.stt_test_audio_cache.get(audio_key)
            if cached is None:
                if st.button("🔊 이 단계 음성으로 듣기", key=f"tts_btn_{current_step_number}"):
                    from tts.infer import tts_synthesize  # 지연 import, 파일 상단 주석 참고

                    with st.spinner(TTS_WAIT_WARNING):
                        cached = tts_synthesize(current_text)
                    st.session_state.stt_test_audio_cache[audio_key] = cached

                    saved_path = _save_wav_to_new_sentences_folder(current_step_number, current_text, *cached)
                    st.caption(f"💾 저장됨: {saved_path}")

            if cached is not None:
                waveform, sample_rate = cached
                st.audio(waveform, sample_rate=sample_rate)

            # 하드코딩 테스트와 같은 이유·같은 방식 — 현재 단계 카드만이 아니라 전체
            # 단계를 다 보여준다. 이 블록은 이미 발화 처리(폼 submit) *다음*에 있어서
            # (위 하드코딩 섹션과 달리 st.container()로 순서를 우회할 필요가 없다 —
            # 여기는 애초에 스크립트 순서상 폼 처리 뒤라 최신 step_number를 바로 읽는다)
            # "다음"/"이전"을 눌러도 마커가 한 턴 뒤처지는 문제가 없다.
            st.divider()
            st.caption("전체 조리순서 (테스트용 — 실제 제품은 TTS로 한 단계씩만 읽어줌)")
            for step in steps:
                marker = "👉 " if step["step_number"] == current_step_number else ""
                st.write(f"{marker}{step['step_number']}. {step['text']}")
