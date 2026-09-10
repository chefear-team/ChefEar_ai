"""FR-01/FR-15, 문서 7.2/6.6 — 임베딩 유사도 기반 의도분류(intent classification)."""
from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path

# transformers 라이브러리가 (안 써도 되는) TensorFlow 백엔드까지 불러오려다
# 이 개발 환경에서 충돌을 일으켜서, PyTorch만 쓰도록 강제로 꺼둔다.
# 우리 로직과는 무관한 순수 환경 설정이다.
os.environ.setdefault("USE_TF", "0")

import torch
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_CSV = PROJECT_ROOT / "data" / "intent_examples" / "기준예문.csv"
MODEL_NAME = "jhgan/ko-sroberta-multitask"  # 한국어 문장 임베딩에 특화된 모델(SDD 8.1 고정값)

# ── 판정 기준값 두 가지 ────────────────────────────────────────────────
# THRESHOLD: 1등 의도의 유사도가 이 값보다 낮으면 "그 어떤 의도와도 안 비슷하다"고
#            보고 미분류 처리한다. OI-09에 "착수 후 실측 튜닝 필요"라고 명시된
#            항목이라, 지금 값(0.5)은 일단 기능이 돌아가게 만든 개발용 임시값이다.
# MARGIN:    1등과 2등의 유사도 차이가 이 값보다 작으면(너무 근소한 차이면)
#            "어느 게 맞는지 확신 못 하겠다"고 보고 역시 미분류 처리한다.
#            이 값(0.05)은 문서 EC-02에 명시된 숫자를 그대로 썼다.
# 예) "다음"과 "다시"는 둘 다 "진행/재청취" 계열이라 실제로 유사도가 꽤 가까운데,
#     이때 아무거나 임의로 골라버리면 잘못된 진행을 할 위험이 있어서 차라리
#     "다시 한번 말씀해주시겠어요?"라고 되묻는 게 더 안전하다는 설계다.
THRESHOLD = 0.5
MARGIN = 0.05

VALID_INTENTS = {"조회", "등록", "진행", "재청취", "이전", "감탄사"}

FALLBACK_UNCLASSIFIED = "죄송해요, 잘 이해하지 못했어요. 다시 한번 말씀해주시겠어요?"
FALLBACK_EMPTY = "다시 말씀해주세요."
FALLBACK_NEED_CONTEXT = "어떤 레시피에 대해 말씀하시는 건가요?"


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """SentenceTransformer 모델을 최초 1회만 불러오고 이후엔 캐시된 걸 재사용한다.

    모델을 불러오는 작업(디스크에서 읽거나, 처음이면 인터넷에서 다운로드)은
    수 초~수십 초가 걸리는 무거운 작업이라, 매 발화마다 다시 불러오면
    응답이 느려진다. @lru_cache(maxsize=1)은 "인자 없이 호출하면 처음 결과를
    저장해뒀다가 다음부터는 그걸 그대로 돌려준다"는 뜻의 파이썬 표준 캐싱
    데코레이터다.
    """
    return SentenceTransformer(MODEL_NAME)


def _load_examples() -> list[tuple[str, str]]:
    """기준예문.csv를 읽어서 (의도, 예문 문장) 튜플 목록으로 만든다."""
    with EXAMPLES_CSV.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [(row["intent"], row["example"]) for row in reader if row["intent"] in VALID_INTENTS]


@lru_cache(maxsize=1)
def _example_embeddings():
    """모든 기준예문을 한 번에 임베딩(벡터화)해서 캐시해둔다.

    normalize_embeddings=True로 각 벡터의 길이(크기)를 1로 맞춘다(정규화).
    벡터 길이가 전부 1이면, 두 벡터의 내적(dot product) 값이 바로 코사인
    유사도와 같아진다 — 그래서 아래 classify_intent()에서 굳이 코사인 유사도
    공식을 따로 계산하지 않고 "@"(행렬곱) 연산 한 줄로 끝낼 수 있다.
    """
    pairs = _load_examples()
    intents = [p[0] for p in pairs]
    examples = [p[1] for p in pairs]
    embeddings = _get_model().encode(examples, normalize_embeddings=True)
    return intents, examples, embeddings


