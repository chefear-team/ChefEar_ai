"""ChefEar 발화 처리(핵심 디스패처) — src/app.py에서 분리(2026-08-22, 화면 컴포넌트화).

start/cooking_step/unclassified 화면이 공유한다.
"""
from __future__ import annotations

import re
import threading
import time

import streamlit as st

from orchestration import gpu_worker_pool
from orchestration.db import get_client
from orchestration.pipeline import manual_fallback
from orchestration.term_dict import resolve_for_tts
from ui.recipe_view import _fetch_recipe_view, _view_cache_fresh, refresh_recipe_view
from ui.session import _DEFAULT_PIPELINE_SESSION, get_owner_id, goto
from ui.voice_io import _close_loading_overlay, _drain_mic_while, speak

# cooking_step에서 "다음"으로 마지막 단계를 넘어가면(advance_step()이 step=None을
# 돌려줌, orchestration/pipeline.py 참고) 안내만 하고 같은 화면에 머무르는 대신 별도
# 완료 화면(cooking_complete)으로 보낸다(2026-08-22 요청 — "요리가 완성됐어요!" 화면).
# screens/cooking.py의 screen_cooking_complete()가 _render_cached_speech()로 이
# 문구를 다시 찾아 들려줘야 해서 문구 자체를 여기(더 아래 계층)에 두고 화면 쪽에서
# import해 쓴다(screens -> dispatch 의존 방향, ui/README.md 참고).
COOKING_COMPLETE_MESSAGE = "요리가 완성됐어요! 수고하셨어요."

# 2026-08-23 추가 — 상시 마이크가 초기 화면(start) 말고는 어디서도 안 끊기게 되면서
# ("처음으로 돌아가고 싶다"는 요청도 화면을 안 옮긴 채 음성만으로 처리해야 함), "처음"류
# 발화를 classify_intent()/LLM 파이프라인에 태우지 않고 바로 잡아낸다 — 이 파이프라인은
# "조회/진행/재청취/이전/등록" 같은 요리 도메인 의도만 다루도록 만들어져 있어서 "처음"을
# 넣어봐야 미분류나 엉뚱한 의도로 샐 위험이 있고, "처음으로 돌아가기"는 애초에 의도 분류가
# 필요 없을 만큼 명확한 명령이라 굳이 그 비용(임베딩 유사도 계산 + LLM 호출)을 들일
# 필요도 없다. 화면마다 있던 "처음 화면으로" 버튼(cooking.py screen_cooking_complete 등)과
# 똑같이 pipeline_session/chat_log/recipe_view/pending_dish_name을 초기화한다.
_HOME_WORDS = {
    "처음", "처음으로", "처음화면", "처음 화면", "처음 화면으로",
    "메인", "메인 화면", "홈",
    # 2026-08-25 추가 — 사용자가 실제로 쓰는 리셋 단어가 "초기"였는데(원 리포트: "'초기'라는
    # 단어를 들으면 A 화면으로 돌아가야 한다"), 이 집합엔 "처음" 계열만 있고 "초기"가 없어서
    # is_home_word()가 매번 False를 돌려주고 있었다 — process_utterance()가 이걸 홈 단축으로
    # 못 잡고 classify_intent()/LLM 파이프라인으로 흘려보내 "초기"라고 말해도 반응이 없거나
    # 엉뚱하게 처리되는 버그였다(화면 전환 잔상과는 별개 원인).
    "초기", "초기화면", "초기 화면", "초기화",
}

# 2026-08-24 추가 — "등록"이라는 단어가 들어가면 곧장 등록 화면으로 보내라는 요청.
# extract_intent_llm()(로컬 LLM)이 이미 "등록하고 싶다"는 의도를 판단하지만, LLM
# 판단을 거치지 않고도 이 단어 하나만으로 확정할 수 있는 가장 명확한 신호라 is_home_word()와
# 같은 자리(파이프라인 진입 전)에서 먼저 잡는다.
_REGISTER_WORD = "등록"

# 2026-08-28 — 요리명 조회 캐시(_recipe_lookup_cache / _recipe_view_cache)의 TTL.
# 예전엔 "만개레시피 실데이터는 세션 도중 안 바뀐다"는 전제로 무기한 유지했는데, 이제
# 관리자 승인/삭제 워크플로우가 생겨서 user_custom 레시피는 세션 도중 바뀔 수 있다
# (승인 취소/삭제 시 캐시된 사용자는 계속 옛 레시피로 조리). staleness를 5분으로 묶는다.
_LOOKUP_CACHE_TTL_S = 300

# 2026-08-26 요청 — 대화 기록(render_chat())의 "나: ..." 줄에 STT가 인식한 문장을
# 그대로 보여주면, 같은 의도라도 사람마다 표현이 제각각이라("다음으로 넘어가주세요"/
# "음 다음으로 좀"/"다음 단계는?") 화면이 장황해진다는 지적 — 순수 명령형 의도(진행/
# 재청취/이전/취소/등록)는 실제로 뭘 말했든 그 의도에 대응하는 단어 하나로만 표시한다.
# 새 단어를 지어내지 않고, fallback_buttons()의 버튼 이름("이전"/"다시"/"다음")과
# orchestration/pipeline.py::_DIRECTION_BY_INTENT가 이미 쓰는 값을 그대로 재사용한다.
# "조회"는 요리명처럼 발화마다 실제 내용이 달라 정보 손실이 생기므로 이 축약
# 대상에서 뺀다(process_utterance() 아래 각 분기 참고) — 원문(정제된 텍스트)을
# 그대로 보여준다.
_INTENT_DISPLAY_LABEL = {"진행": "다음", "재청취": "다시", "이전": "이전", "등록": "등록"}


def _normalize_for_lookup(text: str) -> str:
    """세션 요리명 조회 캐시(_recipe_lookup_cache)의 키 정규화 — extract_intent_llm()이
    LLM에 넣기 전 하는 것과 같은 처리(끝 문장부호 제거 + 공백 전부 제거)에 소문자화만
    더했다. "된장찌개", "된장찌개?", "된장 찌개 " 가 같은 키가 되게 해서, 같은 메뉴를
    표현만 살짝 바꿔 다시 말해도 캐시에 맞게 한다. 자유발화 문장 전체("된장찌개 어떻게
    만들어")는 여기서 요리명만 뽑지 않으므로 그 형태 그대로가 키가 된다 — 그래도
    사용자가 시연 중 같은 문장을 반복하는 흔한 패턴은 그대로 캐시된다."""
    return re.sub(r"\s+", "", text.strip().rstrip("?!.,~ ").lower())


def is_home_word(text: str) -> bool:
    """recipe_confirm/register_intro/register_dish_name처럼 classify_intent()를 안 거치고
    자기 화면 안에서 직접 몇 단어만 확인하는 화면들도 이걸로 "처음" 발화를 똑같이 잡아낼
    수 있게 공개 함수로 둔다.

    2026-08-24 수정 — "처음으로"라고 말했는데 main이 아니라 등록 페이지로 가버리는
    버그 실측 확인. 예전엔 정규화한 발화 전체가 _HOME_WORDS 중 하나와 "정확히" 같아야만
    인정했는데, STT 결과엔 조사/군더더기가 자주 붙는다("어 처음으로 가주세요" 등) — 그러면
    이 함수가 False를 돌려줘서 process_utterance() 맨 위의 조기 처리를 놓치고, 그 발화가
    그대로 classify_intent()/LLM 파이프라인까지 흘러간다. "처음"은 그 파이프라인이 아는
    의도가 아니라서 대개 "미분류"로 떨어지고, dispatch.py의 미분류 분기가 등록 유도
    화면(register_intro)으로 보내버려서 정확히 이 증상(처음으로 말했는데 등록 화면으로
    이동)이 나온다. recipe_confirm 화면의 "처음"/"다시" 로컬 처리가 이미 포함(in) 방식으로
    바뀐 것과 똑같이, 여기도 전체 일치 대신 포함 여부로 완화한다.
    """
    norm = text.strip().rstrip("?!. ")
    return any(word in norm for word in _HOME_WORDS)


