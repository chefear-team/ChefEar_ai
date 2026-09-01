"""7.3/7.6 — 표준 레시피 선정, 발화 속 요리명 추출.

이 파일의 함수들은 전부 "DB에서 조건에 맞는 레시피를 찾는다"는 공통점이
있는데, 못 찾았을 때 절대로 답을 지어내지 않는다(1.5 원칙: 서비스 실행 중
LLM 생성 fallback 없음). 못 찾으면 그냥 "없다"고 정직하게 답한다.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from functools import lru_cache

from orchestration.db import get_client

# extract_dish_name()의 3단계 중 편집거리 유사도(3번) 판정 기준값. intent_classifier.py의
# THRESHOLD와 같은 성격 — 실측 튜닝 전 임시값이다. 0.75로 하면 "부대찌개"/"부대찌게"(글자
# 하나 차이, 실제 SequenceMatcher 유사도 0.75)가 걸러져버려서, 이 프로젝트가 다루려는
# "STT가 글자 하나 잘못 들은" 케이스를 못 잡는다. 그래서 0.7로 여유를 뒀다.
FUZZY_CUTOFF = 0.7


@lru_cache(maxsize=8)
def _all_dish_names(client) -> list[str]:
    """recipes 테이블에 있는 모든 요리명을 중복 없이 가져온다.

    Supabase(PostgREST)는 select() 결과를 기본적으로 최대 1000행까지만 돌려준다
    (실측 확인: 60,196건 중 1000건만 반환됨, 2026-08-20) — 필터 없이 그냥
    .execute()만 부르면 나머지 59,196건은 조용히 빠져버려서, 하필 뒤쪽에 있는
    요리명(예: "부대찌개")은 매칭 후보에서 아예 사라지는 실제 버그가 있었다.
    그래서 .range()로 1000행씩 페이지를 넘겨가며 끝까지 다 끌어온다(마지막
    페이지가 1000행보다 적게 오면 그게 끝이라는 뜻).

    같은 요리명이 api_standard/user_custom 여러 행으로 존재할 수 있어서 set으로
    중복을 지운다 — extract_dish_name()이 편집거리 비교를 돌 때 같은 이름을
    여러 번 비교하지 않게 하려는 것뿐, 정확도엔 영향 없다.

    @lru_cache(client 객체별로 캐시): 실측 결과 60,196건을 페이지네이션으로 다
    끌어오는 데 12~18초가 걸려서(2026-08-20), 발화 하나마다 매번 이걸 반복하면
    "다음"/"이전" 같은 흔한 명령까지 다 그만큼 느려진다. client 객체(진짜
    Supabase 클라이언트든 테스트용 FakeSupabaseClient든)를 캐시 키로 써서, 같은
    클라이언트로 다시 부르면 두 번째부터는 즉시 반환한다 — 테스트는 매번 새
    FakeSupabaseClient를 만들어 쓰므로 캐시가 테스트끼리 섞이지 않는다.
    단점: 이 캐시가 살아있는 동안(같은 프로세스, 같은 client 객체) 새로 등록되거나
    load_data.py로 재적재된 요리명은 안 잡힌다 — 필요해지면 _all_dish_names.
    cache_clear()로 비우거나, 더 정교한 무효화 전략을 나중에 붙여야 한다.
    """
    names: set[str] = set()
    page_size = 1000
    start = 0
    while True:
        res = client.table("recipes").select("dish_name").range(start, start + page_size - 1).execute()
        rows = res.data
        names.update(row["dish_name"] for row in rows if row.get("dish_name"))
        if len(rows) < page_size:
            break
        start += page_size
    return list(names)


def _decompose_hangul(text: str) -> str:
    """음절 단위 한글을 초성/중성/종성 자모로 풀어헤친다(유니코드 NFD 정규화 — 한글
    완성형 음절은 초성+중성(+종성) 조합으로 알고리즘적으로 합성되므로, 표준 라이브러리
    unicodedata만으로 새 의존성 없이 분해된다).

    extract_dish_name() 3단계(편집거리 유사도)가 difflib을 음절 그대로 비교하면,
    "찌"(ㅉ+ㅣ)/"치"(ㅊ+ㅣ)처럼 자음 하나(된소리/거센소리)만 다르거나 "개"(ㄱ+ㅐ)/
    "게"(ㄱ+ㅔ)처럼 모음 하나(애/에, 실제 발화에서 거의 구분 안 되는 경우가 흔함)만
    다른 음절을 "완전히 다른 글자"로 취급해버린다. 실측: STT가 "된장찌개"를
    "된장치게"로 오인식한 실사례에서 음절 단위 SequenceMatcher.ratio()는 0.5로
    FUZZY_CUTOFF(0.7) 미달이라 매칭 자체가 실패했는데, 자모 단위로 풀어서 비교하면
    0.8로 올라가 정상적으로 "된장찌개"에 매칭된다(2026-08-23 실측 확인). 기존에
    이 커트오프를 통과하던 "부대찌개"/"부대찌게" 케이스는 자모 단위에서도 여전히
    통과하고(0.75 -> 0.875), 완전히 다른 요리("된장찌개"/"감자조림")는 자모
    단위에서도 여전히 낮게 나와(0.3) 오탐이 늘지 않음을 같이 확인했다.
    """
    return unicodedata.normalize("NFD", text)


def _collapse_stt_repetition(text: str) -> str:
    """faster-whisper(beam_size=1, 그리디 디코딩)가 짧은 음절 조각을 연속으로 반복
    생성하는 디코딩 아티팩트를 접는다 — 실측: "된장찌개"->"된장찌장찌개"("장찌"가 2회
    연속), "가지무침"->"가지무칔무칔무칔"("무칔"이 3회 연속) 둘 다 이 패턴.

    **이 함수 자체를 STT 결과에 바로 적용하지 않는다** — "샤브샤브"/"타르타르"/
    "토마토"(내부에 "토마"가 2번 이어짐)처럼 2~3글자가 실제로 정당하게 반복되는
    진짜 요리명이 60,282건 중 153건(0.26%) 있어서, 텍스트를 무조건 바꾸면 이런
    진짜 이름을 깨뜨린다(실측 확인, 2026-08-26). 그래서 extract_dish_name()에서
    "접은 버전도 후보 하나로 추가"하는 용도로만 쓴다 — 원본이 이미 실제 이름과
    맞으면(exact/substring/fuzzy 어느 단계로든) candidates에 원본이 이미 들어있고,
    max(candidates, key=len)이 더 긴 원본을 우선 채택하므로 접은 버전이 끼어들 수
    없다. 원본이 DB에 없는 진짜 디코딩 아티팩트일 때만 이 접은 버전이 유일한
    매칭 후보가 되어 구제한다.
    """
    return re.sub(r"(.{2,3})\1+", r"\1", text)


@lru_cache(maxsize=8)
def _decomposed_name_map(client) -> dict[str, str]:
    """자모 분해된 요리명 -> 원본 요리명 매핑. _all_dish_names()와 같은 client별
    캐시 전략을 그대로 따른다(같은 클라이언트로 반복 호출 시 재계산 없음, 캐시 무효화
    한계도 동일 — _all_dish_names() docstring 참고). 서로 다른 두 요리명이 자모까지
    완전히 같아지는 경우는 곧 원본 문자열이 같다는 뜻이라(NFD는 결정적/가역적 변환)
    키 충돌로 서로 다른 요리명이 묻히는 일은 없다.
    """
    return {_decompose_hangul(name): name for name in _all_dish_names(client)}


def extract_dish_name(utterance: str, client=None, fuzzy_cutoff: float = FUZZY_CUTOFF) -> str | None:
    """STT 텍스트 한 문장에서 DB에 실제로 있는 요리명을 찾아낸다.

    이 함수가 돌려주는 문자열을 select_standard_recipe()의 dish_name 인자로
    그대로 넘기면 된다 — 지금까지는 이 자리를 호출하는 쪽(테스트/app.py)이
    손으로 채워 넣고 있었다.

    LLM에게 "이 문장의 요리명이 뭐야?"라고 묻지 않는다(1.5 원칙, 로컬 LLM도
    포함 — 판단을 LLM에 맡기는 구조 자체를 안 쓰기로 한 결정). 대신 3단계
    문자열 비교만으로 처리한다.

      1) 완전일치 — 발화 전체가 요리명 그 자체인 경우 ("된장찌개")
      2) 부분일치 — 발화 안에 요리명이 그대로 들어있는 경우
         ("된장찌개 어떻게 만들어?")
      3) 편집거리 유사도 — STT가 요리명 자체를 잘못 들은 경우("부대찌게",
         "된장치게") 보정. 발화 전체와 공백으로 나눈 각 단어를 모두 후보로
         비교해서, 문장 속에 섞여 있어도("부대찌게 어떻게 만들어?") 잡히게
         한다. 비교는 음절 그대로가 아니라 자모로 분해해서 한다(_decompose_hangul
         참고) — 된소리/거센소리, 애/에처럼 음절 단위로는 "다른 글자"로 보이지만
         실제로는 음소 하나 차이인 흔한 오인식까지 잡아내기 위함.

    2)와 3)에서 나온 후보를 합쳐서 더 구체적인(긴) 이름을 채택한다(예: "김치"와
    "김치찌개" 둘 다 발화에 포함되면 "김치찌개"). 2026-08-24 실측 확인 — STT가
    "된장찌개"를 "된장찌장찌개"로 중복 오인식했을 때, 부분일치 단계가 "된장"
    (짧지만 실제 존재하는 요리명)을 substring으로 찾자마자 그대로 반환해버려서,
    편집거리 단계라면 훨씬 높은 유사도(0.8)로 잡아낼 수 있었을 "된장찌개"를
    아예 시도조차 못 하고 놓쳤다. 부분일치가 있어도 편집거리 후보까지 항상 같이
    구해서 더 긴 쪽을 채택해야 이런 "짧은 이름이 우연히 substring이라 먼저
    걸리는" 케이스를 피할 수 있다.

    셋 다 실패하면 None — 억지로 아무 요리나 골라주지 않는다(1.5 원칙과 같은
    태도: 모르면 모른다고 한다). 호출하는 쪽은 None일 때 "레시피 없음" 안내 후
    신규 등록으로 유도하면 된다(EC-11).
    """
    client = client or get_client()
    text = utterance.strip()
    if not text:
        return None

    names = _all_dish_names(client)
    if text in names:
        return text

    # len(name) >= 2 — 2026-08-24 실측 확인. DB에 1글자 요리명이 41개 있는데("무",
    # "국", "닭", "면", "장" 등), 부분일치를 글자 수 제한 없이 하면 "별빛나무 레시피
    # 알려줘"(존재하지 않는 요리)가 "무"라는 아무 관련 없는 요리와 매칭돼버린다(1.5
    # 원칙 위반 — 없는 걸 있다고 잘못 답함). 1글자 요리명이 정말 그 자체로 의도된
    # 경우("무 어떻게 만들어?")는 아래 편집거리 단계가 문장을 공백으로 나눠서
    # ("무"라는 단어 자체를 후보로) 여전히 잡아준다 — 그러니 여기서 부분일치만
    # 2글자 이상으로 좁혀도 정상 케이스를 놓치지 않는다.
    candidates = [name for name in names if name and len(name) >= 2 and name in text]

    name_map = _decomposed_name_map(client)
    for candidate in (text, *text.split()):
        close = difflib.get_close_matches(_decompose_hangul(candidate), name_map.keys(), n=1, cutoff=fuzzy_cutoff)
        if close:
            candidates.append(name_map[close[0]])

    # 2026-08-26 추가 — "가지무침"이 "가지무칔무칔무칔"로(faster-whisper beam_size=1
    # 디코딩 아티팩트, _collapse_stt_repetition() 문서 참고) 오인식된 경우 대응.
    # 접은 버전("가지무칔")도 위와 똑같이 부분일치/편집거리 후보로 시도해서 candidates에
    # 추가한다 — 원본 텍스트를 바꿔치기하지 않고 후보 하나만 더 늘리는 것이라 안전하다.
    # "샤브샤브"/"토마토"처럼 원본이 이미 실제 이름인 경우는 위에서 이미 그 원본이(더
    # 긴 형태로) candidates에 들어가 있어서, max(candidates, key=len)이 항상 더 긴
    # 원본을 우선 채택하고 접은 버전은 무시된다(실측: 60,282건 요리명 전체 스캔으로
    # "접은 버전이 원본보다 길어지는 경우는 없음"을 확인함 — 접기는 항상 문자열을
    # 줄이기만 하므로 구조적으로 보장됨).
    collapsed = _collapse_stt_repetition(text)
    if collapsed != text:
        candidates.extend(name for name in names if name and len(name) >= 2 and name in collapsed)
        for candidate in (collapsed, *collapsed.split()):
            close = difflib.get_close_matches(_decompose_hangul(candidate), name_map.keys(), n=1, cutoff=fuzzy_cutoff)
            if close:
                candidates.append(name_map[close[0]])

    # 2026-08-27 실측 리포트 — "10분잡채"(DB엔 공백 없이 저장)를 STT가 "10분 잡채"로
    # 중간에 공백을 넣어 인식한 경우, 위 부분일치 단계가 "10분잡채"는 통째로 못 찾고
    # (문자 그대로 비교라 공백 하나 차이도 실패) 그 안에 우연히 들어있는 더 짧은 다른
    # 요리명("잡채")만 찾아서 그걸로 확정해버렸다 — "10분잡채 레시피 알려줘"라고
    # 말했는데 "잡채"로 조회되는 버그(실측 확인). find_dish_name_ignoring_spaces()가
    # 이미 비슷한 문제를 select_standard_recipe() 실패 후 안전망으로 처리하지만, 이
    # 경우는 애초에 "잡채"라는 실제 존재하는 다른 이름으로 잘못 확정돼버려서
    # (select_standard_recipe()가 None을 안 돌려줌) 그 안전망까지 갈 일이 없다 —
    # 여기서 먼저 막아야 한다. 공백을 전부 지운 버전으로도 부분일치를 시도해서
    # candidates에 추가한다 — "10분잡채"가 후보에 들어오면 "잡채"보다 길어서
    # max(candidates, key=len)이 항상 이걸 우선 채택한다(위 "김치"/"김치찌개"와
    # 같은 원리).
    text_no_space = re.sub(r"\s+", "", text)
    if text_no_space != text:
        candidates.extend(name for name in names if name and len(name) >= 2 and name in text_no_space)

    if candidates:
        return max(candidates, key=len)

    return None


def find_dish_name_ignoring_spaces(dish_name: str, client=None) -> str | None:
    """dish_name이 DB에 완전일치로는 없지만, 공백만 다르게 붙어서 내용은 정확히 같은
    이름이 있으면 그 DB 원본 문자열을 돌려준다.

    2026-08-26 실측 리포트 — "실제 DB에 있는(직접 등록한) '고등어 라테'가 조회 안 됨"
    재현/원인 확정: entity_extract_llm.py::extract_intent_llm()이 LLM에 넘기기 전
    띄어쓰기를 전부 지우는 전처리를 하는데(2026-08-20, "소고기 미역국"이 "미역국"만
    잘리는 문제 방지용), 그 결과 LLM이 돌려주는 dish_name도 종종 공백 없이("고등어라테")
    나온다 — DB엔 원문 그대로("고등어 라테") 저장돼 있어서 select_standard_recipe()의
    완전일치가 실패했다. 등록한 커스텀 레시피뿐 아니라 공백이 들어간 표준 요리명
    전반에 해당하는 구조적 문제.

    extract_dish_name()의 편집거리 유사도(difflib, FUZZY_CUTOFF=0.7)와는 성격이 다르다 —
    "비슷한 다른 요리"로 새는 오매칭 위험이 있어서 pipeline.py::handle_utterance()의
    안전망으로 한 번 넣었다가 되돌렸는데("초코민트된장찌개"가 "토마토된장찌개"로
    오매칭되는 사례 실측), 이 함수는 유사도가 아니라 "공백만 빼면 내용이 정확히 같은가"
    만 본다 — 다른 요리로 새는 경우가 구조적으로 없다(내용 자체가 100% 동일해야만
    매칭됨).
    """
    client = client or get_client()
    target = re.sub(r"\s+", "", dish_name)
    if not target:
        return None
    for name in _all_dish_names(client):
        if re.sub(r"\s+", "", name) == target:
            return name
    return None


def find_dish_name_ignoring_repetition(dish_name: str, client=None) -> str | None:
    """dish_name이 DB에 완전일치로는 없지만, 짧은 음절 반복만 접으면 내용이 정확히
    같은 이름이 있으면 그 DB 원본 문자열을 돌려준다. find_dish_name_ignoring_spaces()와
    같은 자리에서 같은 이유로 쓰는 안전망 — fuzzy 매칭이 아니라 "반복만 접으면 정확히
    같은가"만 보므로 다른 요리로 새는 오매칭 위험이 없다.

    2026-08-26 실측 확정 — pipeline.py::handle_utterance()의 `resolved_dish_name =
    dish_name or extract_dish_name(...)`에서 로컬 LLM이 dish_name을 주면(예:
    "된장찌장찌개", faster-whisper beam_size=1 반복 아티팩트를 LLM이 검증 없이
    그대로 옮긴 것) extract_dish_name()의 _collapse_stt_repetition() 후보 로직이
    통째로 건너뛰어져서 아무 보정도 못 받는다는 게 실측 확인됐다 — extract_dish_name()
    은 "utterance"를 받는데 여긴 이미 확정된 "dish_name" 하나만 있어서 그 함수를
    재사용할 수 없었다. find_dish_name_ignoring_spaces()와 나란히, dish_name
    하나만 받아 반복만 접어서 정확일치 확인하는 이 함수로 별도 안전망을 둔다.
    """
    client = client or get_client()
    collapsed = _collapse_stt_repetition(dish_name)
    if not collapsed or collapsed == dish_name:
        return None
    if collapsed in _all_dish_names(client):
        return collapsed
    return None


# entity_extract.py::_QUERY_SUFFIXES와 같은 문구 — 그 파일은 규칙 기반 v1 추출기(현재
# 미사용, 로컬 LLM으로 대체됨)가 발화 원문에서 요리명을 잘라낼 때 쓰던 접미사 목록인데,
# 여기서는 반대 방향 — 로컬 LLM이 dish_name에 이 문구를 실수로 안 떼고 그대로 남겨서
# 돌려준 경우를 잡는다(find_dish_name_stripping_query_suffix() 문서 참고).
_QUERY_SUFFIXES_TO_STRIP = (
    "레시피 알려줘",
    "레시피알려줘",
    "만드는 법 알려줘",
    "만드는법 알려줘",
    "어떻게 만들어요",
    "어떻게 만드나요",
    "어떻게 만들어",
    "어떻게 해요",
    "어떻게 해",
    "레시피",  # 가장 짧고 포괄적이라 마지막에 검사(다른 접미사가 먼저 걸리게)
)


def find_dish_name_stripping_query_suffix(dish_name: str, client=None) -> str | None:
    """dish_name 끝에 "레시피"류 질의 접미사가 안 떼진 채 남아있어서 완전일치가
    실패했을 때, 그 접미사를 떼면 DB에 정확히 있는 이름인 경우 그 원본을 돌려준다.
    find_dish_name_ignoring_spaces()/find_dish_name_ignoring_repetition()와 같은
    자리, 같은 성격의 안전망 — 편집거리/유사도를 전혀 안 쓰고 "접미사를 뗀 결과가
    DB에 글자 그대로 있는가"만 본다. 그래서 사용자가 실제로 등록한 적 없는 새 요리를
    말했을 때(예: 존재하지 않는 "OO레시피") 엉뚱한 기존 요리로 새는 오매칭은 구조적으로
    없다 — 뗀 이름이 없으면 그냥 None, 호출부는 그대로 "없다"고 정직하게 답한다.

    2026-08-27 실측 리포트 — "멸치볶음 레시피"라고 물었는데 "멸치볶음"(DB에 실제 있는
    표준 레시피)을 못 찾고 통째로 실패하는 사례. entity_extract_llm.py의 few-shot이
    "요리명레시피" 패턴을 대부분 잘 걸러내지만(예: "김치볶음밥레시피알려줘"->
    "김치볶음밥"), 100% 보장은 아니라서 LLM이 가끔 "레시피"까지 dish_name에 그대로
    남겨 돌려주면 `resolved_dish_name = dish_name or extract_dish_name(...)`의
    `or` 단축 평가 때문에 정답을 이미 정확히 뽑아내는 extract_dish_name()의 원문
    기반 로직 자체가 통째로 건너뛰어진다(원문 재시도 자체를 안전망으로 되살리는
    방식은 "초코민트 된장찌개"->"토마토된장찌개" 오매칭 회귀 때문에 이미 되돌려져
    있음, pipeline.py 조회 분기 주석 참고) — 그래서 원문 재시도 대신, LLM 출력 자체를
    결정적 문자열 접미사 제거로만 정리하는 이 훨씬 좁고 안전한 방식을 택한다.
    """
    client = client or get_client()
    text = dish_name.strip()
    if not text:
        return None
    names = _all_dish_names(client)
    for suffix in _QUERY_SUFFIXES_TO_STRIP:
        if text.endswith(suffix):
            candidate = text[: -len(suffix)].strip()
            if candidate and candidate in names:
                return candidate
    return None


def find_more_specific_containing_name(dish_name: str, utterance: str, client=None) -> str | None:
    """dish_name이 이미 DB에서 찾아졌지만, 발화 원문 안에 dish_name을 포함하면서 더
    긴(더 구체적인) 다른 DB 요리명이 문자 그대로(공백만 무시) 들어있으면 그 이름을
    돌려준다.

    2026-08-27 실측 리포트 — "10분잡채"(DB에 실제 있음)를 로컬 LLM이 "잡채"(이것도
    DB에 실제 있는 별개 요리)로만 추측해서 조회한 사례. "잡채"도 정직하게 존재하는
    매칭이라 select_standard_recipe()가 None을 안 돌려주고, 그러면 handle_utterance()의
    다른 안전망들(find_dish_name_ignoring_spaces() 등)은 애초에 "found is None"일
    때만 발동하므로 전혀 도움이 안 된다 — 이미 성공한 매칭을 사후에 더 구체적인
    것으로 승격해주는 이 함수가 따로 필요하다.

    순수 substring 포함관계만 보고 편집거리/유사도는 전혀 안 쓴다 — "초코민트
    된장찌개"(존재하지 않는 요리)가 "토마토된장찌개"(엉뚱한 실제 요리)에 편집거리로
    잘못 매칭되던 문제(pipeline.py 조회 분기 주석 참고)와는 오매칭 위험의 성격이
    다르다. 거기선 존재하지 않는 요리를 억지로 편집거리로 매칭시켰지만, 여긴 발화에
    실제로 그 글자 그대로(공백 제외) 들어있는 이름만 인정하므로 구조적으로 안전하다.
    """
    client = client or get_client()
    text_no_space = re.sub(r"\s+", "", utterance)
    names = _all_dish_names(client)
    # 2026-09-01 버그 수정 — utterance는 공백을 지우고 비교하면서(text_no_space) DB에서
    # 온 후보 name은 공백을 그대로 둔 채 "in text_no_space"로 비교하고 있었다. DB
    # 요리명 자체에 내부 공백이 있으면(예: "10분 잡채") 공백 없는 발화 문자열과 절대
    # substring이 안 맞아서 이 함수가 항상 조용히 실패했다(승격을 못 해서 "10분잡채"라고
    # 말해도 먼저 찾은 "잡채"에 그대로 머묾) — 실측 재현(2026-09-01, "10분 잡채 알려줘"
    # -> "잡채" 레시피가 나옴). 이 함수 docstring 자체가 "공백만 무시"라고 명시하고
    # 있으니 양쪽 다 공백을 지우고 비교해야 그 설명대로 동작한다.
    candidates = [
        name
        for name in names
        if name
        and len(name) > len(dish_name)
        and dish_name in name
        and re.sub(r"\s+", "", name) in text_no_space
    ]
    if candidates:
        return max(candidates, key=len)
    return None


# 2026-09-01 — 이 자리에 있던 _max_view_count()(조회수+등록일 기준으로 여러 후보 중
# 1등을 겨루던 헬퍼) 제거. select_standard_recipe() 문서 참고 — 새 500개 표준
# 데이터는 요리명당 api_standard가 정확히 1행뿐이라 겨룰 후보 자체가 없어져서
# 유일한 호출부가 사라졌다(grep으로 다른 호출부 없음, 테스트도 이 함수를 직접
# 테스트하지 않았음을 확인). 되돌리려면 git으로 이 커밋 이전 버전을 참고할 것.


def select_standard_recipe(dish_name: str, client=None) -> dict | None:
    """요리명 하나를 받아서, 보여줄 "그 요리의 대표 레시피" 하나를 고른다.

    2026-09-01 — 500개 표준 데이터 전면 교체와 함께 조회수(view_count) 기반
    "여러 후보 중 대표 선정" 로직을 제거했다(팀 결정, 되돌리려면 git으로 이 커밋
    이전 버전 참고). 예전엔 api_standard 표준 데이터가 60,282건 원본 안에서
    이미 "요리명당 여러 행"으로 존재할 수 있어서(만개레시피 원본에 같은 요리명이
    여러 번 등록돼 있었음) 조회수로 그중 1등을 겨루는 로직이 필요했는데, 새
    500개 데이터는 DB의 uq_recipes_dish_name_standard(unique index)가 요리명당
    api_standard 행을 정확히 1개로 이미 강제하고 있어서 그 경쟁 자체가 구조적으로
    발생할 수 없다.

    같은 요리명이 여전히 여러 개 있을 수 있는 경우는 하나뿐이다: 사용자가 표준
    요리와 같은 이름으로 직접 등록한(user_custom) 버전이 추가로 있는 경우(EC-17,
    같은 이름으로 여러 버전 등록 허용). 이럴 땐 검증된 표준(api_standard)을
    우선한다 — 사용자 임의 제출보다 신뢰도가 높다고 보는 게 자연스러운 기본값.
    api_standard가 아예 없으면(사용자만 등록한 요리) 승인된 user_custom 중
    가장 먼저 등록된 것(created_at 오름차순 첫 번째)을 결정론적으로 고른다 —
    "먼저 등록한 사람 것을 우선"이라는 단순하고 예측 가능한 규칙.

    승인 여부(recipes.approved, 관리자 페이지 스펙 참고)로만 공개를 가른다 —
    등록한 사람이 누구인지는 추적하지 않는다(2026-08-27, 계정/쿠키 시스템 제거
    결정). api_standard는 항상 approved='Y'이고, 신규 user_custom은 관리자가
    승인하기 전까지 approved='N'이라 아래 필터에서 제외된다.

    반환값 셋 중 하나:
      - None: 이 요리명 자체가 DB에 아예 없음(6.5: 표준 데이터 밖 요리)
      - {"pending": True}: 이 요리명으로 등록된 행은 있지만 전부 승인 대기 중
      - 대표 레시피 dict: 승인된 후보 중 1등(api_standard 우선, 없으면 최초 등록)
    """
    client = client or get_client()
    # .eq("dish_name", ...) : dish_name이 정확히 일치하는 행만
    # .in_("source", [...]) : source가 두 값 중 하나인 행만 (SQL의 WHERE ... IN (...) 과 같음)
    # .order("created_at") : api_standard가 없을 때 "가장 먼저 등록된 것"을 결정론적으로
    # 고르기 위한 정렬 — 정렬 없이는 Supabase가 어떤 순서로 돌려줄지 보장이 없다.
    res = (
        client.table("recipes")
        .select("*")
        .eq("dish_name", dish_name)
        .in_("source", ["api_standard", "user_custom"])
        .order("created_at")
        .execute()
    )
    rows = res.data
    if not rows:
        return None  # 이 요리명 자체가 DB에 아예 없음 (6.5: 표준 데이터 밖 요리)

    candidates = [r for r in rows if r.get("approved") == "Y"]
    if not candidates:
        return {"pending": True}  # 있지만 전부 관리자 승인 대기 중

    # api_standard가 후보에 있으면 항상 그걸 우선(검증된 표준이라 신뢰도가 더 높음).
    # 없으면(사용자만 등록한 요리) 위 order("created_at")로 이미 정렬돼 있으므로
    # candidates[0]이 곧 "가장 먼저 등록된 승인 버전"이다.
    winner = next((r for r in candidates if r.get("source") == "api_standard"), candidates[0])

    return {
        "recipe_id": winner["id"],
        "dish_name": winner["dish_name"],
        "view_count": winner.get("view_count", 0),
        # 2026-08-20 추가: ui/start.py가 실제 화면(recipe_confirm)에 "오늘의 재료" 미리보기를
        # 그리려면 원문 재료 텍스트가 필요한데, 이전엔 이 함수가 요약 정보만 돌려주고
        # ingredients는 빼놓고 있었다. winner는 이미 .select("*")로 전체 컬럼을 갖고
        # 있으니 그냥 같이 얹어준다 — 새 쿼리 없음. 기존 호출부는 키를 그대로 골라 쓰므로
        # (예: result["recipe_id"]) 딕셔너리에 키가 하나 늘어나는 건 하위 호환에 안전하다.
        "ingredients": winner.get("ingredients", ""),
    }
