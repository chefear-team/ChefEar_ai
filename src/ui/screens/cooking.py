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
    render_typewriter_message,
)
from ui.dispatch import COOKING_COMPLETE_MESSAGE, fallback_buttons, is_home_word, process_utterance, reset_to_start
from ui.recipe_view import _ingredients_to_chips, refresh_recipe_view
from ui.session import goto
from ui.voice_io import _AUDIO_DIR, _render_cached_speech, listen, mic_is_playing, prefetch_remaining_steps_audio, speak


def screen_start() -> None:
    render_spacer()
    st.markdown(
        '<div class="ce-center"><h1>무엇을 만들고 싶으세요?</h1>'
        "<p>숫자 메뉴 없이, 하고 싶은 말을 편하게 그대로 말씀해주세요.</p>"
        '<p style="color:var(--text-faint); font-size:13.5px;">예: "된장찌개 어떻게 만들어?"</p></div>',
        unsafe_allow_html=True,
    )
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
    text = listen("start", show_mic=False)
    if text:
        process_utterance(text)

    # 2026-08-21: 위쪽에만 render_spacer()가 있고 아래쪽엔 없어서, block-container의
    # flex:1 남는 공간이 전부 위에만 쌓여 콘텐츠가 화면 아래쪽으로 밀렸다 - 뷰포트가
    # 높을수록(세로로 긴 화면비) 남는 공간 자체가 커져서 그만큼 더 크게 벌어져 보였다.
    # 다른 화면들(register_intro, complete, login 등)처럼 아래에도 render_spacer()를
    # 넣어 남는 공간을 위아래로 똑같이 나눠 화면 비율과 무관하게 수직 중앙 정렬되게 한다.
    render_spacer()