def reset_to_start() -> None:
    """"처음 화면으로" 버튼들(cooking.py/register.py)과 동일한 초기화 — 진행 중이던
    레시피/등록/대화 기록을 전부 비우고 start로 보낸다."""
    st.session_state.pipeline_session = dict(_DEFAULT_PIPELINE_SESSION)
    st.session_state.chat_log = []
    st.session_state.recipe_view = None
    st.session_state.pending_dish_name = None
    goto("start")


def listen_background_only(key_prefix: str, *, cancel_target: str) -> None:
    """register_ingredients/register_steps처럼 이미 목적이 뚜렷한 텍스트 폼(재료/순서
    추가칸)을 쓰는 화면용(2026-08-23 추가) — 상시 마이크 연결은 계속 유지하되("start
    화면 말고는 안 끊기게 해달라"는 요청) 자유 발화를 그대로 재료/순서 항목으로 등록해버리면
    안 되므로, "취소"/"처음" 같은 소수의 안전한 단어에만 반응하고 나머지는 무시한다 —
    이 화면들의 진짜 입력 수단은 여전히 화면 자체의 텍스트 폼이다."""
    from ui.voice_io import listen

    text = listen(key_prefix, show_text_fallback=False)
    if not text:
        return
    norm = text.strip().rstrip("?!. ")
    if is_home_word(norm):
        reset_to_start()
    elif norm in ("취소", "취소할래요", "취소해줘"):
        goto(cancel_target)
    else:
        # 2026-08-25 추가 — dispatch.py의 "미분류" 분기와 같은 이유(그쪽 주석 참고) —
        # 위 두 분기 다 goto()로 화면을 다시 그리며 listen()을 재호출해 마이크 드레인
        # 루프를 이어가는데, 이 무시 케이스(재료/순서 자유 발화 등)만 rerun 없이 끝나서
        # 그 순간부터 프레임이 안 비워져 "Queue overflow"로 이어졌다.
        st.rerun()


def _is_admin_trigger(text: str) -> bool:
    """"관리자 페이지 접근할게요" 류 발화 감지 — 관리자 페이지로 이동만 시키는 트리거
    (docs/specs/admin_voice_2fa.md 옵션 A). 실제 인증은 도착한 관리자 페이지의 랜덤
    단어 챌린지 + 화자검증이 한다 — 이 문구 자체는 아무 권한도 안 주므로 노출/복제돼도
    무방하다. is_home_word()처럼 조사/군더더기에 강하게 "포함" 매칭한다."""
    norm = re.sub(r"\s+", "", text.strip())
    if "관리자" not in norm:
        return False
    return any(k in norm for k in ("페이지", "화면", "권한", "모드", "콘솔", "접근"))


