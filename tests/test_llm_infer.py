"""llm/infer.py 테스트 — 실제 EXAONE 가중치를 로드하지 않고 generate_response()를
모킹해서 generate_json()의 파싱 로직만 검증한다(EC-03, `docs/specs/llm_dish_name_extract.md`).
모델 로드(load_llm())/실제 추론은 GPU 데스크탑에서 별도로 확인해야 한다(unit test 범위 밖).
"""
import json

from llm import infer


def test_generate_json_success(monkeypatch):
    monkeypatch.setattr(infer, "generate_response", lambda prompt, **kw: json.dumps({"dish_name": "된장찌개"}))

    assert infer.generate_json("아무 프롬프트") == {"dish_name": "된장찌개"}


def test_generate_json_strips_markdown_code_fence(monkeypatch):
    """실측(2026-08-20, GPU 데스크탑 실제 EXAONE 추론)에서 확인된 실제 응답 형태 —
    프롬프트가 "다른 말은 덧붙이지 않는다"고 명시해도 ```json ... ``` 로 감싸서 답함."""
    fenced = '```json\n{"dish_name": "된장찌지게"}\n```'
    monkeypatch.setattr(infer, "generate_response", lambda prompt, **kw: fenced)

    assert infer.generate_json("아무 프롬프트") == {"dish_name": "된장찌지게"}


def test_generate_json_malformed_response_returns_none(monkeypatch):
    monkeypatch.setattr(infer, "generate_response", lambda prompt, **kw: "이건 JSON이 아니라 그냥 설명이에요")

    assert infer.generate_json("아무 프롬프트") is None


def test_generate_json_passes_through_max_new_tokens(monkeypatch):
    seen = {}

    def fake_generate_response(prompt, **kwargs):
        seen.update(kwargs)
        return json.dumps({"dish_name": None})

    monkeypatch.setattr(infer, "generate_response", fake_generate_response)

    infer.generate_json("아무 프롬프트", max_new_tokens=32)

    assert seen["max_new_tokens"] == 32
