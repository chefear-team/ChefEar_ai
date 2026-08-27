"""docs/specs/admin_voice_2fa.md — 화자검증 저장/검증 로직 + 챌린지 단어 매칭.

무거운 ECAPA 모델은 로드하지 않는다 — speaker_verify.embed()를 가짜로 바꿔서
enroll/verify의 저장·비교 로직만 검증한다(모델 실측은 별도 스모크 스크립트).
"""
from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture()
def sv(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_VOICEPRINT_FILE", str(tmp_path / "vp.json"))
    monkeypatch.setenv("ADMIN_VOICE_THRESHOLD", "0.55")
    import importlib

    from orchestration import speaker_verify as module

    module = importlib.reload(module)

    # audio -> 그 값을 시드로 한 결정적 단위벡터. 같은 시드면 같은 임베딩.
    def fake_embed(audio, sample_rate=None):
        seed = int(audio) if isinstance(audio, (int, float)) else abs(hash(str(audio))) % (2**31)
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(192).astype(np.float32)
        return v / np.linalg.norm(v)

    monkeypatch.setattr(module, "embed", fake_embed)
    return module


def test_verify_no_voiceprints_is_fail_closed(sv):
    """AC-06 / EC-04 — 등록된 성문이 없으면 무조건 실패."""
    ok, name, score = sv.verify(1)
    assert ok is False and name is None and score == 0.0


def test_enroll_then_verify_same_voice_passes(sv):
    """AC-02 — 같은 목소리(시드)로 등록·검증하면 통과."""
    sv.enroll("김철수", [1, 1, 1])
    assert sv.list_admins() == ["김철수"]
    ok, name, score = sv.verify(1)
    assert ok is True and name == "김철수" and score > 0.99


def test_verify_different_voice_rejected(sv):
    """AC-03 — 다른 목소리(다른 시드)는 threshold 미달로 거부."""
    sv.enroll("김철수", [10, 10, 10])
    ok, name, score = sv.verify(999)  # 무작위 다른 벡터 -> 코사인 ~0
    assert ok is False
    assert score < 0.55


def test_enroll_is_upsert_not_append(sv):
    """AC-08 — 같은 이름 재등록 시 행이 안 늘고 갱신만."""
    sv.enroll("김철수", [1, 1, 1])
    sv.enroll("김철수", [2, 2, 2])
    assert sv.list_admins() == ["김철수"]
    ok, _, _ = sv.verify(2)   # 최신 등록(시드 2)과 매칭
    assert ok is True
    ok_old, _, _ = sv.verify(1)
    assert ok_old is False


def test_multiple_admins_matched_by_identity(sv):
    sv.enroll("김철수", [1, 1, 1])
    sv.enroll("박영희", [50, 50, 50])
    assert sv.list_admins() == ["김철수", "박영희"]
    ok, name, _ = sv.verify(50)
    assert ok is True and name == "박영희"


def test_remove_admin(sv):
    sv.enroll("김철수", [1, 1, 1])
    assert sv.remove_admin("김철수") is True
    assert sv.remove_admin("없는사람") is False
    ok, _, _ = sv.verify(1)
    assert ok is False  # 다시 fail-closed


def test_enroll_rejects_empty(sv):
    with pytest.raises(ValueError):
        sv.enroll("", [1])
    with pytest.raises(ValueError):
        sv.enroll("김철수", [])


# ── 챌린지 단어 매칭 (admin_auth, 모델 무관) ──────────────────────────────

def test_challenge_word_matching():
    from ui.screens.admin_auth import _transcript_matches, _new_challenge

    ch = ["사과", "구름", "책상"]
    assert _transcript_matches("사과 구름 책상", ch) == (True, 3)
    assert _transcript_matches("사과, 구름, 책상입니다.", ch) == (True, 3)
    assert _transcript_matches("사과 구름", ch) == (True, 2)          # 2/3 허용
    assert _transcript_matches("사과 만 들림", ch)[0] is False        # 1/3 -> 실패
    assert _transcript_matches("전혀 다른 말", ch)[0] is False

    words = _new_challenge()
    assert len(words) == 3 and len(set(words)) == 3


def test_ip_rate_limit_lock_and_auto_forget():
    """IP 기준 5회 실패 -> 60초 잠금, 60초 지나면 IP 항목 삭제(개인정보 최소 보유).
    성공 시 즉시 삭제."""
    from ui.screens import admin_auth as m

    m._rate.clear()
    ip = "1.2.3.4"
    t = 1000.0

    for _ in range(4):
        m._record_failure(ip, t)
        assert m._cooldown_remaining(ip, t) == 0.0  # 아직 안 잠김
    m._record_failure(ip, t)  # 5번째 -> 잠금
    rem = m._cooldown_remaining(ip, t + 1)
    assert 58 <= rem <= 60

    # 잠금 안 풀린 동안 항목 유지
    assert ip in m._rate
    # 60초 지나면 조회 시 항목 삭제 + 잠금 해제
    assert m._cooldown_remaining(ip, t + 61) == 0.0
    assert ip not in m._rate

    # 실패 몇 번 후 60초 아무것도 안 하면 항목 소멸(카운터도 잊음)
    m._record_failure(ip, 2000.0)
    m._record_failure(ip, 2000.0)
    assert ip in m._rate
    m._cooldown_remaining(ip, 2000.0 + 61)  # prune 트리거
    assert ip not in m._rate

    # 성공 시 즉시 삭제
    m._record_failure(ip, 3000.0)
    m._forget_ip(ip)
    assert ip not in m._rate


def test_gate_tokens(monkeypatch):
    import streamlit as st

    monkeypatch.setenv("ADMIN_ACCESS_TOKEN", "adm-secret")
    monkeypatch.setenv("ADMIN_ENROLL_TOKEN", "enr-secret")
    import importlib
    import app as app_module

    app_module = importlib.reload(app_module)

    class _QP(dict):
        pass

    monkeypatch.setattr(st, "query_params", _QP(admin_key="adm-secret"))
    assert app_module._admin_gate_ok() is True
    assert app_module._enroll_gate_ok() is False
    monkeypatch.setattr(st, "query_params", _QP(enroll_key="enr-secret"))
    assert app_module._enroll_gate_ok() is True
    monkeypatch.setattr(st, "query_params", _QP(admin_key="wrong"))
    assert app_module._admin_gate_ok() is False
    monkeypatch.setattr(st, "query_params", _QP())  # 토큰 없음
    assert app_module._admin_gate_ok() is False
    assert app_module._enroll_gate_ok() is False


def test_admin_gate_fail_closed_when_token_unset(monkeypatch):
    """AC-07 — .env에 토큰이 아예 없으면 아무 값으로도 못 들어간다(fail-closed)."""
    import importlib

    import streamlit as st

    monkeypatch.delenv("ADMIN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_ENROLL_TOKEN", raising=False)
    import app as app_module

    app_module = importlib.reload(app_module)

    class _QP(dict):
        pass

    monkeypatch.setattr(st, "query_params", _QP(admin_key="anything", enroll_key="anything"))
    assert app_module._admin_gate_ok() is False
    assert app_module._enroll_gate_ok() is False


def test_admin_voice_trigger_phrase_matching():
    """옵션 A — "관리자 페이지 접근할게요" 류만 잡고 잡담은 안 잡는다."""
    from ui.dispatch import _is_admin_trigger

    for good in (
        "관리자 페이지 접근할게요",
        "관리자페이지 열어줘",
        "관리자 화면 보여줘",
        "관리자 권한으로 들어갈게",
        "어 관리자 모드로 가줘",
    ):
        assert _is_admin_trigger(good) is True, good
    for bad in (
        "된장찌개 레시피 알려줘",
        "관리자님 안녕하세요",       # "관리자"만 있고 페이지/화면/권한/모드/콘솔/접근 없음
        "다음 페이지로 넘어가줘",     # "페이지"만 있고 "관리자" 없음
        "",
    ):
        assert _is_admin_trigger(bad) is False, bad


def test_admin_trigger_sets_flag_and_reruns(monkeypatch):
    """process_utterance가 트리거 발화에 _admin_via_voice 플래그만 세우고 rerun."""
    import types

    import ui.dispatch as D

    class SS(dict):
        def __getattr__(self, k):
            try:
                return self[k]
            except KeyError:
                raise AttributeError(k)

        def __setattr__(self, k, v):
            self[k] = v

    class Rerun(Exception):
        pass

    ss = SS(pipeline_session={"current_recipe_id": None}, chat_log=[])
    fake_st = types.SimpleNamespace(session_state=ss)

    def _rerun():
        raise Rerun()

    fake_st.rerun = _rerun
    monkeypatch.setattr(D, "st", fake_st)
    # is_home_word / _REGISTER_WORD 안 걸리는 발화
    import pytest as _pytest

    with _pytest.raises(Rerun):
        D.process_utterance("관리자 페이지 접근할게요")
    assert ss["_admin_via_voice"] is True