def process_utterance(text: str) -> None:
    # 2026-09-01 — 진단 로그(실측 리포트 추적용, 요청에 따라 process_utterance()
    # 전체 분기에 빠짐없이 추가). 이 줄이 매 발화 처리의 진입점이라 [PERF]/
    # [STT_CONF_DEBUG]/[GOTO]와 시간순으로 나란히 놓고 보면 "어떤 발화가 어떤
    # 분기를 타서 어디로 갔는지"를 끝까지 추적할 수 있다.
    print(f"[DISPATCH] process_utterance 진입: text={text!r} screen={st.session_state.get('screen')!r}", flush=True)
    if is_home_word(text):
        print(f"[DISPATCH] 분기=is_home_word -> reset_to_start()", flush=True)
        reset_to_start()
        return

    # 2026-08-28 — 관리자 페이지 진입 트리거(옵션 A). is_home_word()와 같은 자리에서
    # classify_intent()/LLM을 안 거치고 문자열로 바로 잡는다. 세션 플래그만 세우고
    # rerun하면 app.py::main()이 관리자 st.Page로 switch_page 한다(그 Page는
    # _admin_via_voice 플래그가 있으면 등록됨). 조리 중에도 허용한다(관리자가 급히
    # 승인/삭제할 상황).
    if _is_admin_trigger(text):
        print(f"[DISPATCH] 분기=admin_trigger -> 관리자 페이지 전환", flush=True)
        st.session_state["_admin_via_voice"] = True
        st.rerun()
        return

    # 2026-08-26 재요청 — "모든 채팅을 다 넣지 말고, 임베딩 유사도에 맞는 대화가
    # 나왔을 때[만] 텍스트 등록되게" — 예전엔 여기서 무조건 기록해서, classify_intent()가
    # 결국 "미분류"로 끝나는 잡담/잡음(마이크 오인식 등)까지 대화 기록(render_chat())에
    # "나: ...." 로 그대로 남아 지저분했다. 이제 chat_log.append()는 실제로 뭔가
    # 처리(등록 확정 또는 classify_intent()의 embedding 유사도가 실제 의도와 매칭)된
    # 경우에만 각 분기 안에서 개별적으로 호출한다 — 아래 _REGISTER_WORD 분기 시작
    # 부분과, "미분류" 분기 *다음*(= 실제 의도로 확정된 지점) 두 곳.

    # 2026-08-27 수정 — "레시피 도중에 이상한 말이 들어오면 로그인 후 이용해주세요가
    # 뜬다" 실측 리포트. 원인: 이 _REGISTER_WORD 빠른 경로엔 조리 중(context_recipe_id
    # 있음) 가드가 없었다 — 아래 wants_register 분기(2026-08-26에 이미 이 정확히 같은
    # 증상으로 `and not session.get("current_recipe_id")`가 추가됨, 그쪽 문서 참고)와
    # classify_intent()의 "등록"("등록은 첫 페이지 아니면 의미없는 문구다" 원칙, 그쪽
    # 문서 참고)은 이미 막혀있었는데, 이 문자열 매칭 경로만 빠져서 조리 중 STT가
    # "등록"이 섞인 아무 말이나 오인식해도 무조건 로그인 게이트가 발동했다. 나머지
    # 세 경로와 똑같이 조리 중이면 이 분기 자체를 건너뛰고 그냥 재청취로 넘어간다.
    if _REGISTER_WORD in text and not st.session_state.pipeline_session.get("current_recipe_id"):
        print(f"[DISPATCH] 분기=등록단어(빠른경로) -> register_dish_name", flush=True)
        st.session_state.chat_log.append(("user", _INTENT_DISPLAY_LABEL["등록"]))
        # is_home_word()와 같은 자리 — classify_intent()/LLM까지 갈 것도 없이 "등록"
        # 단어 하나로 확정되는 명령이라 바로 처리한다. wants_register 분기(아래)와
        # 같은 이유로 register_intro(확인 화면)는 건너뛰고 register_dish_name으로
        # 바로 간다 — 사용자가 "등록"이라고 직접 말한 건 시스템의 짐작이 아니다.
        # 2026-08-27 — 로그인 개념 자체가 없어져서(계정/쿠키 시스템 제거) 게이트도
        # 같이 없앴다 — 로그인 여부와 무관하게 항상 등록 화면으로 바로 간다.
        st.session_state.pending_dish_name = None
        goto("register_dish_name")
        return

    session = st.session_state.pipeline_session
    client = get_client()
    # 2026-09-02 — docs/specs/private_recipe_visibility.md: 조회 결과가 이제 조회자
    # (owner_id)에 따라 달라지므로(같은 발화라도 A/B가 서로 다른 user_custom을 봄),
    # 아래 요리명 조회 캐시 키에도 섞어 넣는다 — 안 그러면 A로 조회 성공한 캐시를 같은
    # 탭에서 로그아웃 후 로그인한 B가 그대로 재사용해 A의 비공개 레시피를 보게 된다.
    owner_id = get_owner_id()

    # 2026-08-28 — 세션 요리명 조회 캐시(_recipe_lookup_cache). 조리 중이 아닐 때(start
    # 화면 등) 이번 세션에서 이미 조회에 성공한 발화를 그대로 다시 말하면, 아래
    # extract_intent_llm()(로컬 LLM, GPU 1~3초) + handle_utterance() 안의 classify_intent()
    # (임베딩) + select_standard_recipe()/refresh_recipe_view()(Supabase 왕복 여러 번)를
    # 전부 건너뛰고 캐시된 recipe_id로 곧장 recipe_confirm으로 보낸다 — "같은 메뉴를
    # 반복해서 물어보는데 매번 처음부터 다 다시 처리하는 것 같다(DB 들렀다 음성 만드는
    # 느낌)"는 실측 리포트 대응. recipe_view도 recipe_id별 세션 캐시(_recipe_view_cache,
    # ui/recipe_view.py)가 받쳐줘서 DB 왕복 0회. 조리 중(current_recipe_id 있음)에는 이
    # 캐시를 안 탄다 — 그땐 "다시"/"다음" 같은 진행 명령이라 조회 캐시가 방해만 된다.
    # 캐시는 reset_to_start()가 안 지운다. staleness는 _LOOKUP_CACHE_TTL_S(5분)로 묶는다.
    lookup_key = f"{owner_id}:{_normalize_for_lookup(text)}"
    lookup_cache = st.session_state.setdefault("_recipe_lookup_cache", {})
    _hit = lookup_cache.get(lookup_key)
    _hit_fresh = _hit is not None and (time.monotonic() - _hit.get("_ts", 0.0)) < _LOOKUP_CACHE_TTL_S
    # [PERF] — 이 캐시는 "조리 중 아님" + "같은 발화를 이 세션에서 이미 조회한 적
    # 있음" 두 조건이 다 맞을 때만 히트한다(위 문서 참고) — 처음 묻는 요리명이나
    # 진행/재청취 명령("다시"/"다음")은 이 캐시 자체를 안 타는 게 정상 설계다.
    print(
        f"[PERF] recipe_lookup_cache "
        f"{'HIT' if (_hit_fresh and not session.get('current_recipe_id')) else 'MISS'} key={lookup_key!r}",
        flush=True,
    )
    if not session.get("current_recipe_id") and _hit_fresh:
        hit = _hit
        print(f"[DISPATCH] 분기=조회(캐시히트) dish_name={hit['dish_name']!r} -> recipe_confirm", flush=True)
        st.session_state.chat_log.append(("user", hit["dish_name"]))
        session["current_recipe_id"] = hit["recipe_id"]
        session["step_number"] = 1
        refresh_recipe_view(force=True)  # _recipe_view_cache가 DB 왕복을 막아준다
        speak(
            f'{hit["dish_name"]}, 조회수 1위 표준 레시피예요. 이걸로 시작할까요?',
            hidden=True,
        )
        goto("recipe_confirm")
        return

    # 2026-08-27 추가 — "다시"라고 말할 때마다 뭔가 다시 조회/생성하는 느낌이라는
    # 실측 리포트. 원인: advance_step()(orchestration/pipeline.py)이 step_number가
    # 그대로인 "다시"에도 매번 get_current_step()으로 Supabase에 새로 물어보고
    # 있었다 — 오디오 파일 자체는 speak()가 경로 존재 여부로 이미 재합성을
    # 건너뛰지만, 그 앞단의 이 불필요한 DB 왕복 자체가 체감 지연의 실제 원인이었다.
    # 이 화면(recipe_view)이 이미 레시피 조회 시 전체 조리순서를 한 번에 다
    # 받아둔 캐시(ui/recipe_view.py::refresh_recipe_view())가 있으므로, 그걸
    # handle_utterance()에 그대로 넘겨 advance_step()이 DB 대신 이 목록에서
    # 찾게 한다. recipe_view가 아직 이번 session의 current_recipe_id와 안
    # 맞을 수 있는 아주 짧은 틈(예: 방금 새 레시피를 찾은 직후)엔 안전하게
    # None으로 둬서 advance_step()이 기존 DB 조회로 폴백하게 한다 — 배경
    # 스레드(_compute)는 st.session_state를 직접 못 건드리므로(다른 st.* 호출과
    # 같은 이유, 아래 threading.Thread 참고) 스레드를 띄우기 전인 지금(메인
    # 스레드) 미리 읽어 클로저로 넘긴다.
    view = st.session_state.get("recipe_view")
    steps_cache = (
        view["steps"]
        if view and view.get("recipe_id") == session.get("current_recipe_id") and view.get("steps")
        else None
    )
    # 2026-08-28 (A) — 배경 스레드가 조회 성공 시 recipe_view도 미리 가져올 수 있게
    # _recipe_view_cache 참조를 지금(메인 스레드에서) 잡아 넘긴다. dict라 스레드에서 읽기만
    # 하면 안전하고, 실제 쓰기(캐시 채우기)는 이 함수가 결과를 받은 뒤 메인에서 한다.
    view_cache = st.session_state.setdefault("_recipe_view_cache", {})

    # 2026-08-23 — extract_intent_llm()/handle_utterance()를 배경 스레드로 돌리고, 메인
    # 스레드는 그동안 voice_io._drain_mic_while()로 마이크 큐를 계속 비운다. speak()의
    # TTS 합성 구간만 이렇게 고쳤을 땐 재현이 계속됐는데(그 요청은 TTS가 이미 캐싱돼 있어
    # 합성 자체를 안 탄 경우였음), 실측(WEBRTC_DEBUG 로그)해보니 이 구간 — classify_intent()가
    # 쓰는 sentence-transformers 임베딩 모델의 최초 GPU 로딩(세션당 1회, 몇 초) + Supabase
    # DB 조회(순차 HTTP 요청 여러 번) — 도 TTS만큼 길게 아무도 안 비우는 블로킹 구간이라
    # 브라우저가 똑같이 연결을 끊었다("DTLS shutdown by remote party"). extract_intent_llm/
    # handle_utterance 둘 다 st.* API를 안 써서(순수 함수, DB client는 인자로 받음) 배경
    # 스레드에서 안전하게 돌릴 수 있다 — session_state 쓰기/goto()(st.rerun())는 이 함수가
    # 결과를 받은 뒤 메인 스레드에서 그대로 처리한다.
    job: dict = {
        "done": False,
        "llm_result": None,
        "result": None,
        "value_error": False,
        "network_error": False,
        "recipe_view": None,  # 2026-08-28 (A) — 조회 성공 시 배경 스레드가 미리 채운다
        "recipe_view_id": None,
    }

    def _compute(job=job) -> None:
        try:
            # 2026-08-26 요청 — "왜 로컬 LLM에 가는거지? 이상한 것들은 로딩이 안 떠야
            # 정상 아닌가?" 실측 확인: extract_intent_llm()의 두 출력(dish_name/
            # wants_register) 다 이미 조리 중(session["current_recipe_id"] 있음)이면
            # 아무데도 안 쓰인다 — dish_name은 "조회" intent가 이제 조리 중엔 절대
            # 안 뜨게 막아놔서(intent_classifier.py::_pick_intent()) 쓰일 데가 없고,
            # wants_register는 True가 나와도 바로 아래 elif 분기가 조리 중이면 무조건
            # 무시한다. 그런데도 "돼지고기"/"참치찌"처럼 아무 명령도 아닌 발화까지 매번
            # 이 로컬 LLM(GPU, 보통 1~3초+)을 불러서 결과를 그냥 버리고 있었다 — 그
            # 사이 로딩 팝업만 뜨고 아무 일도 안 일어나는 게 정확히 이 낭비였다. 조리
            # 중이면 이 호출 자체를 건너뛰고 바로 안전한 기본값으로 채운다 — start
            # 화면(아직 아무 레시피도 안 고른 상태)에서는 여전히 필요해서(요리명 추출/
            # 등록 의도 판단 둘 다 거기선 실제로 쓰임) 그대로 부른다.
            if session.get("current_recipe_id"):
                # 조리 중이면 이 결과가 뭐가 나오든 안 쓰이니(위 문서 참고) 호출 자체를
                # 건너뛴다 — 아래 나머지 로직(handle_utterance() 호출과 그 예외 처리)은
                # 그대로 다 거친다, 이 값만 안전한 기본값으로 채운다.
                job["llm_result"] = {"dish_name": None, "wants_register": False}
            else:
                try:
                    # 2026-08-24 — 원래 _GPU_LOCK(threading.Lock)으로 감쌌던 자리. 2026-09-01 —
                    # gpu_worker_pool의 별도 프로세스로 보내고 그 Future를 기다리는 것으로
                    # 바뀜(voice_io.py 옛 _GPU_LOCK 정의부 주석, gpu_worker_pool.py 문서 참고).
                    # [PERF] 태그는 voice_io.py::_run_stt() 문서 참고 — 전체 왕복 병목
                    # 진단용, 항상 켜둠.
                    _llm_t0 = time.monotonic()
                    job["llm_result"] = gpu_worker_pool.submit_llm_extract(text).result()
                    print(f"[PERF] LLM(extract) {time.monotonic() - _llm_t0:.2f}s", flush=True)
                except Exception as exc:  # noqa: BLE001 — 아래 이유로 여기서만 넓게 잡음
                    # llm/infer.py generate_json() 문서에 "모델 로드/추론 자체가 실패하면
                    # 예외를 그대로 올린다"고 명시돼 있다. 이 GPU 데스크탑은 STT(faster-whisper)
                    # /임베딩(sentence-transformers)/TTS/이 로컬 LLM(EXAONE)이 전부 같은 GPU를
                    # 공유해서 메모리 경합으로 가끔 실패할 수 있는데(2026-08-24 실사용 중
                    # 재현 — STT 인식은 됐는데 그 다음부터 화면이 조용히 멈춤), 여기서 안 잡으면
                    # job["llm_result"]가 None으로 남아 바로 아래 llm_result["dish_name"]에서
                    # TypeError로 메인 스레드가 죽는다(에러 박스가 떴다가 마이크 재연결 rerun에
                    # 덮여 "그냥 멈춘 것처럼" 보였을 가능성이 높음). extract_intent_llm()이 자신의
                    # 다른 실패 케이스(JSON 형식 오류 등)에 이미 쓰는 것과 같은 안전한 기본값으로
                    # 폴백한다 — 모르면 지어내지 않는다는 1.5 원칙과 같은 태도.
                    print(f"[dispatch] extract_intent_llm 실패, 안전한 기본값으로 폴백: {exc!r}")
                    job["llm_result"] = {"dish_name": None, "wants_register": False}
            if job["llm_result"]["wants_register"]:
                return
            try:
                # handle_utterance() -> classify_intent()가 임베딩 모델(GPU)을 씀. 2026-09-01 —
                # gpu_worker_pool 워커 프로세스 안에서 실행되고, client는 안 넘긴다(그 워커
                # 프로세스 자신의 get_client() 싱글턴을 쓰게 함 — gpu_worker_pool.py의
                # _worker_handle_utterance() 문서 참고). 이 함수의 client 인자(위쪽 매개변수)는
                # 더 이상 handle_utterance()로 전달되지 않는다.
                _hu_t0 = time.monotonic()
                job["result"] = gpu_worker_pool.submit_handle_utterance(
                    session,
                    text,
                    dish_name=job["llm_result"]["dish_name"],
                    steps=steps_cache,
                    owner_id=owner_id,
                ).result()
                print(f"[PERF] handle_utterance(intent+DB) {time.monotonic() - _hu_t0:.2f}s", flush=True)
            except ValueError:
                job["value_error"] = True
            except Exception as exc:  # noqa: BLE001 — 2026-08-26 추가, 아래 문서 참고
                # handle_utterance() 내부의 Supabase 조회(client.table(...).execute())가
                # 던지는 네트워크/HTTP 오류(APIError, 타임아웃, 연결 끊김 등, 4xx/5xx 포함)
                # 는 ValueError가 아니라서 위 except가 못 잡았다 — 그러면 이 background
                # 스레드가 여기서 조용히 죽고(daemon 스레드라 프로세스는 안 죽지만 이
                # job["result"]는 None으로 남는다), 메인 스레드가 잠시 뒤 result.get(...)
                # 에서 AttributeError로 크래시한 뒤에야 app.py의 최상위 catch-all이 겨우
                # 받아내는 지저분한 경로였다(실측 확인 — "40x/50x 에러 다 잡고 있나?"
                # 질문 계기). extract_intent_llm()과 같은 패턴(넓게 잡고 안전한 값으로
                # 폴백)으로 여기도 명시적으로 처리한다 — 무슨 예외인지도 콘솔에 남긴다.
                print(f"[dispatch] handle_utterance 실패(네트워크/서버 오류 추정): {exc!r}")
                job["network_error"] = True

            # 2026-08-28 (A) — 조회 성공이면 recipe_view(재료 원문 + 전체 조리순서)도
            # 여기 배경 스레드에서 미리 조회해 job에 담아둔다. 예전엔 메인 스레드가
            # _drain_mic_while() 밖에서(handle_utterance 결과를 받은 뒤) refresh_recipe_view(
            # force=True)로 했는데, 그 Supabase 왕복 2번(recipes by id + recipe_steps by
            # recipe_id, _fetch_recipe_view() 참고) 동안 아무도 get_frames()를 안 불러 마이크
            # 큐가 쌓였다("Queue overflow"). _fetch_recipe_view()는 순수 함수(client in ->
            # dict out, st.* 안 씀)라 스레드에서 안전하고, 이미 이번 세션에서 조회한
            # 레시피면(_recipe_view_cache 히트) DB를 아예 안 탄다.
            res = job["result"]
            if res and res.get("intent") == "조회" and res.get("recipe_id") and "message" not in res:
                rid = res["recipe_id"]
                try:
                    _cv = view_cache.get(rid)
                    job["recipe_view"] = _cv if _view_cache_fresh(_cv) else _fetch_recipe_view(rid, client)
                    job["recipe_view_id"] = rid
                except Exception as exc:  # noqa: BLE001 — 못 가져오면 메인이 refresh_recipe_view()로 폴백
                    print(f"[dispatch] recipe_view 배경 조회 실패(메인에서 재시도): {exc!r}")
        finally:
            job["done"] = True

    threading.Thread(target=_compute, daemon=True).start()
    # 2026-09-01 — "로딩바가 두 번 켜졌다 꺼진다" 리포트 대응. close=False로 팝업을
    # 안 닫고 그대로 돌려받아, 아래 각 분기의 speak() 호출까지 넘겨서 팝업 하나로
    # 이어붙인다(voice_io._drain_mic_while()/_LoadingOverlay 문서 참고). speak()
    # 없이 끝나는 분기(등록 의도, value_error, 미분류/감탄사 등)는 그 자리에서
    # 직접 _close_loading_overlay(overlay)를 불러 닫아야 한다 — 안 그러면 팝업이
    # 화면에 계속 남는다.
    overlay = _drain_mic_while(job, close=False)

    # 2026-09-02 자체 재검토(서브에이전트 리뷰) — 이 지점부터 아래 각 분기의
    # _close_loading_overlay(overlay)/speak(_loading_overlay=overlay) 호출까지
    # 사이에서 예상 못 한 예외(예: result 딕셔너리의 계약 위반, refresh_recipe_view()의
    # 처리 안 된 Supabase 오류 등)가 나면, 그 예외가 각 분기의 마무리 호출을 건너뛰고
    # 그대로 위(app.py::_run_with_error_notice())까지 올라가버려서 overlay(st.empty()
    # 슬롯)가 닫히지 않은 채 남는다. 이 팝업은 화면 전환 잔상 방지용 st.empty() 스왑
    # 구조(app.py::main()의 _screen_slot) *밖*에서 그려지므로, 이 프로젝트가 이미 여러 번
    # 겪은 Streamlit#8360류 잔상 문제에 그대로 노출된다 — try/finally로 어떤 경로로
    # 함수를 벗어나든 반드시 한 번은 닫히게 보장한다. 정상 경로는 각 분기가 이미 명시적으로
    # 닫거나 speak()에 넘겨서 여기 도달할 때 이미 닫혀있는 게 보통이고(overlay.shown이
    # False), _close_loading_overlay()는 그 상태에서 다시 불러도 아무 것도 안 하므로
    # (위 _close_loading_overlay() 문서 참고) 안전하다.
    try:
        llm_result = job["llm_result"]
        dish_name_guess = llm_result["dish_name"]

        print(f"[DISPATCH] LLM 추출 결과: dish_name={dish_name_guess!r} wants_register={llm_result['wants_register']!r}", flush=True)
        if llm_result["wants_register"] and not session.get("current_recipe_id"):
            print(f"[DISPATCH] 분기=wants_register(LLM) -> register_dish_name", flush=True)
            # 2026-08-22 추가 — classify_intent()(임베딩 유사도)가 "등록" 같은 짧은 단일
            # 발화를 "진행"/"이전"과 헷갈려 margin 미충족으로 미분류 처리하는 사례가 실측
            # 확인됐다(기준예문.csv 보강으로 그 구체 사례는 고쳤지만, 임베딩 분류기가 커버
            # 못하는 새 표현은 또 나올 수 있음). classify_intent()를 거치지 않고, LLM이 이미
            # "등록하고 싶다"를 명확히 확인해줬으면 바로 등록으로 보낸다.
            #
            # register_intro(표준 레시피에 없어서 짐작으로 등록을 유도하는 확인 화면)는 안
            # 거친다(2026-08-22 요청) — "등록"이라고 직접 말한 건 시스템의 짐작이 아니라
            # 사용자의 확정된 요청이라 다시 확인받을 필요가 없으므로, register_dish_name
            # (새 레시피 등록 1/3 요리명)으로 바로 보낸다.
            # 2026-08-27 — 로그인 개념 자체가 없어져서 게이트도 같이 없앴다.
            st.session_state.pending_dish_name = dish_name_guess
            # 2026-09-01 — speak() 없이 끝나는 분기라 여기서 직접 팝업을 닫는다(위
            # overlay 문서 참고).
            _close_loading_overlay(overlay)
            goto("register_dish_name")
            return
        # intent_classifier.py의 "등록"(임베딩 매칭)은 context_recipe_id가 있으면(=이미
        # 조리 중) 무시하도록 이미 고쳤는데, 이 LLM 경로(wants_register)는 완전히 별개
        # 판정이라 그 보호를 못 받고 있었다 — 위 if 조건에 `and not session.get("current_recipe_id")`를
        # 추가해서 조리 중엔 이 경로 자체를 안 타게 막았다 — 여기로 떨어지면(조리 중에
        # wants_register가 True) 그냥 무시하고 원래 화면에 머무른다("등록은 첫 페이지 아니면
        # 의미없는 문구다" 원칙, classify_intent() 쪽과 동일).
        elif llm_result["wants_register"]:
            print(f"[DISPATCH] 분기=wants_register(조리중이라 무시) -> 화면 그대로, rerun만", flush=True)
            _close_loading_overlay(overlay)
            st.rerun()
            return

        if job["network_error"]:
            # 2026-08-26 추가 — "40x/50x 에러 다 잡고 있나?" 재요청으로 발견/수정. Supabase
            # 조회(4xx/5xx, 타임아웃, 연결 끊김 등)가 실패한 경우 서비스가 죽는 대신 "알 수
            # 없는 intent" 분기와 같은 안전한 경로(speak+unclassified)로 보낸다 — 그 화면이
            # chat_log의 마지막 ai 메시지를 다시 찾아 들려주므로 hidden=True. unclassified
            # 화면 자체의 고정 문구("잘 이해하지 못했어요")는 이 케이스(실제로는 인식은
            # 됐지만 서버 오류)엔 살짝 안 맞지만, 음성 응답은 정확한 이유를 말해주고 화면
            # 기능(재시도 버튼 등)은 그대로 동작해서 이번엔 이 경로를 재사용한다.
            print(f"[DISPATCH] 분기=network_error -> unclassified", flush=True)
            speak("일시적인 오류가 발생했어요. 잠시 후 다시 이용해 주세요.", hidden=True, _loading_overlay=overlay)
            goto("unclassified")
            return

        if job["value_error"]:
            print(f"[DISPATCH] 분기=value_error(등록 의도인데 registration_step 없음) -> register_dish_name", flush=True)
            # 위 배경 스레드의 _compute() 안에서 handle_utterance()가 ValueError를 던진 경우 —
            # "등록" 의도인데 registration_step 없이 자유발화로 들어온 경우 등. 서비스를
            # 죽이는 대신 신규 등록으로 안전하게 보낸다. classify_intent()가 이미 "등록"으로
            # 확정 분류한 경우라 위 wants_register 분기와 같은 이유로 register_intro(확인
            # 화면)는 안 거치고 바로 register_dish_name으로 보낸다.
            st.session_state.pending_dish_name = dish_name_guess
            # 2026-09-01 — speak() 없이 끝나는 분기라 여기서 직접 팝업을 닫는다(위
            # overlay 문서 참고).
            _close_loading_overlay(overlay)
            goto("register_dish_name")
            return

        result = job["result"]
        intent = result.get("intent")
        print(f"[DISPATCH] classify_intent 결과: intent={intent!r} result={result!r}", flush=True)

        if intent == "미분류" or intent == "감탄사":
            print(f"[DISPATCH] 분기=미분류/감탄사 -> 무시(화면 그대로, rerun만)", flush=True)
            # 2026-08-26 추가 — "감탄사"(감사합니다/아멘/고마워요 등, 기준예문.csv 참고):
            # classify_intent()가 이 실제 매칭시킨 진짜 의도라 "미분류"는 아니지만, 이
            # 발화들은 애초에 아무 명령도 아니라서 처리할 게 없다 — 실측: "감사합니다"가
            # "재청취"(다시 한번요)와 0.65로 헷갈려 다시듣기가 잘못 트리거되는 문제가
            # 있었다(임베딩이 짧고 단순한 문장 구조만 보고 헷갈림, 의미와 무관). THRESHOLD를
            # 올려서 막으려 하면 "좋아"(0.71) 같은 진짜 확정 발화까지 같이 막혀서, 대신
            # 이 표현들을 자기 카테고리로 분리해 자기 자신과 거의 1.0으로 매칭시켜 이기게
            # 하고, 여기서 "미분류"와 완전히 동일하게(화면 전환도 응답도 없이 무시) 처리한다.
            #
            # 문장 패턴 분류(classify_intent)가 기준예문.csv의 어떤 의도와도 못 매칭한
            # 경우 전부 여기로 온다. 2026-08-24 재요청 — 기준예문에 없는 발화는 화면 전환도,
            # 음성 응답도 없이 그냥 무시한다(예전엔 register_intro로 등록을 유도하거나
            # unclassified 화면에서 "못 알아들었다"고 되물었는데, 조회 예문을 크게 넓힌
            # 뒤로는 진짜 잡담/잡음만 여기로 남아서 매번 반응할 필요가 없다는 판단).
            # register_intro/unclassified 화면 자체는 다른 경로(_REGISTER_WORD, "알 수
            # 없는 intent" 방어 분기 등)로 여전히 갈 수 있다.
            #
            # 2026-09-01 — speak() 없이 끝나는 분기라 여기서 직접 팝업을 닫는다(위
            # overlay 문서 참고).
            #
            # 2026-08-25 추가 — 이 분기만 유일하게 goto()(=st.rerun())를 안 불렀다. 다른
            # 모든 분기는 화면을 옮기며 rerun이 걸리고, 그 rerun이 다시 listen()을 호출해
            # _run_mic_loop()의 프레임 드레인 루프가 곧장 이어지는데, 여기는 그냥 return해서
            # 이번 스크립트 실행이 끝나버린다 — 그 순간부터 아무도 get_frames()를 안 불러서
            # (다음 rerun이 우연히 다른 이유로 트리거될 때까지) 마이크 큐가 쌓이기만 하다
            # 넘친다("Queue overflow" 반복 + 그 직후 발화가 씹히는 리포트, 실측 확인 —
            # "여기까지하면"/"좋아?"처럼 margin 미충족으로 미분류 처리된 직후에만 정확히
            # 재현됨). 화면은 그대로 두고 같은 화면으로 rerun만 걸어서 드레인 루프가
            # 끊기지 않게 한다.
            _close_loading_overlay(overlay)
            st.rerun()
            return

        # 2026-08-26 재요청 — "내 발화가 성공하면(=classify_intent()가 실제 의도와
        # 매칭시켜서 뭔가 처리됐으면) 대화 기록에 남겨야 한다." (중간에 "다음 페이지로
        # 안 넘어가면 기록 안 함"으로 더 좁혔다가, 사용자가 "내 기록은 아예 기록 안
        # 한다고?"로 되물어서 원래 기준으로 되돌림 — 아래 각 분기의 "2026-08-26 재요청"
        # 주석 참고.) 여기 도달한 시점(미분류/감탄사를 이미 걸러낸 뒤)은 전부 성공
        # 케이스라, 화면이 실제로 바뀌든(조회/등록 등) 같은 화면에 머물든(다시/이전
        # 단계 없음 등) 상관없이 각 분기 안에서 기록한다 — speak()의 AI 응답 기록은
        # 이 규칙과 별개로 원래부터 항상 그대로 남는다.

        if intent == "조회":
            if "message" in result:  # DISH_NOT_FOUND_MESSAGE 또는 PENDING_MESSAGE
                print(f"[DISPATCH] 분기=조회(실패) message={result['message']!r} -> 현재 화면 유지, rerun만", flush=True)
                # 2026-08-27 — no_match 화면 자체를 없앴다(잔상 문제 다발). 화면 전환
                # 없이 현재 화면(start)에 그대로 머무른 채 안내만 1회 들려준다 — 대화
                # 기록에도 안 남기고(같은 요리를 계속 물어봐도 채팅창이 안 쌓임), 재생을
                # 대신해줄 도착 화면이 없으므로 hidden 없이 직접 들려준다.
                #
                # 2026-08-27 실측 리포트 — 조회 실패 한 번에 "Queue overflow" 반복 발생.
                # goto() 없이 그냥 return하면 이 스크립트 실행이 여기서 끝나버려서, "미분류"
                # 분기가 이미 겪었던 것과 똑같은 문제가 재현된다(그쪽 2026-08-25 주석 참고) —
                # rerun이 안 걸리니 아무도 get_frames()를 안 불러 마이크 큐가 쌓이기만 하다
                # 넘친다. 화면은 그대로 두되(goto 아님) rerun만 걸어서 드레인 루프를 잇는다.
                #
                # 2026-08-28 수정 — 같은 "없는 요리"를 두 번 연속 물으면 두 번째가 완전 무음이던
                # 버그. DISH_NOT_FOUND_MESSAGE/PENDING_MESSAGE는 고정 문구라, screen_start()가
                # _render_cached_speech(msg, nonce=_audio_replay_nonce)로 재생할 때 nonce가
                # 안 바뀌면 브라우저가 "이미 로드된 오디오"로 보고 autoplay를 재실행하지 않는다
                # (screen_start()가 chat_log도 안 그리므로 텍스트 피드백도 없음). nonce를 올려
                # 매번 새로 재생되게 한다.
                st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
                # hidden=True — 도착 화면(현재 화면 그대로, 대개 start)이 _render_cached_speech()로
                # 재생을 맡는다. 여기서 render_audio_player()를 그리면 바로 뒤 st.rerun()에 곧장
                # 지워지는 "떴다 사라짐" 깜빡임만 남는다(이 파일 다른 분기들과 동일 패턴).
                speak(result["message"], hidden=True, _loading_overlay=overlay)
                st.rerun()
                return
            # 2026-08-26 요청 — "제육복근"이라고 잘못 들려도 recipe_search.py::extract_dish_name()
            # 3단계(편집거리, 자모 분해 difflib)가 "제육볶음"으로 보정해서 정상 매칭시키는데,
            # 정작 채팅창엔 보정 전 원문(text)이 그대로 남아서 "AI는 제육볶음이라 답하는데
            # 내 말풍선은 제육복근"이라는 불일치가 생겼다. AI 응답(바로 아래 speak())과
            # 같은 값(result["dish_name"], 실제로 DB에서 찾은 표준 요리명)을 써서 맞춘다.
            print(f"[DISPATCH] 분기=조회(성공) dish_name={result['dish_name']!r} recipe_id={result['recipe_id']!r} -> recipe_confirm", flush=True)
            st.session_state.chat_log.append(("user", result["dish_name"]))
            # 2026-09-01 — 위 "진행"/"재청취"/"이전" 분기와 완전히 같은 원인의 버그.
            # handle_utterance()가 조회 성공 시 session["current_recipe_id"]/["step_number"]를
            # 그 자리에서 직접 바꾸는 방식으로 짜여 있는데(orchestration/pipeline.py
            # 참고), 이 호출이 gpu_worker_pool.submit_handle_utterance(session, ...)로
            # 별도 프로세스에 넘어가서 그 프로세스 안의 pickle된 복사본만 바뀌고 여기
            # 이 session(=st.session_state.pipeline_session)은 안 바뀐다 — 캐시 히트
            # 경로(위 _hit_fresh 분기)는 메인 스레드에서 직접 실행돼 이미 명시적으로
            # 쓰고 있던 것과 같은 이유로, 여기(캐시 미스 = 첫 조회)도 명시적으로 다시
            # 써서 프로세스 경계를 건너 세션에 반영한다.
            session["current_recipe_id"] = result["recipe_id"]
            session["step_number"] = 1
            # 2026-08-28 — 이 발화 -> 이 레시피 매칭을 세션 캐시에 남긴다(위 process_utterance()
            # 상단 lookup_cache 주석 참고). 다음에 같은 발화를 다시 말하면 LLM/임베딩/DB를
            # 전부 건너뛴다. result["recipe_id"]는 handle_utterance()가 방금 DB에서 확정한 값.
            lookup_cache[lookup_key] = {
                "recipe_id": result["recipe_id"],
                "dish_name": result["dish_name"],
                "_ts": time.monotonic(),
            }
            # 2026-08-28 (A) — recipe_view의 DB 왕복은 위 _compute() 배경 스레드가
            # _drain_mic_while() 우산 안에서 이미 끝냈다("Queue overflow" 대응). 그 결과를
            # 그대로 반영하고 세션 캐시도 채운다. 배경 조회가 못 됐으면(스레드 예외 등)
            # 기존대로 메인에서 refresh_recipe_view()로 폴백한다.
            if job["recipe_view"] is not None:
                st.session_state.recipe_view = job["recipe_view"]
                view_cache[job["recipe_view_id"]] = job["recipe_view"]
            else:
                refresh_recipe_view(force=True)
            # 위와 같은 이유 — 도착 화면(recipe_confirm)이 chat_log의 마지막 ai 메시지를
            # _render_cached_speech()로 다시 들려준다.
            speak(
                f'{result["dish_name"]}, 조회수 1위 표준 레시피예요. 이걸로 시작할까요?',
                hidden=True,
                _loading_overlay=overlay,
            )
            goto("recipe_confirm")
            return

        if intent in ("진행", "재청취", "이전"):
            # 2026-09-01 — 실측 리포트("챗박스는 2단계로 정상 표시되는데 화면 카드와
            # 음성은 계속 1단계 그대로") 원인 발견: handle_utterance()(-> advance_step())가
            # session["step_number"]를 "그 자리에서 직접 바꾸는" 방식으로 동작하는데,
            # 2026-09-01 GPU 워커 풀을 멀티프로세스(ProcessPoolExecutor)로 전환하면서 이
            # 호출이 gpu_worker_pool.submit_handle_utterance(session, ...)로 별도
            # *프로세스*에 넘어가게 됐다 — 그 프로세스 안에서 session을 바꿔봐야 pickle된
            # 복사본만 바뀌고, 여기 이 session(=st.session_state.pipeline_session 그 자체)
            # 은 전혀 안 바뀐다. .result()로 돌아오는 건 반환값(result 딕셔너리)뿐이라
            # 챗박스(아래 speak() 텍스트)는 result["step"] 기준이라 맞게 나오는데, 화면
            # 카드/오디오 캐시 경로는 여전히 이 session["step_number"](갱신 안 됨, 1단계
            # 그대로)를 보고 그려져서 어긋났다. advance_step()은 항상 최상위에 "step_number"
            # 를 돌려주므로(orchestration/pipeline.py 문서 참고, no_previous/완료 케이스
            # 포함 전부) 여기서 명시적으로 다시 써서 프로세스 경계를 건너 세션에 반영한다.
            session["step_number"] = result["step_number"]
            step = result.get("step")
            print(
                f"[DISPATCH] 분기={intent} step_number(반영후)={session['step_number']!r} "
                f"no_previous={result.get('no_previous')!r} step_is_none={step is None!r}",
                flush=True,
            )
            if result.get("no_previous"):
                print(f"[DISPATCH]   -> no_previous 안내, cooking_step 유지", flush=True)
                # 2026-08-26 재요청 — "내 발화가 성공하면(=classify_intent()가 실제
                # 의도와 매칭시켰으면) 기록에 남겨야 한다"로 다시 확정. "다음 페이지로
                # 안 넘어가면 기록 안 함"으로 한 번 더 좁혔다가(이전 커밋), 사용자가
                # "내 기록은 아예 기록 안 한다고?"로 되물어서 원래 기준(성공 매칭 여부)
                # 으로 되돌린다 — 여기(이전 단계 없음)도 "이전"이 정상적으로 인식·처리된
                # 결과라 기록한다.
                # 2026-08-26 요청 — 표시는 원문 대신 _INTENT_DISPLAY_LABEL(위 정의 참고)의
                # 짧은 단어로. 아래 두 곳(elif/else)도 동일.
                st.session_state.chat_log.append(("user", _INTENT_DISPLAY_LABEL[intent]))
                # 2026-08-28 수정 — "'이전'이라고 해도 안내 음성이 안 들린다" 실측 리포트.
                # 원인: hidden=True가 빠져서 여기서 그린 재생 위젯이 바로 아래 goto()의
                # rerun에 곧장 지워졌다(이 파일 다른 분기들이 이미 겪고 고친 것과 같은
                # 패턴인데 이 분기만 빠져있었음) — 게다가 screen_cooking_step()엔
                # start()/recipe_confirm()과 달리 "도착 화면이 chat_log의 마지막 안내를
                # 다시 찾아 들려주는" 로직 자체가 없어서, hidden=True로만 고치면 이번엔
                # 아예 아무 데서도 재생을 안 하게 된다. 아래에서 새로 추가한 전용 nonce
                # (_cooking_notice_nonce)를 올려서 screen_cooking_step()이 이 안내를
                # 재생하게 한다 — 기존 _audio_replay_nonce를 같이 올리면 화면에 그대로
                # 남아있는 조리 단계 카드의 캐시 오디오까지 덩달아 다시 재생되어 이 안내
                # 음성과 겹쳐 들리므로(위 else 분기 주석 참고) 반드시 별도 변수를 쓴다.
                st.session_state["_cooking_notice_nonce"] = st.session_state.get("_cooking_notice_nonce", 0) + 1
                speak("1단계예요, 이전 단계가 없어요.", hidden=True, _loading_overlay=overlay)
                goto("cooking_step")
            elif step is None:
                print(f"[DISPATCH]   -> 마지막 단계 이후 -> cooking_complete", flush=True)
                st.session_state.chat_log.append(("user", _INTENT_DISPLAY_LABEL[intent]))
                # 마지막 단계에서 "다음" -> advance_step()이 더 이상 존재하지 않는 단계를
                # 찾다 step=None을 돌려준 경우(2026-08-22 요청) — 안내만 하고 cooking_step에
                # 머무르는 대신 완료 화면으로 보낸다. screen_cooking_complete()가 이 문구를
                # _render_cached_speech()로 다시 찾아 들려주므로 여기서는 hidden=True로 화면
                # 없는 자동재생만 하고, 실제로 들리는 소리는 도착 화면 쪽에 맡긴다(recipe_confirm/
                # register_steps와 같은 패턴).
                # 2026-08-25 — 이번에 새로 도착하는 완료 화면이 한 번은 재생할 수 있게
                # 플래그를 여기서 리셋한다(screen_cooking_complete()의 "화면 진입당 한 번만
                # 재생" 가드 참고 — 이 플래그가 없으면 그 가드가 매번 True로 막혀버린다).
                st.session_state["_cooking_complete_audio_played"] = False
                speak(COOKING_COMPLETE_MESSAGE, hidden=True, _loading_overlay=overlay)
                goto("cooking_complete")
            else:
                print(f"[DISPATCH]   -> 정상 진행, step_number={step.get('step_number')!r} -> cooking_step", flush=True)
                # 2026-08-26 재요청 — 위 no_previous 분기와 같은 이유로 되돌림: "재청취"
                # (다시)도 classify_intent()가 정상적으로 매칭시킨 성공 케이스라 기록한다
                # (한때 "다음 페이지로 안 넘어가면 제외"로 뺐다가 사용자 재확인으로 복구).
                st.session_state.chat_log.append(("user", _INTENT_DISPLAY_LABEL[intent]))
                # "다시"는 같은 파일을 다시 재생하는 거라 오디오 콘텐츠 자체가 안 바뀌어서
                # nonce 없이는 iframe이 안 바뀐 걸로 보고 autoplay가 재실행되지 않는다. "다음"/
                # "이전"도 이전에 방문했던 단계로 돌아갈 때(예: 2단계->1단계->2단계) 같은 문제가
                # 재현될 수 있어 실제 단계 오디오를 다시 들려줄 때만 nonce를 올려 항상 새로
                # 로드되게 한다(theme.py render_audio_player() 참고).
                #
                # 2026-08-22 리포트: 이 nonce 증가를 "1단계예요..."/"마지막 단계까지..." 안내
                # 분기 앞에서 공통으로 하고 있었는데, 그 두 경우엔 현재 화면의 단계 번호가
                # 안 바뀐다 — 그런데도 nonce를 올리면 goto()의 rerun 직후 screen_cooking_step()이
                # 화면에 그대로 남아있는 그 단계 카드의 캐시 오디오를 "새로 로드된 것"으로 보고
                # 다시 자동재생해서, 방금 speak()로 들려준 안내 음성과 동시에 겹쳐 들렸다. 실제
                # 단계 오디오를 다시 보여주는 이 분기에서만 nonce를 올려서 막는다.
                #
                # 2026-08-22 추가 리포트: 여기서 그리는 speak()의 재생바도 recipe_confirm과
                # 같은 이유로 goto()의 rerun에 곧장 지워져 "떴다 사라짐" 깜빡임만 남긴다 —
                # 도착 화면(cooking_step)이 render_step_card()로 같은 단계 오디오를 캐시에서
                # 다시 찾아 들려주므로 hidden=True로 화면 없는 자동재생만 한다.
                st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
                # 2026-09-01 — step["text"]는 [TERM:용어] 태그가 남은 원본이다(term_dict.py
                # 참고). 이 분기가 "다음"/"다시"/"이전" 음성 발화의 실제 처리 경로라(process_utterance()
                # -> classify_intent()), resolve_for_tts()를 안 거치면 TTS와 채팅창 양쪽에
                # "[TERM:...]" 문자열이 그대로 노출된다 — 실측 리포트로 발견됨(cooking.py의
                # speak() 호출부만 고치고 여기를 놓쳤었음: 그쪽은 화면 진입 시 1회성 speak()
                # 뿐이고, 실제 음성 탐색은 전부 이 경로를 탄다).
                speak(
                    resolve_for_tts(step["text"]),
                    recipe_id=session.get("current_recipe_id"),
                    step_number=step.get("step_number"),
                    hidden=True,
                    _loading_overlay=overlay,
                )
                goto("cooking_step")
            return

        if intent == "등록":
            print(f"[DISPATCH] 분기=등록(분류) -> register_intro", flush=True)
            st.session_state.chat_log.append(("user", _INTENT_DISPLAY_LABEL[intent]))
            prompt = result.get("prompt") or result.get("summary") or result.get("message")
            if prompt:
                speak(prompt, _loading_overlay=overlay)
            else:
                # 2026-09-01 — speak()를 안 부르는 경우라 여기서 직접 팝업을 닫는다(위
                # overlay 문서 참고).
                _close_loading_overlay(overlay)
            goto("register_intro")
            return

        # 알 수 없는 intent(방어적 처리) — 서비스가 죽는 대신 fallback으로.
        print(f"[DISPATCH] 분기=알수없는intent({intent!r}, 방어적처리) -> unclassified", flush=True)
        st.session_state.chat_log.append(("user", text))
        # 위와 같은 이유(2026-08-22) — unclassified가 chat_log의 마지막 ai 메시지를 다시
        # 들려주므로 hidden=True.
        speak("죄송해요, 잘 처리하지 못했어요. 다시 한 번 말씀해주시겠어요?", hidden=True, _loading_overlay=overlay)
        goto("unclassified")
    finally:
        _close_loading_overlay(overlay)


