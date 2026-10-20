"""STT 텍스트 후처리(순수 함수) — 단위 정규화, 조리 문맥 숫자 보정, 환각 방어.

원래 stt/infer.py 안에 있던 것을 그대로 옮겼다(동작 변경 없음). torch/transformers 없이 import되어
추론 서버(CPU 이미지)와 API 서버가 같은 후처리를 쓴다. stt.infer는 아래 이름을 다시 내보낸다.
"""
import re
from typing import Optional, Sequence, Union

# ============================================================
# 고위험 재료 사전
# ============================================================

# canonical:
# 실제 ChefEar에서 사용할 표준 재료명
#
# risky_patterns:
# STT 고위험군 테스트에서 실제 반복 확인된 표현
#
# 숫자는 여기에서 지정하지 않습니다.
# 숫자 보정 여부는 현재 레시피 문맥을 확인한 뒤 결정합니다.

HIGH_RISK_INGREDIENTS = {
    "소고기다짐육": [
        r"소고기\s*다짐육",
        r"소고기\s*다짐",
        r"소고기\s*다진",
    ],

    "돼지고기다짐육": [
        r"돼지고기\s*다짐육",
        r"돼지고기\s*다짐",
        r"돼지고기\s*다진",
    ],

    "한우다짐육": [
        r"한우\s*다짐육",
        r"한우\s*다짐",
        r"한우\s*다진",
    ],

    "다짐육": [
        r"(?<![가-힣])다짐육",
        r"(?<![가-힣])다짐",
    ],
}

# ============================================================
# 1차 후처리
# 단위 표기 정규화
# ============================================================

def normalize_stt_text(text: str) -> str:
    """STT가 의미는 맞게 인식했지만
    단위를 영어로 출력한 경우 한글 표기로 통일합니다.
    """

    # kg → 킬로그램
    # g보다 먼저 처리
    text = re.sub(
        r"(\d+)\s*[kK][gG](?![A-Za-z])",
        r"\1킬로그램",
        text,
    )

    # ml → 밀리리터
    # l보다 먼저 처리
    text = re.sub(
        r"(\d+)\s*[mM][lL](?![A-Za-z])",
        r"\1밀리리터",
        text,
    )

    # g → 그램
    text = re.sub(
        r"(\d+)\s*[gG](?![A-Za-z])",
        r"\1그램",
        text,
    )

    # l / L → 리터
    text = re.sub(
        r"(\d+)\s*[lL](?![A-Za-z])",
        r"\1리터",
        text,
    )

    return text


# ============================================================
# 재료 문맥 정규화
# ============================================================

def normalize_ingredient_context(
    ingredient_context: Optional[
        Union[str, Sequence[str]]
    ],
) -> str:
    """현재 레시피의 재료 정보를
    비교하기 쉬운 하나의 문자열로 변환합니다.
    """

    if ingredient_context is None:
        return ""

    if isinstance(
        ingredient_context,
        (list, tuple, set),
    ):

        context = " ".join(
            str(item)
            for item in ingredient_context
        )

    else:

        context = str(
            ingredient_context
        )


    # 재료 DB의 g / kg / ml 등도
    # 같은 기준으로 맞춤
    context = normalize_stt_text(
        context
    )


    # 비교에 방해되는 연속 공백 정리
    context = re.sub(
        r"\s+",
        " ",
        context,
    ).strip()

    return context


# ============================================================
# 재료 문맥에서 수량 존재 여부 확인
# ============================================================

def context_has_quantity(
    context: str,
    ingredient: str,
    quantity: int,
) -> bool:
    """
    현재 레시피 재료 문맥에

        재료명 + 특정 그램 수

    가 존재하는지 확인합니다.

    예
    --
    소고기다짐육 100그램
    """

    # 비교 시 재료명 내부 공백 허용
    ingredient_pattern = (
        r"\s*".join(
            map(
                re.escape,
                ingredient,
            )
        )
    )

    pattern = (
        ingredient_pattern
        + rf"\s*{quantity}\s*그램"
    )

    return bool(
        re.search(
            pattern,
            context,
        )
    )


# ============================================================
# 2차 후처리
# 고위험 음향 경계 조건부 보정
# ============================================================

def correct_high_risk_with_context(
    text: str,
    ingredient_context: Optional[
        Union[str, Sequence[str]]
    ],
) -> str:
    """고위험군 테스트에서 반복 확인된
    '다짐육 + 백그램 → 다짐 + 육백그램'
    음향 경계 문제를 조건부로 보정합니다.
    """

    context = normalize_ingredient_context(
        ingredient_context
    )


    # --------------------------------------------------------
    # 재료 문맥이 없으면 숫자 보정 금지
    # --------------------------------------------------------

    if not context:
        return text


    corrected_text = text


    # ========================================================
    # 고위험 재료별 검사
    # ========================================================

    for canonical_name, risky_patterns in (
        HIGH_RISK_INGREDIENTS.items()
    ):

        # ----------------------------------------------------
        # 현재 레시피가 실제로 100그램인지 확인
        # ----------------------------------------------------

        has_100g = context_has_quantity(
            context,
            canonical_name,
            100,
        )


        # ----------------------------------------------------
        # 현재 레시피가 실제 600그램이면
        # 절대 100그램으로 바꾸지 않음
        # ----------------------------------------------------

        has_600g = context_has_quantity(
            context,
            canonical_name,
            600,
        )


        # 안전 조건
        if not has_100g:
            continue

        if has_600g:
            continue


        # ----------------------------------------------------
        # STT 결과에서
        # 고위험 표현 + 600그램 확인
        # ----------------------------------------------------

        for risky_pattern in risky_patterns:

            pattern = (
                rf"{risky_pattern}"
                rf"\s*600그램"
            )


            # ------------------------------------------------
            # 현재 레시피가 100그램이라고 확인된 경우에만
            # 표준 재료명 + 100그램으로 보정
            # ------------------------------------------------

            corrected_text = re.sub(
                pattern,
                f"{canonical_name} 100그램",
                corrected_text,
            )


    return corrected_text

_HALLUCINATION_MARKERS: tuple[str, ...] = (
    "시청해주셔서 감사합니다",
    "시청해 주셔서 감사합니다",
    "구독과 좋아요",
    "구독", "좋아요 눌러",
    "다음 영상에서 만나요",
    "다음 시간에",
    "영상 봐주셔서",
    "한글자막",
    "자막 제공",
    "mbc 뉴스",
    "kbs 뉴스",
    "sbs 뉴스",
    "뉴스룸",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "subscribe to",
)


def _looks_like_hallucination(text: str) -> bool:
    """text가 whisper 환각 상투구를 포함하거나, 같은 짧은 조각이 비정상적으로 반복되면 True."""
    low = text.lower()
    if any(m in low for m in _HALLUCINATION_MARKERS):
        return True
    # 반복 아티팩트: 같은 토큰(공백 기준)이 전체의 절반 이상 + 4회 이상
    parts = [p for p in text.split() if p]
    if len(parts) >= 4:
        from collections import Counter

        top, cnt = Counter(parts).most_common(1)[0]
        if cnt >= 4 and cnt / len(parts) >= 0.5:
            return True
    return False