def screen_recipe_confirm() -> None:
    view = st.session_state.recipe_view
    if not view:
        goto("start")
        return

    render_badge("조회수 1위 표준 레시피 자동 선택 · 되묻지 않음 (FR-05)")
    # 2026-08-22 재요청: 이전 대화 기록(사용자 질문 등)은 아예 안 보여주고, 마지막 AI
    # 메시지를 챗봇 말풍선 없이 요리명/문장 두 줄로 줄바꿈해서(요리명은 크게) 타자기처럼
    # 한 글자씩 나타나는 순수 텍스트로 보여준다. 세 줄 문구는 dispatch.process_utterance()의
    # 조회 확인 메시지(`speak(f'{dish_name}, 조회수 1위 표준 레시피예요. 이걸로
    # 시작할까요?')`)와 내용이 같아야 한다 — 그쪽은 TTS로 자연스럽게 읽히려고 한 문장
    # 그대로 두고, 화면 표시만 여기서 줄 단위로 다시 나눈다.
    chat_log = st.session_state.chat_log
    if chat_log and chat_log[-1][0] == "ai":
        # dispatch.py가 이 화면으로 넘어오기 직전 speak(..., hidden=True)로 미리 합성/캐싱만
        # 해둔 문구를 여기서 다시 찾아 들려준다(2026-08-22 리포트 — 화면 전환 중 이전
        # 화면 하단에 재생바가 "떴다 사라짐" 깜빡이는 문제, no_match/unclassified와 같은 패턴).
        # nonce(2026-08-23) — 아래 "다시" 처리가 이 값을 올려서 같은 문구를 한 번 더 듣게 한다.
        _render_cached_speech(chat_log[-1][1], nonce=st.session_state.get("_audio_replay_nonce", 0))
        # render_spacer()로 뱃지와의 사이를 벌려서, 텍스트 블록이 위쪽에 바짝 붙지 않고
        # 아래쪽 "재료 미리보기" 사이 빈 공간의 세로 중앙쯤에 오게 한다(2026-08-22
        # 스크린샷 지적 — screen_start() 등 다른 화면의 render_spacer() 패턴과 동일).
        render_spacer()
        render_typewriter_message(
            [view["dish_name"], "조회수 1위 표준 레시피예요.", "이걸로 시작할까요?"],
            key=f"recipe_confirm:{chat_log[-1][1]}",
        )

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

    # "응"(긍정) 확인은 classify_intent()가 처리하지 않는다(의도적 제외,
    # tests/integration_test.md 기록) — 이 화면 안에서만 문자열로 직접 우회 처리.
    # cooking_step/register_intro/register_dish_name과 같은 이유(2026-08-21/22) — 바로 위
    # render_mic_bar()가 이미 "듣는 중" 펄스 애니메이션으로 마이크가 켜져 있음을 보여주고
    # 있어서, listen()이 따로 그리는 실제 녹음 위젯("말씀해주세요" 박스)까지 있으면 마이크
    # 안내가 중복돼 보인다는 지적(2026-08-22)으로 show_mic=False로 꺼둔다(완전히 지우진
    # 않음, 나중에 되돌릴 수 있게). 텍스트 입력 대체 경로는 그대로 남아있다.
    text = listen("recipe_confirm", show_mic=False)
    if text:
        # 2026-08-24 추가 — 이 화면은 process_utterance()를 안 거치고 직접 문자열을
        # 비교하는 구조라(바로 아래 이유 참고), process_utterance() 맨 앞에서 하던
        # chat_log 기록(`st.session_state.chat_log.append(("user", text))`)도 안 타고
        # 있었다 — 그래서 "응"/"좋아" 같은 확정 발화가 대화 기록에서 통째로 빠지는
        # 실측 리포트("내가 했던 대화 내용이 없다")로 확인, 여기서 직접 기록해준다.
        st.session_state.chat_log.append(("user", text))
        norm = text.strip().rstrip("?!. ")
        # 2026-08-22 원래 의도로 되돌림 — 이 화면은 원래 "확정 단어 목록 -> 진행,
        # 그 외 전부 -> 처음 화면"이라는 단순한 이분법으로 설계됐었는데, 그동안
        # else 분기가 process_utterance()(classify_intent() 전체 파이프라인)로
        # 넘어가게 돼 있었다. "조회수 1위 표준 레시피 자동 선택 · 되묻지 않음(FR-05)"
        # 화면이라 여기서 진행/이전/재료대체 같은 다른 의도까지 판단할 필요가 없고,
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
            reset_to_start()
        elif "다시" in norm:
            st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
            st.rerun()
        # 2026-08-24 — "좋아"를 "좋"(어근)으로 완화. 실측: "좋아"라고 말했는데 STT가
        # "좋다고?"로 인식하면서 "좋아"가 부분 문자열로도 안 걸려 화면이 안 넘어간 사례
        # 확인됨 — "좋"만 확인하면 좋아/좋아요/좋다/좋네/좋다고 전부 커버된다.
        elif any(word in norm for word in ("응", "네", "좋", "다음", "그래", "시작")) or norm.lower() == "next":
            st.session_state.pipeline_session["step_number"] = 1
            # register_steps의 "네, 저장할게요"와 같은 이유(2026-08-22 리포트) — 여기서
            # speak()가 그리는 재생바는 바로 다음 줄 goto()의 st.rerun()에 곧장 지워져서
            # "떴다가 사라지는" 화면 깜빡임만 만든다. 도착 화면(cooking_step)이 같은
            # 음성을 캐시에서 다시 찾아 들려주므로(render_step_card()) hidden=True로
            # 화면 없는 자동재생만 하고, 실제로 들리는 소리는 도착 화면 쪽에 맡긴다.
            if view["steps"]:
                first_step = view["steps"][0]
                speak(
                    first_step["text"],
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

    if st.button("다른 레시피 찾을래요", use_container_width=True):
        goto("start")


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

    # 2026-08-21: speak()가 만드는 재생 위젯은 그 직후 goto()의 st.rerun()으로 화면이
    # 바로 새로고침되면서 같이 사라진다 — speak() 안에서 렌더링한 건 "그 rerun 전까지만"
    # 유효하다. 그래서 이 화면(cooking_step) 자체가 매번 다시 그려질 때도 캐시된 오디오를
    # 직접 찾아서 render_step_card()에 넘겨야 실제로 화면에 남아있는 재생바가 된다
    # (speak()가 쓰는 것과 같은 ui/assets/audio/<recipe_id>/<step:02d>.wav 캐시 경로).
    cached_audio_path = _AUDIO_DIR / str(view["recipe_id"]) / f"{step_number:02d}.wav"
    if cached_audio_path.exists():
        nav_target = render_step_card(
            total,
            step_number,
            current["text"],
            audio_path=cached_audio_path,
            audio_nonce=st.session_state.get("_audio_replay_nonce", 0),
        )
    else:
        nav_target = render_step_card(total, step_number, current["text"])

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
            target_step["text"],
            recipe_id=view["recipe_id"],
            step_number=target_step.get("step_number", nav_target),
            hidden=True,
        )
        goto("cooking_step")

    st.markdown("**오늘의 재료**")
    render_chips(_ingredients_to_chips(view["ingredients_raw"]))

    if st.session_state.chat_log:
        render_chat(st.session_state.chat_log[-4:])

    _mic_ready = mic_is_playing()
    render_mic_bar(
        "듣는 중" if _mic_ready else "마이크 연결 중...",
        '"이전" · "다시" · "다음"',
        listening=_mic_ready,
    )

    # register_intro/register_dish_name과 같은 이유(2026-08-21) — 바로 위 render_mic_bar()가
    # 이미 "듣는 중" 펄스 애니메이션으로 마이크가 켜져 있음을 보여주고 있어서, listen()이
    # 따로 그리는 실제 녹음 위젯("말씀해주세요" 박스)까지 있으면 마이크 안내가 중복돼
    # 보인다는 지적(2026-08-22)으로 여기도 show_mic=False로 꺼둔다(완전히 지우진 않음,
    # 나중에 되돌릴 수 있게). 텍스트 입력 대체 경로는 그대로 남아있다.
    text = listen("cooking_step", show_mic=False)
    if text:
        process_utterance(text)

    fallback_buttons("cooking_step")


