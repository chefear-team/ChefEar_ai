"""FR-01/FR-15, 문서 7.2/6.6 — 임베딩 유사도 기반 의도분류(intent classification).

## 이 파일이 하는 일 (개념 설명)

사용자가 "다음"이라고 말하면 그게 "다음 단계로 진행해줘"라는 뜻인지 어떻게
알까? ChatGPT 같은 LLM에 "이 문장의 의도가 뭐야?"라고 매번 물어볼 수도 있지만,
이 프로젝트는 서비스가 실행되는 동안 외부 LLM API를 호출하면 안 된다는 원칙이
있다(1.5 원칙 — 강사 가이드 위반). 그래서 대신 "임베딩 유사도 매칭"이라는
훨씬 가벼운 방법을 쓴다.

1. "의도별 예문 세트"를 미리 준비해둔다. 예를 들어 "진행" 의도에는
   "다음", "다음꺼", "넥스트" 같은 예문들이 있다(data/intent_examples/기준예문.csv).
2. sentence-transformers 모델(jhgan/ko-sroberta-multitask)로 문장을 숫자
   벡터(임베딩)로 바꾼다. 의미가 비슷한 문장은 벡터도 비슷한 방향을 가리키게
   학습된 모델이다.
3. 사용자가 실제로 말한 문장도 같은 방식으로 벡터로 바꾼다.
4. 사용자 발화 벡터와 모든 예문 벡터 사이의 "코사인 유사도"(두 벡터가 얼마나
   같은 방향을 가리키는지, -1~1 사이 값. 1에 가까울수록 의미가 비슷함)를 계산해서,
   가장 유사도가 높은 예문이 속한 의도를 채택한다.

이 방식은 LLM 호출이 아니라 그냥 벡터 내적(dot product) 계산이라 매우
빠르고, 서버 비용도 안 든다.
"""
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

