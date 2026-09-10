"""entity_extract_llm.py 테스트 — generate_json()을 모킹해서 extract_dish_name_llm()의
파싱/방어 로직만 검증한다(Spec AC-01/AC-02, `docs/specs/llm_dish_name_extract.md`).
`generate_json()` 자체의 JSON 파싱 방어 로직은 `tests/test_llm_infer.py`가 따로 검증한다.
"""
from orchestration import entity_extract_llm


def test_extracts_dish_name(monkeypatch):
    monkeypatch.setattr(entity_extract_llm, "generate_json", lambda prompt: {"dish_name": "된장찌개"})

    assert entity_extract_llm.extract_dish_name_llm("된장찌개 어떻게 만들어?") == "된장찌개"


def test_no_dish_name_returns_none(monkeypatch):
    monkeypatch.setattr(entity_extract_llm, "generate_json", lambda prompt: {"dish_name": None})

    assert entity_extract_llm.extract_dish_name_llm("다음 단계로 넘어가줘") is None


def test_server_failure_returns_none(monkeypatch):
    monkeypatch.setattr(entity_extract_llm, "generate_json", lambda prompt: None)

    assert entity_extract_llm.extract_dish_name_llm("된장찌개 어떻게 만들어?") is None


def test_malformed_dish_name_type_returns_none(monkeypatch):
    monkeypatch.setattr(entity_extract_llm, "generate_json", lambda prompt: {"dish_name": 123})

    assert entity_extract_llm.extract_dish_name_llm("아무 발화") is None


def test_blank_dish_name_returns_none(monkeypatch):
    monkeypatch.setattr(entity_extract_llm, "generate_json", lambda prompt: {"dish_name": "   "})

    assert entity_extract_llm.extract_dish_name_llm("아무 발화") is None


def test_empty_utterance_short_circuits_without_calling_llm(monkeypatch):
    called = []
    monkeypatch.setattr(entity_extract_llm, "generate_json", lambda prompt: called.append(prompt))

    assert entity_extract_llm.extract_dish_name_llm("   ") is None
    assert called == []


def test_whitespace_and_trailing_punctuation_stripped_before_llm(monkeypatch):
    """LLM에 넘기는 사본은 띄어쓰기뿐 아니라 끝 문장부호도 제거돼야
    한다(intent_classifier.py::classify_intent의 `.rstrip("?!.,~ ")`와 같은 정규화).
    실제로 프롬프트에 어떤 문자열이 박히는지 직접 확인한다.
    """
    prompts = []
    monkeypatch.setattr(
        entity_extract_llm,
        "generate_json",
        lambda prompt: prompts.append(prompt) or {"dish_name": "된장찌개", "wants_register": False},
    )

    entity_extract_llm.extract_intent_llm("된장찌개 어떻게 만들어?  ")

    assert len(prompts) == 1
    # 프롬프트 템플릿 자체(규칙 설명)에 "된장찌개 어떻게 만들어?"라는 예시 문구가 이미
    # 들어있어서(그건 원래 있어야 하는 정상 텍스트) 전체 프롬프트에 "만들어?"가 없다고
    # 단정하면 안 된다 — 실제로 발화가 채워지는 맨 끝 "발화: ..." 줄만 정확히 확인한다.
    assert prompts[0].endswith('발화: "된장찌개어떻게만들어"\n답:')


def test_wants_register_true_when_llm_confirms(monkeypatch):
    monkeypatch.setattr(
        entity_extract_llm, "generate_json", lambda prompt: {"dish_name": None, "wants_register": True}
    )

    assert entity_extract_llm.extract_intent_llm("등록해줘") == {"dish_name": None, "wants_register": True}


def test_wants_register_false_alongside_dish_name(monkeypatch):
    monkeypatch.setattr(
        entity_extract_llm, "generate_json", lambda prompt: {"dish_name": "된장찌개", "wants_register": False}
    )

    result = entity_extract_llm.extract_intent_llm("된장찌개 어떻게 만들어?")
    assert result == {"dish_name": "된장찌개", "wants_register": False}


def test_wants_register_defaults_false_when_key_missing(monkeypatch):
    # generate_json()이 wants_register 키 자체를 안 준 경우(구형 응답 형식 등)에도 죽지 않고 False로.
    monkeypatch.setattr(entity_extract_llm, "generate_json", lambda prompt: {"dish_name": None})

    result = entity_extract_llm.extract_intent_llm("아무 발화")
    assert result == {"dish_name": None, "wants_register": False}


def test_wants_register_defaults_false_on_llm_failure(monkeypatch):
    monkeypatch.setattr(entity_extract_llm, "generate_json", lambda prompt: None)

    result = entity_extract_llm.extract_intent_llm("아무 발화")
    assert result == {"dish_name": None, "wants_register": False}


def test_extract_dish_name_llm_is_thin_wrapper_over_extract_intent_llm(monkeypatch):
    # 기존 extract_dish_name_llm() 호출부(app.py, tests/test_ui.py)와의 하위 호환 확인.
    monkeypatch.setattr(
        entity_extract_llm, "generate_json", lambda prompt: {"dish_name": "잡채", "wants_register": True}
    )

    assert entity_extract_llm.extract_dish_name_llm("잡채 어떻게 만들어?") == "잡채"
