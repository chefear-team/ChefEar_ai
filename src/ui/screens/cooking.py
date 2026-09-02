"""ChefEar 조리 흐름 화면(start/recipe_confirm/cooking_step) — src/app.py에서 분리
(2026-08-22, 화면 컴포넌트화)."""
from __future__ import annotations

import streamlit as st

from theme import (
    ICON_CHECK_CIRCLE,
    render_back_link,
    render_badge,
    render_big_mic,
    render_chat,
    render_chips,
    render_mic_bar,
    render_spacer,
    render_step_card,
)
from orchestration.term_dict import resolve_for_display, resolve_for_tts
from ui.dispatch import COOKING_COMPLETE_MESSAGE, fallback_buttons, is_home_word, reset_to_start
from ui.recipe_view import _ingredients_to_chips, refresh_recipe_view
from ui.session import goto
from ui.voice_io import _AUDIO_DIR, _render_cached_speech, mic_is_playing, prefetch_remaining_steps_audio, speak


def screen_start() -> None:
    render_spacer()
    # 2026-08-26 요청 — "무엇을 만들고 싶으세요?" 제목부터 마이크 부분까지(로고·로그인
    # 버튼은 제외)를 전체적으로 100px 아래로. 로고/로그인은 render_brand()가 app.py에서
    # 이 함수보다 먼저 그려서 안 밀린다 — 그래서 이 화면 "본문"의 맨 앞에 고정 높이 빈
    # 칸만 추가하면 그 아래 내용 전체가 그만큼 밀린다(위 render_spacer()의 flex:1과
    # 달리 유동적이지 않은 고정 100px).
    st.markdown('<div style="height:100px;"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ce-center"><h1>무엇을 만들고 싶으세요?</h1>'
        "<p>숫자 메뉴 없이, 하고 싶은 말을 편하게 그대로 말씀해주세요.</p>"
        '<p style="color:var(--text-faint); font-size:13.5px;">예: "된장찌개 어떻게 만들어?"</p></div>',
        unsafe_allow_html=True,
    )
    # 2026-08-25 추가 — dispatch.py::process_utterance()가 로그인 안 한 상태의 "등록"
    # 발화에 goto() 없이 이 화면에 그대로 머무르며 speak(..., hidden=True)로 안내
    # 음성만 미리 합성/캐싱해둔다(그 자리에서 바로 재생 위젯을 그리면 뒤이은 rerun에
    # 곧장 지워져 소리가 거의 안 들리는 문제가 실측 확인됨, dispatch.py 주석 참고) —
    # no_match/recipe_confirm과 같은 패턴으로, 이 화면 자신이 다음 rerun에서 chat_log의
    # 마지막 ai 메시지를 여기서 다시 찾아 들려준다.
    #
    # cooking_complete 완료 멘트 건과 똑같은 이유로(위 screen_cooking_complete() 문서의
    # "_cooking_complete_audio_played" 참고 — Streamlit이 이 오디오 iframe을 rerun마다
    # 새 DOM 엘리먼트로 다시 만들어서, 같은 파일이라도 브라우저의 "이미 로드된 오디오는
    # 다시 안 튼다" 방어가 안 먹히는 게 실측 확인됨) 여기도 "정확히 한 번만 재생"을
    # 플래그로 명시적으로 강제한다 — start 화면은 다른 화면보다도 훨씬 자주(마이크
    # idle 폴링 등으로) 다시 그려지는 화면이라, 이 가드 없이 chat_log만 보고 매번
    # 다시 재생을 시도하면 가만히 있는 동안 안내 음성이 계속 반복될 위험이 실제로
    # 있다. 재생한 뒤 바로 chat_log를 비워서 다음 rerun엔 조건 자체가 안 걸리게 한다
    # (이 화면은 대화 기록을 화면에 안 보여주므로 비워도 다른 부작용 없음).
    chat_log = st.session_state.chat_log
    if chat_log and chat_log[-1][0] == "ai":
        # 2026-08-27 수정 — 같은 화면(start)에 머무른 채 같은 문구를 반복 재생해야
        # 하는 경우(예: 조회 실패 안내), nonce 없이 부르면 브라우저가 "이미 로드된
        # 오디오"로 보고 두 번째 시도부터 autoplay를 다시 실행하지 않는다
        # (render_audio_player()/render_audio_autoplay() 문서 참고 — 같은 audio_src
        # 문자열이면 iframe srcDoc이 안 바뀐 걸로 보고 리마운트 안 함). recipe_confirm이
        # 이미 쓰는 것과 같은 패턴(_audio_replay_nonce)으로 맞춘다 — 반복 재생이
        # 필요한 호출부가 이 값을 올려주면, 여기서 읽기만 해도 매번 새로 재생된다.
        _render_cached_speech(chat_log[-1][1], nonce=st.session_state.get("_audio_replay_nonce", 0))
        st.session_state.chat_log = []
    # 2026-08-23 요청 — "준비됐는지 안 됐는지 모르겠다": 실제 연결 상태(mic_is_playing())를
    # 큰 마이크 아이콘 색으로 보여준다. 아래 listen("start")가 이 값을 이번 rerun에서
    # 갱신하기 *전에* 먼저 읽으므로 화면 위쪽(아이콘)이 먼저, 실제 연결 시도는 그 아래에서
    # 이어지는 순서 그대로다 — 값 자체는 직전 rerun까지의 최신 상태라 문제없다.
    render_big_mic(ready=mic_is_playing())

    # 2026-08-23 — 처음엔 "start 화면에서만 마이크를 끈다"로 만들었는데(mic_enabled=False),
    # 재요청으로 되돌림: start도 다른 화면과 똑같이 상시 마이크 연결을 유지한다. 대신
    # webrtc_streamer(desired_playing_state=True, voice_io._run_mic_loop() 참고)로 이
    # 화면이 뜨자마자(=페이지 로드하자마자) 클릭 없이 바로 연결을 시도하게 했다 — 브라우저가
    # 이 사이트에 마이크 권한을 이미 준 적 있으면 정말로 클릭 한 번 없이 곧장 "준비 상태"가
    # 된다. render_big_mic()의 큰 원형 아이콘은 그 상태를 보여주는 장식 요소로 남는다.
    #
    # 2026-08-25 — listen() 호출 자체는 이제 이 함수(화면 "본문")가 아니라 app.py::main()이
    # 화면별 key 컨테이너 *밖에서* 직접 부른다(_run_mic_loop() 정의부와 app.py 주석 참고 —
    # 화면 key 컨테이너가 바뀔 때마다 그 안에 있던 webrtc 컴포넌트가 매번 통째로 재마운트돼
    # 마이크가 화면 전환마다 새로 연결되는 문제가 실측 확인됨). 이 화면의 발화 처리는 여전히
    # process_utterance()를 그대로 쓴다 — app.py가 "start" 화면일 때 그 함수를 핸들러로 넘긴다.

    # 2026-08-21: 위쪽에만 render_spacer()가 있고 아래쪽엔 없어서, block-container의
    # flex:1 남는 공간이 전부 위에만 쌓여 콘텐츠가 화면 아래쪽으로 밀렸다 - 뷰포트가
    # 높을수록(세로로 긴 화면비) 남는 공간 자체가 커져서 그만큼 더 크게 벌어져 보였다.
    # 다른 화면들(register_dish_name, complete, login 등)처럼 아래에도 render_spacer()를
    # 넣어 남는 공간을 위아래로 똑같이 나눠 화면 비율과 무관하게 수직 중앙 정렬되게 한다.
    render_spacer()