VALID_INTENTS = {"조회", "등록", "진행", "재청취", "이전", "재료대체", "취소", "감탄사"}
# 2026-08-26 추가 — "감탄사"(감사합니다/아멘/고마워요 등)만 새로 추가. "긍정"(응/네/좋아
# 등, 기준예문.csv엔 있지만 여기 화이트리스트엔 의도적으로 빠져있음 — my_recipes.py
# 관련 코드가 아니라 recipe_confirm 등 화면이 직접 문자열 비교로 처리하기로 이미
# 결정된 사항, dispatch.py::process_utterance() 주석 참고)는 그대로 안 건드린다.

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
    """유사도 점수가 이미 계산된 뒤, threshold/margin/EC-05 규칙만으로 최종 응답을 결정한다.

    classify_intent()에서 이 부분만 따로 함수로 뺀 이유: 임베딩 계산(모델 로딩,
    벡터화)은 무겁고 진짜 모델이 있어야 테스트할 수 있지만, "1등/2등 점수가
    이럴 때 어떤 결과를 내야 하는가"라는 판단 로직 자체는 순수하게 숫자
    비교일 뿐이라 가짜 점수를 손으로 만들어서도 테스트할 수 있다
    (tests/test_intent_classifier.py의 test_pick_intent_* 참고). 이렇게
    "계산이 오래 걸리는 부분"과 "순수 로직 부분"을 나누는 건 테스트를 쉽게
    만드는 흔한 설계 패턴이다.

    ranked는 [(의도, (유사도 점수, 매칭된 예문 문장)), ...] 형태이고,
    유사도 점수가 높은 순으로 이미 정렬돼 있다고 가정한다.
    """
    top_intent, (top_score, top_example) = ranked[0]

    # 2026-08-25 임시 진단 로그 — "메롱"처럼 의미 없는 발화가 실제로 어떤 의도/점수로
    # 판정되는지 확인하기 위함(margin 미충족일 때만 찍히던 기존 print()로는 threshold
    # 미달로 조용히 미분류된 건지, 아니면 threshold+margin을 둘 다 넘겨서 실제로
    # 채택된 건지 구분이 안 됐다 — "말도 안 되는 발화인데 직전 명령이 반복 실행된다"는
    # 실측 리포트, 2026-08-25). 원인 확인되면 지울 것.
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

    if top_intent == "재료대체" and not context_recipe_id:
        # EC-05: "바지락 넣어도 돼?"처럼 재료대체 의도로 보이지만, 지금 어떤
        # 레시피를 진행 중인지(context_recipe_id)를 모르면 뭘 대체해야 할지
        # 알 수 없다. 이럴 땐 의도 분류 자체는 맞았어도 실행할 수 없으니
        # 되물어야 한다.
        return {"intent": "미분류", "similarity_score": top_score, "fallback_message": FALLBACK_NEED_CONTEXT}

    if top_intent == "등록" and context_recipe_id:
        # 2026-08-26 요청 — "등록"은 아직 아무 레시피도 안 고른 첫 화면에서만 의미
        # 있는 의도다("등록은 첫 페이지 아니면 의미없는 문구다"). 그런데 실측 로그로
        # "다음 단계 알려줘"류 조리 중 발화가 "진행"과 근소한 차이로 "등록" 예문과도
        # 계속 비슷하게 잡히는 게 확인됐다(예: 진행=0.435 vs 등록=0.404) — margin
        # 미달로 대부분은 미분류로 걸러지지만, 운 좋게(?) margin을 넘기면 조리
        # 흐름 중간에 뜬금없이 등록 화면으로 튕겨나간다. 위 재료대체(EC-05)와 같은
        # 자리에서, 이미 레시피를 진행 중(context_recipe_id 있음)이면 "등록"으로
        # 분류됐어도 미분류로 되돌려 무시한다. 사용자가 "등록"이라는 단어를 직접
        # 말하는 경로(dispatch.py::_REGISTER_WORD)는 이 함수를 거치지 않는 별도
        # 분기라 화면과 무관하게 여전히 동작한다 — 명시적 단어 vs 애매한 임베딩
        # 매칭을 다르게 취급하는 것.
        return {"intent": "미분류", "similarity_score": top_score, "fallback_message": FALLBACK_UNCLASSIFIED}

    if top_intent == "조회" and context_recipe_id:
        # 2026-08-26 실측 리포트 — 조리 3단계("돼지고기와 새우젓을 손질해주세요") 중에
        # "돼지고기과?"라고만 말했더니 "돼지고기"를 새 요리명으로 보고 완전히 새로운
        # 조회를 시작해서 김치찌개 조리가 처음부터 다시 시작된 것처럼 리셋됐다. 처음엔
        # "한 단어짜리 발화만" 막았는데("된장찌개로 바꿔줘"류 명시적 전환 요청은 허용),
        # 재요청으로 원칙이 바뀌었다: "레시피 전환이 되면 안 된다, 절대로" — 조리 중엔
        # 문장이 아무리 명확해도("된장찌개로 바꿔줘", "이제 된장찌개 만들래") 음성으로
        # 다른 레시피로 넘어가는 길 자체를 완전히 막는다. 다른 레시피를 원하면 "처음"으로
        # 돌아가서(reset_to_start(), is_home_word() 경로 — 이 함수를 안 거치는 별개 경로라
        # 여전히 동작함) 초기 화면에서 다시 검색해야 한다 — 그게 유일한 전환 경로다.
        # 이유: "조회" 분기(pipeline.py)가 조건 없이 session["current_recipe_id"]를
        # 덮어써서(무슨 요리를 진행 중이었는지 확인/경고 절차가 전혀 없음), 확실한
        # 전환 요청과 애매한 재료명 언급을 임베딩 유사도만으로 구분하는 건 근본적으로
        # 신뢰할 수 없다고 판단 — "된장찌개"(요리명 단독) 0.915, "돼지고기"(재료명 단독)
        # 0.619로 오히려 애매한 쪽이 더 낮게 나오는 경우까지 실측된 상태(intent_classifier.py
        # 관련 대화 참고), 문장 길이/명확성으로 안전하게 가를 수 있는 문제가 아니다.
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
    # 2026-08-25 추가 — STT가 "그래?"처럼 평서/응답 발화에도 끝에 물음표를 붙이는 경우가
    # 흔한데(라이징 인토네이션을 의문문으로 오인), 기준예문.csv 쪽 예문엔 이런 문장부호가
    # 거의 없다. 그 결과 끝에 "?"/"!"가 붙었을 뿐인 같은 의미의 발화가 예문과 미묘하게
    # 다른 임베딩이 되어 margin이 근소하게(0.05 미만) 갈리는 사례가 실측 확인됐다
    # ("그래?" -> 진행=0.616 vs 재청취=0.609, margin=0.007로 미분류 처리). is_home_word()가
    # 이미 하는 것과 같은 정규화(끝 문장부호 제거)를 여기서도 적용해 분류용 벡터만 이
    # 노이즈를 안 타게 한다 — chat_log 표시나 다른 후처리에 쓰는 원본 utterance는 그대로 둔다.
    normalized = utterance.strip().rstrip("?!.,~ ")
    query_embedding = _get_model().encode([normalized or utterance], normalize_embeddings=True)[0]
    # 2026-08-25 — src/stt/infer.py::stt_transcribe()와 같은 이유(그쪽 주석 참고) — STT/
    # LLM/TTS/임베딩(이 함수)이 12GB GPU를 같이 써서 유휴 상태에도 VRAM 여유가 500MB
    # 미만이다. 가중치는 그대로 두고(재로딩 없음) 이번 encode()가 남긴 미사용 캐시만 반환한다.
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    # example_embeddings의 shape는 (예문 개수, 768), query_embedding은 (768,).
    # 행렬 @ 벡터 연산을 하면 예문 하나하나와 query 사이의 내적(=코사인 유사도,
    # 위 _example_embeddings() 설명 참고)이 한 번에 배열로 나온다. for문 없이
    # numpy가 벡터 연산을 훨씬 빠르게 처리해준다.
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
