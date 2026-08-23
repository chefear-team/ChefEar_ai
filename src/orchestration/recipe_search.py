"""7.3/7.6 — 표준 레시피 선정, 재료 대체 검색(6.4), 발화 속 요리명 추출.

이 파일의 함수들은 전부 "DB에서 조건에 맞는 레시피를 찾는다"는 공통점이
있는데, 못 찾았을 때 절대로 답을 지어내지 않는다(1.5 원칙: 서비스 실행 중
LLM 생성 fallback 없음). 못 찾으면 그냥 "없다"고 정직하게 답한다 — 이게 이
프로젝트 재료 대체 기능의 핵심 설계다.
"""
from __future__ import annotations

import difflib
import unicodedata
from functools import lru_cache

from orchestration.db import get_client

NOT_FOUND_MESSAGE = "죄송해요, 이 조합의 레시피는 없어요."

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
         ("된장찌개 어떻게 만들어?"). 여러 요리명이 동시에 걸리면(예: "김치"와
         "김치찌개" 둘 다 발화에 포함) 더 구체적인(긴) 이름을 채택한다.
      3) 편집거리 유사도 — STT가 요리명 자체를 잘못 들은 경우("부대찌게",
         "된장치게") 보정. 발화 전체와 공백으로 나눈 각 단어를 모두 후보로
         비교해서, 문장 속에 섞여 있어도("부대찌게 어떻게 만들어?") 잡히게
         한다. 비교는 음절 그대로가 아니라 자모로 분해해서 한다(_decompose_hangul
         참고) — 된소리/거센소리, 애/에처럼 음절 단위로는 "다른 글자"로 보이지만
         실제로는 음소 하나 차이인 흔한 오인식까지 잡아내기 위함.

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

    contained = [name for name in names if name and name in text]
    if contained:
        return max(contained, key=len)

    name_map = _decomposed_name_map(client)
    for candidate in (text, *text.split()):
        close = difflib.get_close_matches(_decompose_hangul(candidate), name_map.keys(), n=1, cutoff=fuzzy_cutoff)
        if close:
            return name_map[close[0]]

    return None


def _max_view_count(rows: list[dict]) -> dict:
    """여러 후보 중 "표준"으로 뽑을 하나를 고른다. 6.1/EC-09/EC-19 규칙.

    key=lambda r: (view_count, created_at) 는 파이썬 max()에게 "먼저
    view_count(조회수)로 비교하고, 조회수가 같으면 created_at(등록일)으로
    비교해라"라고 알려주는 것이다. 튜플은 앞자리부터 비교되기 때문에
    (10, "2026-01-01") > (10, "2025-01-01")처럼 자연스럽게 2단계 정렬이 된다.
    조회수가 전부 0인 신규 등록 레시피끼리는 결국 created_at만으로 비교되므로
    EC-19("조회수 0이면 최신 등록일 우선")도 이 한 줄로 같이 처리된다.
    """
    return max(rows, key=lambda r: (r.get("view_count", 0), r.get("created_at", "")))


