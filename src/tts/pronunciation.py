"""TTS에 넘기기 직전 텍스트에만 적용하는 발음 보정.

`infer.py`가 torch/qwen_tts를 모듈 최상단에서 import해서(GPU 없는 빠른 pytest 스위트가
못 돌게 됨), 순수 문자열 치환 로직만 별도 모듈로 뺐다.

"닭을"(ㄺ 겹받침 연음)이 이 체크포인트에서 "달근"/"딸을" 등으로 잘못 발음되는 걸 실측
확인(2026-08-19) — "달글"로 표기해서 넘기면 정상 발음됨(직접 청취 확인).
문장 전체를 g2pk/g2pk3(한국어 G2P 라이브러리)로 돌려서 일반화하는 것도 시도했으나,
"소금을 넣고"->"소그믈 러코"처럼 "~을/를 넣고" 같은 흔한 조리 표현에서 단어 경계를
잘못 넘나드는 버그가 두 라이브러리 모두에 있어(2026-08-19 실측, docs/decisions.md 참고)
채택하지 않았다. 대신 실제로 문제 확인된 단어만 정규식으로 직접 치환한다 — 문장의 나머지
부분은 안 건드리므로 G2P 라이브러리의 교차-단어 버그에 노출되지 않는다. 새 단어에서 같은
문제가 발견되면 이 딕셔너리에 추가하면 된다.
"""

from __future__ import annotations

import re

PRONUNCIATION_FIXES: dict[str, str] = {
    "닭을": "달글",
}

_PATTERN = re.compile("|".join(re.escape(k) for k in PRONUNCIATION_FIXES))


def apply_pronunciation_fixes(text: str) -> str:
    """TTS에 넘기기 직전에만 적용 — 화면 표시·로그·DB에 쓰이는 원문은 건드리지 않는다."""

    if not PRONUNCIATION_FIXES:
        return text

    return _PATTERN.sub(lambda m: PRONUNCIATION_FIXES[m.group(0)], text)