def screen_cooking_complete() -> None:
    """마지막 단계까지 다 왔을 때 보여주는 완료 화면(2026-08-22 요청) — 이전엔 "마지막
    단계까지 다 왔어요"를 음성으로만 안내하고 cooking_step 화면에 그대로 머물러서, 요리가
    끝났다는 게 화면으로는 드러나지 않았다. register_steps -> screen_complete()와 같은
    패턴: 전환 직전(dispatch.py)에서 COOKING_COMPLETE_MESSAGE를 hidden=True로 미리
    합성/캐싱해두고, 여기서 _render_cached_speech()로 같은 캐시를 다시 찾아 들려준다.
    """
    dish_name = (st.session_state.recipe_view or {}).get("dish_name") or "레시피"
    if render_back_link("처음으로"):
        goto("start")

    render_spacer()
    st.markdown(f'<div class="ce-lead-icon positive">{ICON_CHECK_CIRCLE}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="ce-center"><h1>요리가 완성됐어요!</h1>'
        f"<p>{dish_name}, 수고하셨어요.</p></div>",
        unsafe_allow_html=True,
    )
    _render_cached_speech(COOKING_COMPLETE_MESSAGE)
    render_spacer()

    # 2026-08-23 요청 — 상시 마이크가 start 화면 말고는 끊기지 않아야 해서, 이 완료
    # 화면도 계속 듣는다("처음"이라고 말하면 아래 버튼과 동일하게 reset_to_start()로
    # 처리됨 — dispatch.process_utterance()가 맨 앞에서 먼저 걸러냄).
    text = listen("cooking_complete", show_mic=False)
    if text:
        process_utterance(text)

    if st.button("처음 화면으로", type="primary", use_container_width=True):
        reset_to_start()
