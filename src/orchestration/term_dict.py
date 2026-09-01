# -*- coding: utf-8 -*-
"""썰기·조리동작 용어 사전.
- resolve_for_tts/resolve_for_display: [TERM:...] 태그를 화면/음성용으로 변환(500개
  규칙생성 데이터, 이미 태그가 정확히 붙어 있는 경우에 사용)
- auto_tag_terms: 사용자가 신규 등록한 자유 텍스트에서 변형 표현("어슷하게 썰어" 등)을
  감지해 [TERM:...] 태그를 자동으로 붙임(register_recipe()에서 사용)
"""
import re

CUTTING_TERMS = {
    "어슷썰기": "칼을 비스듬히 기울여 사선으로 써는 방법",
    "깍둑썰기": "사방 1~2cm 정도의 정육면체 모양으로 써는 방법",
    "채썰기": "가늘고 길게 실처럼 써는 방법",
    "다지기": "잘게 잘라 알갱이처럼 만드는 방법",
    "편썰기": "얇고 넓적하게 써는 방법",
    "통썰기": "원래 모양을 살려 둥글게 두께만 나눠 써는 방법",
    "반달썰기": "세로로 반을 가른 뒤 두께로 썰어 반달 모양으로 만드는 방법",
    "나박썰기": "얇고 네모지게 써는 방법",
    "저미기": "얇게 포 뜨듯이 써는 방법",
}

COOKING_VERB_TERMS = {
    "데치다": "끓는 물에 아주 짧게 넣었다 바로 건져내는 것",
    "조리다": "양념한 국물에 재료를 넣고 국물이 스며들도록 끓이는 것",
    "졸이다": "국물의 양이 줄어들도록 계속 끓이는 것",
    "지지다": "팬에 약간의 기름이나 국물을 두르고 약한 불로 천천히 익히는 것",
    "뜸을 들이다": "불을 끈 뒤에도 뚜껑을 덮은 채로 남은 열로 마저 익히는 것",
}

TERM_DICT = {**CUTTING_TERMS, **COOKING_VERB_TERMS}

_TAG_PATTERN = re.compile(r"\n?\[TERM:([^\]]+)\]")


def resolve_for_tts(raw_text: str) -> str:
    """[TERM:용어] 태그를 완전한 설명 문장으로 바꿔서 TTS에 넘길 최종 텍스트를 만든다."""
    def _replace(match):
        term = match.group(1)
        if term in TERM_DICT:
            return f" {term}란 {TERM_DICT[term]}이에요."
        return ""
    return _TAG_PATTERN.sub(_replace, raw_text)


def resolve_for_display(raw_text: str) -> str:
    """[TERM:용어] 태그를 설명 없이 그냥 제거한다(화면 자막용, 짧게 유지)."""
    return _TAG_PATTERN.sub("", raw_text)


# ── 사용자 신규 등록 텍스트용 자동 태깅 ──
# 완벽한 형태소 분석이 아니라 자주 쓰이는 활용형만 커버하는 패턴 매칭이다.
#
# 2026-09-01 실측 수정 — 원래 "어슷썰기"만 (하게)?를 허용하고 나머지(깍둑/채/편/통/
# 반달/나박)는 어간과 "썰다" 사이에 아무 수식어도 못 끼게 막혀 있었다. 그래서
# "무를 나박하게 썰어주세요"(어간+"하게"+공백+"썰어주세요") 같은, 실제로 사용자가
# 흔히 쓰는 표현이 [TERM:나박썰기]로 안 잡히는 게 term_dict.py 자체 실행(__main__
# 검증)으로 재현됐다 — "어슷" 하나만 우연히 통과하고 나머지는 전부 같은 결함이었다.
# 어간과 동사 사이에 낄 수 있는 흔한 수식어(하게/으로/모양)를 모든 "~썰기" 패턴에
# 공통으로 허용하도록 통일한다(개별 패치 대신 공통 접미부 하나로 관리해서, 나중에
# 새 표현이 또 빠지는 걸 방지).
_CUT_INFIX = r"\s*(?:하게|으로|모양)?\s*"  # 어간과 "썰다" 사이에 낄 수 있는 흔한 수식어

TERM_PATTERNS = {
    "어슷썰기": r"어슷" + _CUT_INFIX + r"(썰|썬|썸)",
    "깍둑썰기": r"깍둑" + _CUT_INFIX + r"(썰|썬)",
    "채썰기": r"채" + _CUT_INFIX + r"(썰|썬)",
    "다지기": r"다지|다져|다진|다졌",
    "편썰기": r"편" + _CUT_INFIX + r"(썰|썬)",
    "통썰기": r"통" + _CUT_INFIX + r"(썰|썬)",
    "반달썰기": r"반달" + _CUT_INFIX + r"(썰|썬)",
    "나박썰기": r"나박" + _CUT_INFIX + r"(썰|썬)",
    "저미기": r"저미|저며|저민",
    "데치다": r"데치|데쳐|데친|데쳤",
    "조리다": r"(?<!요)조려|조리다|조린",
    "졸이다": r"졸이|졸여|졸인|졸였",
    "지지다": r"지지고|지져|지진",
    "뜸을 들이다": r"뜸\s*(을)?\s*들이|뜸\s*(을)?\s*들여",
}


def auto_tag_terms(user_text: str) -> str:
    """사용자가 등록한 조리순서 텍스트를 줄 단위로 스캔해서,
    변형 표현이라도 감지되면 [TERM:...] 태그를 붙인다. 이미 태그가 붙어있는
    줄(500개 규칙생성 데이터)에는 중복 적용하지 않는다."""
    lines = user_text.split("\n")
    output = []
    for line in lines:
        output.append(line)
        if line.strip().startswith("[TERM:"):
            continue
        for term, pattern in TERM_PATTERNS.items():
            if re.search(pattern, line):
                output.append(f"[TERM:{term}]")
    return "\n".join(output)


if __name__ == "__main__":
    sample = "1. 양파를 어슷썰기 해주세요.\n[TERM:어슷썰기]\n2. 국물이 졸아들 때까지 끓여주세요.\n[TERM:졸이다]"
    print("--- 500개 규칙생성 데이터 예시 ---")
    print("원본:\n", sample)
    print("TTS용:\n", resolve_for_tts(sample))
    print("화면용:\n", resolve_for_display(sample))

    user_input = "무를 나박하게 썰어주세요\n양파는 어슷하게 썰어주세요\n국물이 졸아들 때까지 끓여주세요"
    print("\n--- 사용자 신규 등록 예시(변형 표현 포함) ---")
    tagged = auto_tag_terms(user_input)
    print("자동 태깅 결과:\n", tagged)
    print("TTS용:\n", resolve_for_tts(tagged))