def _pick_intent(ranked: list[tuple[str, tuple[float, str]]], context_recipe_id: str | None) -> dict:
    """유사도 점수가 이미 계산된 뒤, threshold/margin/EC-05 규칙만으로 최종 응답을 결정한다."""
    top_intent, (top_score, top_example) = ranked[0]

    if os.environ.get("CHEFEAR_DEBUG"):
        second_str = f"{ranked[1][0]}={ranked[1][1][0]:.3f}" if len(ranked) > 1 else "N/A"
        print(f"[classify_intent] 1위: {top_intent}={top_score:.3f} (2위: {second_str}) 문장='{top_example}'")

    if top_score < THRESHOLD:
        # EC-01 / AC-02: 1등마저 threshold 미만 -> 아예 감이 안 잡히는 발화
        return {"intent": "미분류", "similarity_score": top_score, "fallback_message": FALLBACK_UNCLASSIFIED}

    if len(ranked) > 1:
        second_score = ranked[1][1][0]
        if (top_score - second_score) < MARGIN:
            # 6.6 / AC-10: threshold는 넘었지만 1등과 2등이 너무 근소한 차이 ->
            # 임의로 아무거나 채택하지 않고 미분류 처리(재질문).
            # EC-02가 말하는 "근접 후보를 로그로 남겨서 나중에 기준예문 보강에
            # 참고하자"는 취지는 이 print()로 살려뒀다. (EC-02 원문은 "그래도
            # 1등을 채택하라"고 하는데, 6.6 본문과 AC-10은 정반대로 "미분류
            # 처리하라"고 한다 — 둘이 모순돼서, 더 상세하고 최신인 6.6/AC-10을
            # 따르기로 판단했다. docs/ 보고 내용 참고.)
            print(
                f"[classify_intent] margin 미충족: {ranked[0][0]}={top_score:.3f} "
                f"vs {ranked[1][0]}={second_score:.3f}"
            )
            return {"intent": "미분류", "similarity_score": top_score, "fallback_message": FALLBACK_UNCLASSIFIED}

    if top_intent == "등록" and context_recipe_id:
        return {"intent": "미분류", "similarity_score": top_score, "fallback_message": FALLBACK_UNCLASSIFIED}

    if top_intent == "조회" and context_recipe_id:
        return {"intent": "미분류", "similarity_score": top_score, "fallback_message": FALLBACK_UNCLASSIFIED}

    return {"intent": top_intent, "similarity_score": top_score, "matched_example": top_example}


def classify_intent(utterance: str, context_recipe_id: str | None = None) -> dict:
    """사용자 발화 한 문장을 받아서 의도를 분류한다. 7.2 상세 명세.

    EC-01~05, AC-01/02/09/10 대응. 이 함수 자체는 "임베딩 계산 + 순위 매기기"만
    담당하고, 실제 판정(threshold/margin 비교)은 _pick_intent()에 위임한다.
    """
    if not utterance or not utterance.strip():
        # EC-04: STT가 아예 아무 말도 못 알아들어서 빈 문자열이 온 경우.
        # 이럴 땐 임베딩 계산 자체가 의미 없으니(빈 문장을 벡터화해봐야 소용없음)
        # 모델을 부르지 않고 바로 반환한다 — 문서가 말하는 "classify_intent 호출
        # 자체를 생략"하는 취지를 함수 안에서 조기 반환으로 구현한 것.
        return {"intent": "미분류", "similarity_score": 0.0, "fallback_message": FALLBACK_EMPTY}

    intents, examples, example_embeddings = _example_embeddings()
    normalized = utterance.strip().rstrip("?!.,~ ")
    query_embedding = _get_model().encode([normalized or utterance], normalize_embeddings=True)[0]
    scores = example_embeddings @ query_embedding

    # 같은 의도에 예문이 여러 개 있을 수 있으므로(예: "진행" 의도 예문이 7개),
    # 의도별로 "제일 잘 맞는 예문 하나"만 남긴다(최근접 이웃(nearest neighbor) 방식).
    best_per_intent: dict[str, tuple[float, str]] = {}
    for intent, example, score in zip(intents, examples, scores):
        score = float(score)
        current = best_per_intent.get(intent)
        if current is None or score > current[0]:
            best_per_intent[intent] = (score, example)

    # 유사도 점수가 높은 의도부터 순서대로 정렬 -> ranked[0]이 1등, ranked[1]이 2등.
    ranked = sorted(best_per_intent.items(), key=lambda kv: kv[1][0], reverse=True)
    return _pick_intent(ranked, context_recipe_id)