def fallback_buttons(key_prefix: str) -> None:
    """FR-16 — 음성 인식/의도분류 실패 시 수동 [이전][다시][다음]. 항상 노출한다."""
    session = st.session_state.pipeline_session
    if not session.get("current_recipe_id"):
        return
    client = get_client()
    # process_utterance()의 steps_cache와 같은 이유(위 2026-08-27 주석 참고) — 버튼
    # 경로는 배경 스레드가 아니라 여기서 바로 st.session_state를 읽어도 안전하다.
    view = st.session_state.get("recipe_view")
    steps_cache = (
        view["steps"]
        if view and view.get("recipe_id") == session.get("current_recipe_id") and view.get("steps")
        else None
    )
    # 2026-08-28 — 캡션 + 버튼 3개를 화면 전용 key 컨테이너로 감싼다. cooking_step/
    # unclassified에서 "처음" 등으로 다른 화면(start)으로 넘어갈 때, 이 캡션·버튼이
    # 새 화면 컨테이너 밑으로 재부모화돼 start 하단에 잔상으로 남는 게 실측 확인됐다
    # (Streamlit#8360, app.py::main() 주석 참고). theme.py::_SINGLE_OWNER_WIDGET_KEYS
    # (ruleSingleOwnerWidgets)가 이 key로 "지금 화면이 소유 화면이 아니면 숨김"을
    # 구조적으로(텍스트 무관) 처리하게 하려면 고정 key가 필요하다 — 개별 버튼은
    # ruleFallbackButtons()가 st-key-<owner>_-- 로 이미 잡지만, st.caption()은 key도
    # 컨테이너도 없어서 어느 규칙으로도 안 잡혔다(실측: "처음" 후 start 하단에 캡션만 남음).
    with st.container(key=f"{key_prefix}_fallback"):
        st.caption("음성이 잘 안 될 땐 아래 버튼으로도 진행할 수 있어요.")
        c1, c2, c3 = st.columns(3)
        for col, button in ((c1, "이전"), (c2, "다시"), (c3, "다음")):
            with col:
                if st.button(button, key=f"{key_prefix}_{button}", use_container_width=True):
                    result = manual_fallback(session, button, client=client, steps=steps_cache)
                    print(
                        f"[DISPATCH] fallback_buttons: button={button!r} -> "
                        f"step_number={session.get('step_number')!r} result={result!r}",
                        flush=True,
                    )
                    if result.get("no_previous"):
                        # 2026-08-28 — process_utterance()의 같은 분기와 동일한 수정(그쪽
                        # 주석 참고): hidden=True + 전용 nonce(_cooking_notice_nonce)로
                        # screen_cooking_step()이 이 안내를 재생하게 한다.
                        st.session_state["_cooking_notice_nonce"] = (
                            st.session_state.get("_cooking_notice_nonce", 0) + 1
                        )
                        speak("1단계예요, 이전 단계가 없어요.", hidden=True)
                        goto("cooking_step")
                    elif result.get("step") is None:
                        # process_utterance()의 같은 분기와 동일한 이유(2026-08-22) — 마지막
                        # 단계에서 "다음" 버튼을 누르면 완료 화면으로 보낸다.
                        # 2026-08-25 — process_utterance()의 같은 분기와 동일한 이유로 재생
                        # 플래그를 리셋한다(screen_cooking_complete() 가드 참고).
                        st.session_state["_cooking_complete_audio_played"] = False
                        speak(COOKING_COMPLETE_MESSAGE, hidden=True)
                        goto("cooking_complete")
                    else:
                        # process_utterance()의 같은 분기와 동일한 이유(2026-08-22) — 실제 단계
                        # 오디오를 다시 보여줄 때만 nonce를 올린다. "1단계예요..." 안내는 화면의
                        # 단계가 안 바뀌는데 nonce만 올리면, rerun 후 그 자리에 남아있는 단계
                        # 카드의 캐시 오디오가 다시 자동재생되면서 방금 들려준 안내 음성과
                        # 겹쳐 들린다. speak() 자체도 hidden=True — 도착 화면(cooking_step)이
                        # render_step_card()로 같은 오디오를 캐시에서 다시 들려주므로, 여기서
                        # 그리는 재생바는 rerun에 곧장 지워지는 "떴다 사라짐" 깜빡임만 남긴다.
                        st.session_state["_audio_replay_nonce"] = st.session_state.get("_audio_replay_nonce", 0) + 1
                        # 2026-09-01 — 위 process_utterance()의 같은 분기와 동일한 이유로
                        # resolve_for_tts() 적용(버튼 경로도 [TERM:...] 원본을 그대로
                        # 넘기고 있었음).
                        speak(
                            resolve_for_tts(result["step"]["text"]),
                            recipe_id=session.get("current_recipe_id"),
                            step_number=result["step"].get("step_number"),
                            hidden=True,
                        )
                        goto("cooking_step")
