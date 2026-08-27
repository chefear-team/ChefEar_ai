"""ChefEar 관리자 목소리 등록(enrollment) 화면 — docs/specs/admin_voice_2fa.md.

`?enroll_key=<ADMIN_ENROLL_TOKEN>` 로만 열리는 별도 페이지(`app.py::_enroll_gate_ok()`).
이름 + 짧은 발화 3개를 녹음하면 ECAPA-TDNN 임베딩 평균을 성문으로 저장한다.
등록/재등록만 하고, 검증 자체는 `admin_auth.py`가 한다.
"""
from __future__ import annotations

import streamlit as st

_N_SAMPLES = 3
_EXAMPLE_SENTENCES = (
    "안녕하세요 저는 오늘 저녁으로 김치찌개를 만들 거예요",
    "냉장고에 두부하고 애호박이 있어서 된장찌개도 좋겠네요",
    "밥은 이미 지어놨고 이제 재료만 손질하면 됩니다",
)


def render_admin_enroll() -> None:
    from orchestration import speaker_verify

    st.markdown("## 🎙️ 관리자 목소리 등록")
    st.caption(
        "이름과 짧은 발화 3개를 녹음하면 관리자 페이지 음성 인증에 쓰입니다. "
        "조용한 곳에서, 평소 말투로 녹음해 주세요."
    )

    existing = speaker_verify.list_admins()
    if existing:
        st.info("등록된 관리자: " + ", ".join(existing))

    st.divider()
    name = st.text_input("이름", placeholder="예: 권석욱").strip()

    st.write(f"아래 문장을 하나씩 읽어 **{_N_SAMPLES}개** 녹음해 주세요 (각 3~5초):")
    samples = []
    for i in range(_N_SAMPLES):
        st.markdown(f"**{i + 1}.** {_EXAMPLE_SENTENCES[i % len(_EXAMPLE_SENTENCES)]}")
        rec = st.audio_input(f"녹음 {i + 1}", key=f"enroll_sample_{i}", label_visibility="collapsed")
        if rec is not None:
            samples.append(rec.getvalue())

    ready = bool(name) and len(samples) == _N_SAMPLES
    if not ready:
        st.caption(f"이름 입력 + 녹음 {_N_SAMPLES}개가 모두 필요합니다. (현재 녹음 {len(samples)}개)")

    if st.button("등록", type="primary", disabled=not ready, use_container_width=True):
        try:
            with st.spinner("성문을 만드는 중..."):
                speaker_verify.enroll(name, samples)
            st.success(f"등록됨: {name}")
            print(f"[admin_enroll] 등록/갱신: {name} ({_N_SAMPLES} samples)", flush=True)
        except Exception as exc:  # noqa: BLE001
            st.error(f"등록에 실패했어요: {exc}")
            print(f"[admin_enroll] 실패: {exc!r}", flush=True)

    with st.expander("관리자 삭제"):
        if not existing:
            st.caption("삭제할 관리자가 없습니다.")
        for admin_name in existing:
            c1, c2 = st.columns([3, 1])
            c1.write(admin_name)
            if c2.button("삭제", key=f"enroll_del_{admin_name}"):
                speaker_verify.remove_admin(admin_name)
                print(f"[admin_enroll] 삭제: {admin_name}", flush=True)
                st.rerun()
