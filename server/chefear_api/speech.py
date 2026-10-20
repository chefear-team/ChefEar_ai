"""말할 문장과 음성 파일 키를 한곳에서 정한다.

서버(응답 음성 주소 결정), 목록 내보내기 스크립트(미리 만들 음성 목록), 추론 서버(등록 레시피 음성
생성)가 전부 이 모듈의 함수로 같은 문장 -> 같은 키를 만든다. 문장을 바꾸거나 목소리 모델을 바꾸면
VOICE_VERSION만 올리면 된다 — 키가 전부 새로 바뀌어 예전 음성이 잘못 재생되지 않는다.
"""
from __future__ import annotations

import hashlib

from orchestration.term_dict import resolve_for_tts

# 목소리 모델 버전(KSS LoRA epoch-13). 모델·발음 보정 규칙이 바뀌면 올린다.
VOICE_VERSION = "kss-ep13-v1"

COOKING_COMPLETE_MESSAGE = "요리가 완성됐어요! 수고하셨어요."
NO_PREVIOUS_MESSAGE = "1단계예요, 이전 단계가 없어요."
FIRST_STEP_MISSING_MESSAGE = "1단계 정보를 찾지 못했어요."
TEMPORARY_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 이용해 주세요."
UNHANDLED_MESSAGE = "죄송해요, 잘 처리하지 못했어요. 다시 한 번 말씀해주시겠어요?"
REGISTER_SAVED_MESSAGE = "저장이 완료됐어요!"
REGISTER_ASK_DISH_MESSAGE = "어떤 요리를 등록할까요? 요리 이름을 말씀해 주세요."
REGISTER_CONFIRM_GUESS_MESSAGE = "화면의 요리 이름이 맞으면 '네'라고 말씀해 주세요."
REGISTER_INGREDIENTS_MESSAGE = "화면에 재료를 입력해 주세요."
REGISTER_STEPS_MESSAGE = "화면에 조리 순서를 입력해 주세요."
LOGIN_REQUIRED_MESSAGE = "레시피 등록은 로그인한 뒤에 할 수 있어요."
REGISTER_LIMIT_MESSAGE = "오늘은 더 등록할 수 없어요. 내일 다시 시도해 주세요."

# orchestration/pipeline.py, intent_classifier.py에 있는 안내 문구와 같은 문장이어야 한다.
DISH_NOT_FOUND_MESSAGE = "등록되지 않은 레시피에요. 새로 등록을 원하시면 '레시피 등록'이라고 말씀해 주세요."
NOT_AVAILABLE_MESSAGE = "죄송해요, 이 레시피는 아직 등록되어 있지 않아요."
PENDING_MESSAGE = "등록 심사 중인 레시피예요. 승인되면 바로 조회할 수 있어요."
FALLBACK_UNCLASSIFIED = "죄송해요, 잘 이해하지 못했어요. 다시 한번 말씀해주시겠어요?"
FALLBACK_EMPTY = "다시 말씀해주세요."
FALLBACK_TOO_LONG = "말씀이 너무 길어요. 짧게 나눠서 말씀해 주세요."
FALLBACK_NEED_CONTEXT = "어떤 레시피에 대해 말씀하시는 건가요?"

FIXED_PHRASES: tuple[str, ...] = (
    COOKING_COMPLETE_MESSAGE,
    NO_PREVIOUS_MESSAGE,
    FIRST_STEP_MISSING_MESSAGE,
    TEMPORARY_ERROR_MESSAGE,
    UNHANDLED_MESSAGE,
    REGISTER_SAVED_MESSAGE,
    REGISTER_ASK_DISH_MESSAGE,
    REGISTER_CONFIRM_GUESS_MESSAGE,
    REGISTER_INGREDIENTS_MESSAGE,
    REGISTER_STEPS_MESSAGE,
    LOGIN_REQUIRED_MESSAGE,
    REGISTER_LIMIT_MESSAGE,
    DISH_NOT_FOUND_MESSAGE,
    NOT_AVAILABLE_MESSAGE,
    PENDING_MESSAGE,
    FALLBACK_UNCLASSIFIED,
    FALLBACK_EMPTY,
    FALLBACK_NEED_CONTEXT,
)


def audio_key(text: str) -> str:
    """말할 문장 -> 음성 파일 이름(확장자 제외). 같은 문장·같은 목소리 버전이면 항상 같은 값."""
    return hashlib.sha256(f"{VOICE_VERSION}\n{text}".encode("utf-8")).hexdigest()[:32]


def confirm_text(dish_name: str) -> str:
    """레시피를 찾았을 때 읽어 주는 확인 문장(기존 dispatch.py와 같은 문장)."""
    return f"{dish_name}, 조회수 1위 표준 레시피예요. 이걸로 시작할까요?"


def step_speech_text(step_text: str) -> str:
    """DB의 단계 원문([TERM:...] 태그 포함) -> 읽을 문장(용어 설명 포함).

    발음 보정(단계 번호 한글 낭독 등)은 tts_synthesize() 안에서 적용되므로 여기서 하지 않는다.
    """
    return resolve_for_tts(step_text)