def select_standard_recipe(dish_name: str, owner_id: str | None = None, client=None) -> dict | None:
    """요리명 하나를 받아서, 이 사용자에게 보여줄 "그 요리의 대표 레시피" 하나를 고른다.

    같은 요리명이 여러 개 있을 수 있는 이유는 두 가지다.
      1) api_standard 레시피가 조회수 기준으로 이미 여러 후보 중 1등만 골라
         DB에 들어가 있으므로(작업1의 load_data.py) 보통 1개뿐이다.
      2) 사용자가 직접 등록/수정한 user_custom 버전이 추가로 있을 수 있다.
         심지어 서로 다른 사용자가 각자 자기 버전을 등록했을 수도 있다.

    owner_id(작업3, 쿠키 UUID)가 주어지면 "이 사용자 소유의" user_custom만
    후보로 본다 — 다른 사용자가 저장한 user_custom은 절대로 대신 보여주지
    않는다(그 사람의 개인 레시피를 남에게 노출하면 안 되므로). 내 것이 없으면
    api_standard로 폴백하고, 그마저 없으면(이색 요리를 남이 등록했는데 나는
    등록한 적 없는 경우) None을 반환한다.

    owner_id가 아직 없으면(예: UI가 아직 로그인 로직을 안 붙였거나, 이 함수를
    owner 구분 없이 그냥 써보는 테스트) 예전 방식대로 아무 user_custom이나
    우선한다 — 하위 호환을 위한 기본 동작이다.
    """
    client = client or get_client()
    # .eq("dish_name", ...) : dish_name이 정확히 일치하는 행만
    # .in_("source", [...]) : source가 두 값 중 하나인 행만 (SQL의 WHERE ... IN (...) 과 같음)
    res = (
        client.table("recipes")
        .select("*")
        .eq("dish_name", dish_name)
        .in_("source", ["api_standard", "user_custom"])
        .execute()
    )
    rows = res.data
    if not rows:
        return None  # 이 요리명 자체가 DB에 아예 없음 (6.5: 표준 데이터 밖 요리)

    if owner_id:
        my_custom_rows = [r for r in rows if r["source"] == "user_custom" and r.get("owner_id") == owner_id]
        api_rows = [r for r in rows if r["source"] == "api_standard"]
        candidates = my_custom_rows or api_rows  # 파이썬에서 "or"는 앞이 빈 리스트면 뒤를 씀
        if not candidates:
            return None  # 있는 건 남의 user_custom뿐 -> 노출하지 않음
    else:
        user_custom_rows = [r for r in rows if r["source"] == "user_custom"]
        candidates = user_custom_rows if user_custom_rows else rows  # EC-20/FR-08

    winner = _max_view_count(candidates)

    # representativeness(대표성)는 "1등이 후보들 전체 조회수 중 몇 %를 차지하는가"다.
    # `or 1`은 0으로 나누기(ZeroDivisionError)를 막기 위한 안전장치 —
    # 모든 후보의 view_count가 0이면 total_view도 0이 되니, 그 대신 1로 나눠서
    # representativeness를 그냥 0.0으로 만든다.
    total_view = sum(r.get("view_count", 0) for r in candidates) or 1
    return {
        "recipe_id": winner["id"],
        "dish_name": winner["dish_name"],
        "view_count": winner.get("view_count", 0),
        "total_candidates": len(candidates),
        "representativeness": winner.get("view_count", 0) / total_view,
        # 2026-08-20 추가: ui/start.py가 실제 화면(recipe_confirm)에 "오늘의 재료" 미리보기를
        # 그리려면 원문 재료 텍스트가 필요한데, 이전엔 이 함수가 요약 정보만 돌려주고
        # ingredients는 빼놓고 있었다. winner는 이미 .select("*")로 전체 컬럼을 갖고
        # 있으니 그냥 같이 얹어준다 — 새 쿼리 없음. 기존 호출부는 키를 그대로 골라 쓰므로
        # (예: result["recipe_id"]) 딕셔너리에 키가 하나 늘어나는 건 하위 호환에 안전하다.
        "ingredients": winner.get("ingredients", ""),
    }


def _build_variant_name(base_dish_name: str, requested_ingredient: list[str]) -> str | None:
    """"바지락" + "된장찌개" -> "바지락된장찌개"처럼, 요청 재료를 붙인 요리명을 만든다.

    이 규칙은 6.4 문서에 나온 실제 테스트 사례("새우"+"바지락"+"된장찌개" ->
    "새우바지락된장찌개")를 그대로 따른 것이다. 재료가 하나도 없으면(빼기만
    요청한 EC-08 케이스) 만들 이름 자체가 없으니 None을 돌려주고, 호출하는 쪽은
    그러면 이름 매칭 단계를 건너뛰고 바로 재료 내용 검색으로 넘어간다.
    """
    if not requested_ingredient:
        return None
    return "".join(requested_ingredient) + base_dish_name