def screen_recipe_confirm() -> None:
    view = st.session_state.recipe_view
    if not view:
        # 2026-09-01 — 진단 로그 추가(실측 리포트: "다음"이라고 확정했는데 시작
        # 화면으로 되돌아감 — 원인 후보 중 하나로 recipe_view가 이 시점에 비어있는
        # 경우를 의심 중). 이 줄이 안 찍히면 이 가드는 원인이 아니라는 뜻이다.
        print("[GUARD] screen_recipe_confirm: recipe_view 비어있음 -> start로", flush=True)
        goto("start")
        return

    render_badge("조회수 1위 표준 레시피")
    # 2026-08-22 재요청 때는 대화 기록을 안 보여주고 마지막 AI 메시지만 타자기 텍스트로
    # 보여줬는데, 2026-08-26 재요청 — "다른 레시피 화면(cooking_step 등)에서도 쓰는
    # 챗 형태 박스를 여기도 넣어달라"로 뒤집혔다. render_typewriter_message() 대신
    # cooking_step/no_match와 완전히 같은 render_chat(chat_log) 컴포넌트를 그대로
    # 재사용한다 — 사용자의 조회 질문("나: ...")까지 포함해서 다른 화면과 똑같이 전체
    # 대화 기록을 보여준다.
    chat_log = st.session_state.chat_log
    # 2026-08-28 수정 — chat_log[-1]만 보던 것을 "마지막 ai 메시지"로 바꿈. handle_recipe_confirm()
    # 의 "다시" 분기가 2026-08-26부터 ("user","다시")를 먼저 append하는데, 그러면 chat_log[-1]이
    # ai가 아니게 되어 이 재생 조건이 False가 되고 "다시"라고 해도 확인 문구가 안 들렸다
    # (nonce만 올라감). 뒤에서부터 첫 ai 메시지를 찾으면 도착 시점(마지막이 ai)과 "다시"
    # (마지막이 user) 둘 다에서 같은 확인 문구를 재생한다.
    last_ai = next((m for role, m in reversed(chat_log) if role == "ai"), None)
    if last_ai is not None:
        # dispatch.py가 이 화면으로 넘어오기 직전 speak(..., hidden=True)로 미리 합성/캐싱만
        # 해둔 문구를 여기서 다시 찾아 들려준다(2026-08-22 리포트 — 화면 전환 중 이전
        # 화면 하단에 재생바가 "떴다 사라짐" 깜빡이는 문제, no_match/unclassified와 같은 패턴).
        # nonce(2026-08-23) — 아래 "다시" 처리가 이 값을 올려서 같은 문구를 한 번 더 듣게 한다.
        _render_cached_speech(last_ai, nonce=st.session_state.get("_audio_replay_nonce", 0))
    if chat_log:
        render_chat(chat_log)

    st.markdown("**재료 미리보기**")
    render_chips(_ingredients_to_chips(view["ingredients_raw"]))

    # 2026-08-23 요청 — "연결됐는지 안 됐는지 모르겠다": listening을 항상 True로 고정하지
    # 않고 실제 연결 상태(mic_is_playing())를 그대로 보여준다.
    _mic_ready = mic_is_playing()
    render_mic_bar(
        "듣는 중" if _mic_ready else "마이크 연결 중...",
        '"응" 또는 다른 요청을 말씀해주세요',
        listening=_mic_ready,
    )

    # 2026-08-25 — listen() 호출은 이제 이 함수(화면 "본문")가 아니라 app.py::main()이
    # 화면별 key 컨테이너 *밖에서* 직접 부르고, 잡힌 텍스트를 아래 handle_recipe_confirm()에
    # 넘긴다(cooking.py 상단 주석/app.py 주석 참고 — 마이크가 화면 전환마다 재마운트되는
    # 문제 대응). "응"(긍정) 확인은 classify_intent()가 처리하지 않아서(의도적 제외,
    # tests/integration_test.md 기록) 이 화면 전용 핸들러가 문자열을 직접 비교한다.

    # 2026-08-27 — 잔상 방지용 key. 이 버튼 자체엔 원래 key가 없어서 CSS로 화면
    # 소속을 특정할 방법이 없었다 — theme.py::render_screen_cleanup()이 이 key로
    # "recipe_confirm이 아닌 화면에 남아있으면 잔상"으로 판정해 지운다.
    with st.container(key="recipe_confirm_other_recipe_btn"):
        if st.button("다른 레시피 찾을래요", use_container_width=True):
            goto("start")


