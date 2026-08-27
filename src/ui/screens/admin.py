"""ChefEar 관리자 페이지 — docs/specs/admin_recipe_approval.md (Phase 1).

로그인 버튼 대신 `.env`의 `ADMIN_ACCESS_TOKEN` 토큰 게이트로 접근한다(`app.py::
_admin_gate_ok()` 참고) — 화자검증(ECAPA-TDNN)은 Phase 2로 미뤄뒀다.

독립 Streamlit 페이지(`st.navigation`)로 분리한 이유: 일반 화면들과 같은 스크립트/
세션 안에 두면 Streamlit 화면 전환 잔상 버그(streamlit/streamlit#8360)를 그대로
물려받는다(`docs/specs/remove_user_accounts.md`의 Why 참고) — 대신 페이지 이동에
따르는 마이크(webrtc) 재연결 비용은 감수하기로 했다. 이 화면 자체는 마이크를 전혀
쓰지 않는다(승인 대기 목록을 보고 버튼만 누르는 화면).
"""
from __future__ import annotations

import streamlit as st

from orchestration.db import get_client
from orchestration.registration import delete_recipe


def _pending_recipes(client) -> list[dict]:
    """approved == 'N'인 레시피 전체를 최신 등록순으로 가져온다.

    2026-08-27 수정 — 조회(select_standard_recipe)가 source 구분 없이 approved
    값만 보고 공개 여부를 가르는 것과 똑같이, 관리자 승인 대기 목록도 source와
    무관하게 approved == 'N'인 행은 전부 보여준다(원래는 source == 'user_custom'도
    같이 걸어서, api_standard 행의 approved를 수동으로 'N'으로 바꾼 경우 목록에
    안 잡히는 문제가 있었음 — 실측 확인).
    """
    res = client.table("recipes").select("*").eq("approved", "N").execute()
    rows = res.data or []
    return sorted(rows, key=lambda r: r.get("created_at", ""), reverse=True)


def _approve(recipe_id: str, client) -> None:
    client.table("recipes").update({"approved": "Y"}).eq("id", recipe_id).execute()


def render_admin() -> None:
    st.markdown("## 🍲 ChefEar 관리자")
    st.caption("승인 대기 중인 신규 등록 레시피를 검토합니다.")
    st.divider()

    client = get_client()
    pending = _pending_recipes(client)

    if not pending:
        st.info("승인 대기 중인 레시피가 없어요.")
        return

    for row in pending:
        recipe_id = row["id"]
        # 2026-08-27 요청 — 목록이 길어지는 문제로 카드 전체를 접이식(expander)으로
        # 바꿨다. 기본은 닫힌 상태(요리명 한 줄씩)로, 클릭하면 재료/조리순서/버튼이 열린다.
        with st.expander(row.get("dish_name", "(이름 없음)")):
            st.write(f"**재료**: {row.get('ingredients', '')}")

            steps_res = (
                client.table("recipe_steps")
                .select("*")
                .eq("recipe_id", recipe_id)
                .order("step_number")
                .execute()
            )
            steps = steps_res.data or []
            if steps:
                st.write("**조리순서**")
                for step in steps:
                    st.write(f"{step['step_number']}. {step['step_text']}")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("등록", key=f"admin_approve_{recipe_id}", type="primary", use_container_width=True):
                    _approve(recipe_id, client)
                    st.rerun()
            with c2:
                if st.button("삭제", key=f"admin_delete_{recipe_id}", use_container_width=True):
                    delete_recipe(recipe_id, client=client)
                    st.rerun()