def search_variant_recipe(
    base_recipe_id: str,
    requested_ingredient: list[str],
    excluded_ingredient: str | None = None,
    client=None,
) -> dict:
    """재료 대체 검색의 1단계: 요리명이 정확히 일치하는 레시피가 있는지 먼저 본다(6.4①).

    예: "된장찌개"를 진행 중에 "바지락 넣어도 돼?"라고 물으면, 먼저
    "바지락된장찌개"라는 이름의 레시피가 DB에 그대로 있는지 찾아본다. 있으면
    그게 제일 확실한 매칭이라 바로 반환하고, 없으면(match_type=none이 아니라
    함수 자체가) 2단계인 search_by_ingredient_content()로 넘어간다 — 이름은
    달라도 재료 구성이 맞는 레시피가 있을 수 있어서다(6.4 문서의 "새우바지락된장찌개"
    이름으로는 0건이었지만 "해물된장찌개" 재료 내용으로는 매칭됐던 실측 사례 참고).
    """
    client = client or get_client()
    # .single() : 결과가 정확히 1건이라고 가정하고, res.data를 리스트가 아니라
    # 딕셔너리 하나로 바로 돌려준다(id로 조회하니 1건 아니면 이상한 상황).
    base = client.table("recipes").select("dish_name").eq("id", base_recipe_id).single().execute().data
    variant_name = _build_variant_name(base["dish_name"], requested_ingredient)

    if variant_name:
        res = client.table("recipes").select("*").eq("dish_name", variant_name).execute()
        if res.data:
            winner = _max_view_count(res.data)  # 같은 이름이 여러 건이면 EC-09 규칙대로 1등 선택
            return {
                "match_type": "exact_name",
                "result_recipe_id": winner["id"],
                "result_dish_name": winner["dish_name"],
                "source": winner["source"],
            }

    # 이름 매칭 실패 -> 2단계(재료 내용 검색)로 넘긴다. AND/제외 필터는
    # search_by_ingredient_content() 안에서 처리된다.
    return search_by_ingredient_content(base_recipe_id, requested_ingredient, excluded_ingredient, client=client)


def search_by_ingredient_content(
    base_recipe_id: str,
    requested_ingredient: list[str],
    excluded_ingredient: str | None = None,
    client=None,
) -> dict:
    """재료 대체 검색의 2단계: 이름이 아니라 "재료 목록에 이게 들어있는가"로 찾는다(6.4②).

    EC-06(부분 문자열 매칭)/EC-07(여러 재료 AND 조건)/EC-08(재료 제외) 전부
    여기서 처리한다.
    """
    client = client or get_client()
    query = client.table("recipes").select("*").eq("source", "api_standard")

    # .ilike(컬럼, "%문자열%") 은 SQL의 LIKE '%문자열%' 와 같다 — 대소문자 구분
    # 없이 부분 문자열이 포함돼 있으면 매칭된다. 그래서 사용자가 "바지락"이라고만
    # 말해도 재료란에 "바지락조개"라고 적힌 레시피가 걸린다(EC-06).
    #
    # requested_ingredient가 ["새우", "바지락"] 처럼 여러 개면 .ilike()를 그만큼
    # 여러 번 체이닝(연쇄 호출)한다. supabase-py는 필터를 여러 개 걸면 전부
    # AND로 합쳐지므로(SQL의 WHERE a AND b AND c와 동일), 결과적으로 "새우도
    # 있고 바지락도 있는" 레시피만 남는다(EC-07의 AND 조건).
    for ing in requested_ingredient:
        query = query.ilike("ingredients", f"%{ing}%")

    if excluded_ingredient:
        # .not_.ilike(...) 는 위와 반대로 "이 문자열이 없는" 행만 남긴다(EC-08).
        # 예: "애호박 빼고 새우 넣어도 돼?" -> 새우는 있고 애호박은 없는 레시피만.
        query = query.not_.ilike("ingredients", f"%{excluded_ingredient}%")

    res = query.execute()
    if res.data:
        winner = _max_view_count(res.data)  # 여러 건 매칭되면 EC-09 규칙대로 1등 선택
        return {
            "match_type": "ingredient_content",
            "result_recipe_id": winner["id"],
            "result_dish_name": winner["dish_name"],
            "source": winner["source"],
        }

    # 이름 매칭도, 재료 내용 매칭도 다 실패 -> AC-05. LLM으로 그럴싸한 답을
    # 지어내지 않고 정직하게 "없다"고만 답한다(1.5 원칙).
    return {"match_type": "none", "message": NOT_FOUND_MESSAGE}