def handle_recipe_confirm(text: str) -> None:
    """screen_recipe_confirm()이 그려진 뒤 app.py가 잡아온 발화를 처리한다.

    이 화면은 process_utterance()를 안 거치고 직접 문자열을 비교하는 구조다(아래
    이유 참고) — process_utterance() 맨 앞에서 하던 chat_log 기록도 안 타고 있었어서
    "응"/"좋아" 같은 확정 발화가 대화 기록에서 통째로 빠지는 실측 리포트("내가 했던
    대화 내용이 없다")로 확인, 각 분기 안에서 직접 기록해준다.

    2026-08-26 재요청 — "내 발화가 성공하면(=정상적으로 인식·처리됐으면) 기록에
    남겨야 한다": "처음"/"다시"/확정 단어 세 분기 전부 실제로 인식돼 뭔가 처리한
    성공 케이스라 기록한다. 맨 아래 "아무 분기에도 안 걸린" 무시 케이스만 기록에서
    빠진다(성공한 게 없어서). ChefEar/AI 응답(speak())은 이 규칙과 무관하게 항상
    남는다.
    """
    view = st.session_state.recipe_view
    if not view:
        # 2026-09-01 — 진단 로그. 이 줄이 찍히면 handle_recipe_confirm() 자신도
        # recipe_view가 비어있는 걸 봤다는 뜻 — screen_recipe_confirm()의 같은 가드와
        # 같은 rerun에서 같이 걸렸을 가능성이 높다(app.py 라우팅상 화면 렌더 -> 발화
        # 처리 순서라서 렌더 쪽이 먼저 goto("start")를 건 뒤에도 이 함수는 여전히
        # 호출됨).
        print(f"[GUARD] handle_recipe_confirm: recipe_view 비어있음, text={text!r} -> 무시", flush=True)
        return  # 화면 본문이 이미 goto("start")로 넘어갔을 상황 — 방어적으로만 남김

    norm = text.strip().rstrip("?!. ")
    print(f"[RECIPE_CONFIRM] text={text!r} norm={norm!r}", flush=True)
    # 2026-08-22 원래 의도로 되돌림 — 이 화면은 원래 "확정 단어 목록 -> 진행,
    # 그 외 전부 -> 처음 화면"이라는 단순한 이분법으로 설계됐었는데, 그동안
    # else 분기가 process_utterance()(classify_intent() 전체 파이프라인)로
    # 넘어가게 돼 있었다. "조회수 1위 표준 레시피"
    # 화면이라 여기서 진행/이전 같은 다른 의도까지 판단할 필요가 없고,
    # 이 레시피가 아니면 "다른 레시피 찾을래요" 버튼과 똑같이 처음 화면으로
    # 보내 새로 요리명을 말하게 하는 게 원래 설계다.
    #
    # 2026-08-23 재요청 — 세 가지를 정확히 구분해야 한다: (1) "처음"이 들어있으면
    # 무조건 초기 화면으로(reset_to_start()로 진행 중이던 것도 같이 비움), (2) "다시"가
    # 들어있으면 화면 전환 없이 방금 그 확인 문구만 한 번 더 들려줌, (3) 그 외
    # 확정 단어(응/네/좋아/다음)가 "포함"돼 있으면 진행 — 예전처럼 발화 전체가 그
    # 단어와 정확히 같아야만 인정하던 것(예: "네 좋아요 시작할게요"는 안 걸림)을
    # 포함 여부로 완화했다. 확정 단어도 처음도 다시도 아니면 기존 그대로 처음 화면으로.
    if is_home_word(norm) or "처음" in norm:
        print(f"[RECIPE_CONFIRM] 분기=처음/홈단어 -> reset_to_start()", flush=True)
        st.session_state.chat_log.append(("user", text))
        reset_to_start()
    elif "다시" in norm:
        print(f"[RECIPE_CONFIRM] 분기=다시 -> 같은 화면 재생", flush=True)
        # 2026-08-26 재요청 — "다음 페이지로 안 넘어가면 기록 안 함"으로 한 번 뺐다가,
        # 사용자가 "내 발화가 성공하면 기록에 남겨야 한다"로 재확인해 되돌림(dispatch.py
        # 의 "재청취" 처리와 같은 이유) — "다시"도 정상 인식된 확정 발화라 기록한다.
        st.session_state.chat_log.append(("user", text))
        st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
        st.rerun()
    # 2026-08-28 추가 — 아래 확정어(응/네/좋/다음/그래/시작/진행/할래) "부분매칭"이
    # 내는 오탐을 먼저 걸러낸다(리뷰에서 지적된 케이스): "안 좋아"→"좋", "시작하기
    # 싫어"→"시작", "네가 알려준 거 말고"→"네", "등록할래"→"할래" 가 전부 조리 시작으로
    # 새던 문제. handle_register_dish_name()이 이미 쓰는 것과 같은 "부정어를 확정어보다
    # 먼저 검사" 패턴이다.
    elif any(word in norm for word in ("아니", "싫", "말고", "별로", "취소", "안 좋", "안좋", "안 할", "안할", "안 해", "안해", "안 돼", "안돼")):
        print(f"[RECIPE_CONFIRM] 분기=부정어 -> reset_to_start()", flush=True)
        st.session_state.chat_log.append(("user", text))
        reset_to_start()
    elif "등록" in norm:
        print(f"[RECIPE_CONFIRM] 분기=등록 -> register_dish_name", flush=True)
        # "이거 말고 등록할래" 등 — 현재 뜬 레시피가 아니라 새 레시피 등록 의도.
        # dispatch.py::process_utterance()의 _REGISTER_WORD 처리와 같은 목적지.
        st.session_state.chat_log.append(("user", "등록"))
        st.session_state.pending_dish_name = None
        goto("register_dish_name")
    # 2026-08-24 — "좋아"를 "좋"(어근)으로 완화. 실측: "좋아"라고 말했는데 STT가
    # "좋다고?"로 인식하면서 "좋아"가 부분 문자열로도 안 걸려 화면이 안 넘어간 사례
    # 확인됨 — "좋"만 확인하면 좋아/좋아요/좋다/좋네/좋다고 전부 커버된다.
    # 2026-08-24 재요청 — "진행"/"알려줘"/"부탁"도 확정 단어로 추가. 이 세 단어가
    # 없으면 "레시피 알려줘"/"진행해줘"/"부탁해" 같은 자연스러운 확정 발화가 어느
    # 분기에도 안 걸려서 화면이 조용히 멈춘 것처럼 보이는 리포트로 확인됨.
    # 2026-08-26 재요청 — "할래"도 확정 단어로 추가("이걸로 할래" 등). 이 화면은
    # 이미 위 세 분기(처음/다시/확정 단어) 외 나머지 발화는 전부 무시하도록 설계돼
    # 있어서(바로 아래 "확정 단어도 처음도 다시도 아니면... 아무 일도 안 하고 이
    # 화면에 그대로 머문다" 주석 참고), 지정 안 된 단어를 추가로 막을 필요 없이
    # 이 튜플에 새 단어를 더하기만 하면 된다.
    #
    # 2026-08-26(같은 날 밤) 실사용 재현 보고 — "냉장찌개 알려줘"(recipe_confirm에
    # 이미 "김치찌개"가 떠 있는 상태에서, 전혀 다른/존재하지도 않는 요리를 말함)가
    # "알려줘"라는 부분 문자열 하나 때문에 확정으로 오판돼 김치찌개 조리가 그대로
    # 시작돼버렸다("돼지고기와 새우젓을 손질해주세요" 1단계가 곧장 나옴). "알려줘"/
    # "부탁"은 "OO 레시피 알려줘"처럼 사실상 모든 요리명 조회 문장에 흔히 붙는
    # 범용 어미라 이 화면(요리명 하나를 특정해서 확정 여부만 묻는 화면)에서 확정
    # 단어로 쓰기엔 너무 헐겁다 — 이 화면은 "다른 레시피 찾을래요" 버튼/처음 화면
    # 재검색으로만 요리를 바꿀 수 있다는 원칙과도 어긋난다(다른 요리를 부르는
    # 발화가 여기서 엉뚱하게 확정으로 먹혀버리면 안 됨). 두 단어를 목록에서 뺀다 —
    # 남은 단어들(응/네/좋/다음/그래/시작/진행/할래)은 요리명 뒤에 자연스럽게 안
    # 붙는 짧은 확정 표현이라 같은 위험이 없다.
    elif (
        any(word in norm for word in ("응", "네", "좋", "다음", "그래", "시작", "진행", "할래"))
        or norm.lower() == "next"
    ):
        print(f"[RECIPE_CONFIRM] 분기=확정단어 -> cooking_step (step 1)", flush=True)
        st.session_state.chat_log.append(("user", text))
        st.session_state.pipeline_session["step_number"] = 1
        # register_steps의 "네, 저장할게요"와 같은 이유(2026-08-22 리포트) — 여기서
        # speak()가 그리는 재생바는 바로 다음 줄 goto()의 st.rerun()에 곧장 지워져서
        # "떴다가 사라지는" 화면 깜빡임만 만든다. 도착 화면(cooking_step)이 같은
        # 음성을 캐시에서 다시 찾아 들려주므로(render_step_card()) hidden=True로
        # 화면 없는 자동재생만 하고, 실제로 들리는 소리는 도착 화면 쪽에 맡긴다.
        if view["steps"]:
            first_step = view["steps"][0]
            # 2026-09-01 — step["text"]는 [TERM:용어] 태그가 남은 원본이라(term_dict.py/
            # pipeline.py 참고) TTS로 읽기 전에 resolve_for_tts()로 설명 문장까지 풀어준다.
            speak(
                resolve_for_tts(first_step["text"]),
                recipe_id=view["recipe_id"],
                step_number=first_step.get("step_number", 1),
                hidden=True,
            )
        else:
            speak("1단계 정보를 찾지 못했어요.", hidden=True)
        goto("cooking_step")
    # 2026-08-23 재요청으로 변경 — 확정 단어("응"/"네"/"좋아"/"다음")도 "처음"도 "다시"도
    # 아닌 그 외 발화는 전부 무시한다(else 분기 자체를 없앰). 예전엔 이럴 때 처음
    # 화면으로 돌려보냈지만, 이제는 아무 일도 안 하고 이 화면(recipe_confirm)에 그대로
    # 머문다 — 사용자가 다시 확정 단어로 말해볼 수 있게. "다른 레시피 찾을래요" 버튼은
    # 그대로 남아있어 처음으로 가고 싶으면 그걸로 가면 된다.
    #
    # 2026-08-25 추가 — dispatch.py의 "미분류" 분기와 같은 이유(그쪽 주석 참고) — 위
    # 세 분기(처음/다시/확정 단어) 다 goto() 또는 st.rerun()으로 화면을 다시 그리며
    # listen()을 재호출해 마이크 드레인 루프를 이어가는데, 이 마지막 무시 케이스만
    # rerun 없이 그냥 끝나서 그 순간부터 프레임이 안 비워져 "Queue overflow"로
    # 이어졌다. 화면은 그대로 두고 rerun만 걸어서 드레인을 이어지게 한다.
    else:
        print(f"[RECIPE_CONFIRM] 분기=무시(아무 단어도 매칭 안 됨) -> 화면 그대로, rerun만", flush=True)
        st.rerun()


def screen_cooking_step() -> None:
    refresh_recipe_view()
    view = st.session_state.recipe_view
    session = st.session_state.pipeline_session
    if not view or not view["steps"]:
        goto("start")
        return

    total = len(view["steps"])
    step_number = min(session.get("step_number", 1), total)
    current = view["steps"][step_number - 1]

    # 사용자가 지금 단계를 보고/듣고 있는 동안 남은 단계 음성을 전부 순서대로 미리
    # 합성해둔다 — prefetch_remaining_steps_audio() 정의부 주석 참고(2026-08-22,
    # TTS 체감 속도 개선. "1페이지를 보는 동안 2/3/4페이지가 눈에 안 보이지만 계속
    # 만들어지게" 요청).
    prefetch_remaining_steps_audio(view, step_number)

    render_badge(f'{view["dish_name"]} · {step_number} / {total} 단계')

    # 2026-08-28 추가 — "1단계예요, 이전 단계가 없어요." 같은 1회성 안내(dispatch.py의
    # no_previous 분기)는 조리 단계 자체의 오디오가 아니라서 아래 render_step_card()가
    # 재생을 못 맡는다 — 이 화면엔 start()/recipe_confirm()과 달리 "도착 화면이 대화
    # 기록의 마지막 안내를 다시 찾아 들려주는" 로직이 아예 없어서, hidden=True로
    # 캐싱만 해두고 아무도 재생을 안 하는 버그였다(실측 리포트). 같은 패턴으로 여기서
    # 재생한다 — 조리 단계 오디오(_audio_replay_nonce)와 같은 rerun에서 동시에
    # 재생되면 겹쳐 들리므로 반드시 별도 nonce(_cooking_notice_nonce, dispatch.py
    # 주석 참고)를 쓴다. 이 화면은 chat_log를 비우지 않는데(render_chat()으로 계속
    # 표시해야 해서), 정상적인 단계 진행(다음/이전/다시)의 마지막 ai 메시지는 조리
    # 단계 텍스트 자체라 _common_audio_path() 캐시가 없어 _render_cached_speech()가
    # 조용히 no-op한다(voice_io.py 문서 참고) — 그래서 이 안내문 케이스만 골라 재생되고
    # 정상 단계 진행엔 부작용이 없다.
    #
    # 2026-08-28 수정 — 이 슬롯을 조건부로(캐시 있을 때만) 그리면 screen_cooking_step
    # 컨테이너의 직계 자식 개수가 rerun마다 달라진다("다시" 후엔 no-op라 0개, "이전"(1단계)
    # 후엔 안내 st.html 1개) — 이게 정확히 app.py::main() 주석이 설명하는 Streamlit#8360
    # stale-widget 트리거다. 실측: "다시" -> "이전" 순서에서 안내 엘리먼트가 새로 생기며
    # 아래 스텝 카드/재생바가 한 칸 밀려 통째로 리마운트되고, _audio_replay_nonce가 안
    # 바뀌었는데도 1단계 음성이 다시 재생돼 안내와 겹쳐 들렸다(음성 2개). fallback_buttons()
    # 의 이전/다시/다음 행도 같은 이유로 잔상 중복됐다. 고정 key 컨테이너로 감싸서 안내
    # 유무와 무관하게 항상 한 칸만 차지하게 해 자식 개수를 고정한다 — 안이 비어도 슬롯은
    # 유지되므로 스텝 카드 위치가 안 밀린다.
    with st.container(key="cs_notice_audio_slot"):
        chat_log = st.session_state.chat_log
        if chat_log and chat_log[-1][0] == "ai":
            _render_cached_speech(chat_log[-1][1], nonce=st.session_state.get("_cooking_notice_nonce", 0))

    # 2026-08-21: speak()가 만드는 재생 위젯은 그 직후 goto()의 st.rerun()으로 화면이
    # 바로 새로고침되면서 같이 사라진다 — speak() 안에서 렌더링한 건 "그 rerun 전까지만"
    # 유효하다. 그래서 이 화면(cooking_step) 자체가 매번 다시 그려질 때도 캐시된 오디오를
    # 직접 찾아서 render_step_card()에 넘겨야 실제로 화면에 남아있는 재생바가 된다
    # (speak()가 쓰는 것과 같은 ui/assets/audio/<recipe_id>/<step:02d>.wav 캐시 경로).
    cached_audio_path = _AUDIO_DIR / str(view["recipe_id"]) / f"{step_number:02d}.wav"
    # 2026-09-01 — 화면 자막용은 태그를 설명 없이 걷어내는 resolve_for_display()를 거친다
    # (theme.py::render_step_card() 자체는 안 건드림 — resolve는 항상 호출부 책임).
    display_text = resolve_for_display(current["text"])
    if cached_audio_path.exists():
        nav_target = render_step_card(
            total,
            step_number,
            display_text,
            audio_path=cached_audio_path,
            audio_nonce=st.session_state.get("_audio_replay_nonce", 0),
        )
    else:
        nav_target = render_step_card(total, step_number, display_text)

    # 2026-08-21: 점을 눌러 그 단계로 바로 이동하거나 화살표로 이전/다음 단계로 넘어간
    # 경우 - render_step_card()는 표시만 하고 실제 상태 전환은 여기서 한다(theme.py는
    # orchestration을 몰라서). [이전][다음] 버튼(fallback_buttons)이 manual_fallback()으로
    # 하는 것과 같은 효과(세션 갱신 + 음성 재생 + 재생 nonce 증가)를 낸다 - 단, 점 클릭은
    # 임의의 단계로 바로 건너뛸 수 있어야 해서 manual_fallback()(상대 이동만 지원)
    # 대신 view["steps"]에서 바로 읽는다(get_precomputed_steps()로 이미 전체를
    # 가져와서 recipe_view에 캐싱돼 있어 추가 조회가 필요 없다).
    if nav_target is not None:
        if nav_target > total:
            # 마지막 단계에서 다음 화살표를 누른 경우(theme.py render_step_card() 참고,
            # 2026-08-22 요청) — view["steps"]에 없는 단계라 인덱싱하면 IndexError가 나므로
            # 여기서 걸러서 완료 화면으로 보낸다. speak()는 hidden=True — 도착 화면
            # (cooking_complete)이 _render_cached_speech()로 이 문구를 다시 찾아 들려준다.
            speak(COOKING_COMPLETE_MESSAGE, hidden=True)
            goto("cooking_complete")
            return
        session["step_number"] = nav_target
        st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
        target_step = view["steps"][nav_target - 1]
        # 2026-08-22 리포트 — 여기서 그리는 재생바도 recipe_confirm과 같은 이유로 goto()의
        # rerun에 곧장 지워져 "떴다 사라짐" 깜빡임만 남긴다. 도착 화면이 render_step_card()로
        # 같은 단계 오디오를 캐시에서 다시 들려주므로 hidden=True로 화면 없는 자동재생만 한다.
        speak(
            resolve_for_tts(target_step["text"]),
            recipe_id=view["recipe_id"],
            step_number=target_step.get("step_number", nav_target),
            hidden=True,
        )
        goto("cooking_step")

    st.markdown("**오늘의 재료**")
    render_chips(_ingredients_to_chips(view["ingredients_raw"]))

    if st.session_state.chat_log:
        # 2026-08-26 재요청 — 최근 4개(2턴)만 보여주던 창을 없애고 전체 대화 기록을
        # 다 보여준다. 미분류 발화를 안 남기는 로직(process_utterance() 참고)으로 바꾼
        # 뒤로 슬롯이 전부 의미있는 내용으로만 차서, 1단계처럼 앞쪽 내용이 몇 번의
        # "다음"만으로 창 밖으로 밀려나가는 게 더 눈에 띄었다는 지적.
        render_chat(st.session_state.chat_log)

    _mic_ready = mic_is_playing()
    render_mic_bar(
        "듣는 중" if _mic_ready else "마이크 연결 중...",
        '"이전" · "다시" · "다음"',
        listening=_mic_ready,
    )

    # 2026-08-25 — listen() 호출은 app.py::main()이 화면별 key 컨테이너 밖에서 직접
    # 부르고(cooking.py 상단 주석 참고), 잡힌 텍스트를 process_utterance()로 그대로
    # 넘긴다 — 이 화면은 별도 핸들러 없이 process_utterance()를 그대로 쓴다.
    fallback_buttons("cooking_step")


def screen_cooking_complete() -> None:
    """마지막 단계까지 다 왔을 때 보여주는 완료 화면(2026-08-22 요청) — 이전엔 "마지막
    단계까지 다 왔어요"를 음성으로만 안내하고 cooking_step 화면에 그대로 머물러서, 요리가
    끝났다는 게 화면으로는 드러나지 않았다. register_steps -> screen_complete()와 같은
    패턴: 전환 직전(dispatch.py)에서 COOKING_COMPLETE_MESSAGE를 hidden=True로 미리
    합성/캐싱해두고, 여기서 _render_cached_speech()로 같은 캐시를 다시 찾아 들려준다.
    """
    dish_name = (st.session_state.recipe_view or {}).get("dish_name") or "레시피"
    # 2026-09-02 실측 리포트 — 이 화면 아래쪽 "처음 화면으로" 버튼(432줄)은 이미
    # reset_to_start()를 쓰는데 이 위쪽 back-link만 goto("start")를 직접 불러서
    # _tts_mute_until 등이 안 지워진 채 start로 넘어가는 불일치가 있었다(마이크가
    # "듣고 있어요"로는 보이는데 프레임이 무음 처리되는 버그, voice_io._mic_muted()/
    # dispatch.reset_to_start() 문서 참고) — 통일한다.
    if render_back_link("처음으로"):
        reset_to_start()

    render_spacer()
    st.markdown(f'<div class="ce-lead-icon positive">{ICON_CHECK_CIRCLE}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="ce-center"><h1>요리가 완성됐어요!</h1>'
        f"<p>{dish_name}, 수고하셨어요.</p></div>",
        unsafe_allow_html=True,
    )
    # 2026-08-25 리포트 실측 확인 — "처음"으로 이 화면을 벗어나 start로 넘어간 직후, 방금
    # 그린 완료 멘트 오디오가 브라우저에서 처음부터 다시 재생되는 문제. "이 완료 화면에
    # 진입한 뒤 정확히 한 번만 재생"을 세션 플래그로 파이썬 쪽에서 명시적으로 강제한다.
    if not st.session_state.get("_cooking_complete_audio_played"):
        _render_cached_speech(COOKING_COMPLETE_MESSAGE)
        st.session_state["_cooking_complete_audio_played"] = True
    render_spacer()

    # 2026-08-25 — listen() 호출은 app.py::main()이 화면별 key 컨테이너 밖에서 직접 부른다.
    # "처음"이라고 말하면 process_utterance()가 맨 앞에서 걸러내 reset_to_start()로 처리한다.
    if st.button("처음 화면으로", type="primary", use_container_width=True):
        reset_to_start()
