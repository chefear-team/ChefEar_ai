"""ChefEar 사용자용 소개(랜딩) 페이지."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="ChefEar", page_icon="🍳", layout="wide", initial_sidebar_state="collapsed")

st.markdown(
    """
<style>
:root {
  --bg: #f7f1e6;
  --surface: #ffffff;
  --surface-alt: #fbf6ec;
  --border: #ece1cc;
  --text: #241c15;
  --text-secondary: #8b7e6c;
  --text-faint: #b3a690;
  --accent: #ee7b36;
  --accent-dark: #d9631f;
  --accent-soft: #fbebd3;
  --accent-soft-text: #ac6a28;
  --positive-bg: #e3efd3;
  --positive-text: #4b7a34;
}

#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
[data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stAppViewContainer"] { background: var(--bg); }
.block-container { max-width: 980px; padding-top: 2.5rem; padding-bottom: 4rem; }

html, body, [class*="css"] {
  font-family: "Pretendard", -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
  color: var(--text);
}

/* 히어로 */
.hero { text-align: center; padding: 20px 0 8px; }
.hero .logo { font-size: 52px; line-height: 1; margin-bottom: 10px; }
.hero h1 {
  font-size: 40px;
  font-weight: 800;
  letter-spacing: -0.5px;
  margin: 0 0 12px;
  color: var(--text);
}
.hero p.tagline {
  font-size: 18px;
  font-weight: 600;
  color: var(--accent-dark);
  margin: 0 0 14px;
}
.hero p.desc {
  font-size: 15.5px;
  color: var(--text-secondary);
  line-height: 1.7;
  max-width: 620px;
  margin: 0 auto;
}
.badge-row {
  display:flex;
  justify-content:center;
  gap:8px;
  margin-top:22px;
  flex-wrap:wrap;
}
.badge {
  display:inline-flex;
  align-items:center;
  gap:6px;
  background:var(--accent-soft);
  color:var(--accent-soft-text);
  border-radius:999px;
  padding:7px 16px;
  font-size:13px;
  font-weight:700;
}

/* 섹션 공통 */
.section { margin-top: 64px; }
.section-label {
  text-align:center;
  font-size:13px;
  font-weight:800;
  letter-spacing:1.5px;
  color:var(--accent);
  text-transform:uppercase;
  margin-bottom:8px;
}
.section-title {
  text-align:center;
  font-size:26px;
  font-weight:800;
  margin:0 0 12px;
  color:var(--text);
}
.section-sub {
  text-align:center;
  font-size:14.5px;
  color:var(--text-secondary);
  max-width:560px;
  margin:0 auto 32px;
  line-height:1.65;
}

/* 카드 */
.card-grid {
  display:grid;
  grid-template-columns:repeat(auto-fit, minmax(230px, 1fr));
  gap:14px;
}
.card-grid-2 {
  display:grid;
  grid-template-columns:repeat(2, 1fr);
  gap:14px;
}
.card-grid-2 > .card:last-child:nth-child(odd) {
  grid-column: 1 / -1;
  width: calc((100% - 14px) / 2);
  justify-self: center;
}
.card-grid-2 .card {
  text-align: center;
}
.card {
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:18px;
  padding:22px 20px;
  box-shadow:0 6px 18px rgba(36,28,21,0.05);
}
.card .icon {
  font-size:26px;
  margin-bottom:10px;
  display:block;
}
.card h4 {
  font-size:15.5px;
  font-weight:800;
  margin:0 0 6px;
}
.card p {
  font-size:13.5px;
  color:var(--text-secondary);
  line-height:1.6;
  margin:0;
}

/* 대화 */
.scenario {
  background:var(--surface);
  border-radius:22px;
  padding:26px 28px;
  box-shadow:0 10px 24px rgba(36,28,21,0.06);
  max-width:560px;
  margin:0 auto;
}
.bubble {
  display:flex;
  margin-bottom:14px;
}
.bubble:last-child {
  margin-bottom:0;
}
.bubble .msg {
  border-radius:16px;
  padding:10px 15px;
  font-size:14px;
  line-height:1.55;
  max-width:82%;
}
.bubble.user {
  justify-content:flex-end;
}
.bubble.user .msg {
  background:var(--accent);
  color:#fff;
  border-bottom-right-radius:4px;
}
.bubble.ai .msg {
  background:var(--surface-alt);
  color:var(--text);
  border-bottom-left-radius:4px;
}

/* 사용 흐름 */
.flow {
  display:flex;
  align-items:center;
  justify-content:center;
  flex-wrap:wrap;
  gap:6px;
}
.flow .step {
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:999px;
  padding:9px 16px;
  font-size:13px;
  font-weight:700;
  color:var(--text);
  box-shadow:0 4px 10px rgba(36,28,21,0.04);
}
.flow .arrow {
  color:var(--text-faint);
  font-size:15px;
}

/* 숫자 */
.stat-grid {
  display:grid;
  grid-template-columns:repeat(auto-fit, minmax(150px, 1fr));
  gap:14px;
}
.stat {
  background:var(--surface-alt);
  border-radius:18px;
  padding:20px;
  text-align:center;
}
.stat .num {
  font-size:26px;
  font-weight:800;
  color:var(--accent-dark);
}
.stat .label {
  font-size:12.5px;
  color:var(--text-secondary);
  margin-top:4px;
}

/* 차이점 */
.diff-row {
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:12px;
  background:var(--surface);
  border-radius:16px;
  padding:16px 18px;
  margin-bottom:10px;
  box-shadow:0 4px 12px rgba(36,28,21,0.04);
}
.diff-row .old {
  color:var(--text-faint);
  font-size:13.5px;
}
.diff-row .old::before {
  content:"기존 ";
  font-weight:700;
  color:var(--text-secondary);
}
.diff-row .new {
  color:var(--positive-text);
  font-size:13.5px;
  font-weight:600;
}
.diff-row .new::before {
  content:"ChefEar ";
  font-weight:700;
}

/* 안내 */
.principle {
  background:var(--positive-bg);
  color:var(--positive-text);
  border-radius:18px;
  padding:18px 22px;
  text-align:center;
  font-size:14px;
  font-weight:600;
  line-height:1.6;
  max-width:640px;
  margin:0 auto;
}

.footer-note {
  text-align:center;
  color:var(--text-faint);
  font-size:12.5px;
  margin-top:60px;
}
</style>
""",
    unsafe_allow_html=True,
)

# 1. 메인 소개
st.markdown(
    """
<div class="hero">
  <div class="logo">🍳</div>
  <h1>ChefEar</h1>
  <p class="tagline">화면 대신, 목소리로 완성하는 요리</p>
  <p class="desc">요리가 처음이어도 괜찮아요. 손이 젖거나 조리 중 화면을 보기 어려울 때, ChefEar에게 말하면 필요한 레시피를 한 단계씩 안내해드려요.</p>
  <div class="badge-row">
    <span class="badge">🎙️ 말로 레시피 찾기</span>
    <span class="badge">👂 한 단계씩 음성 안내</span>
    <span class="badge">🔁 다음 · 다시 말하기</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# 2. 사용자 상황
st.markdown(
    """
<div class="section">
  <div class="section-label">Who it's for</div>
  <div class="section-title">이런 순간, ChefEar가 필요해요</div>
  <div class="section-sub">요리가 익숙하지 않거나 조리 중 화면을 계속 확인하기 어려운 순간, 목소리만으로 필요한 안내를 받을 수 있어요.</div>
  <div class="card-grid-2">
    <div class="card"><span class="icon">🧂</span><h4>재료·계량이 낯설 때</h4><p>재료명과 계량 단위가 익숙하지 않아도 필요한 레시피를 찾아 안내받을 수 있어요.</p></div>
    <div class="card"><span class="icon">🤲</span><h4>손을 쓰기 어려울 때</h4><p>칼질이나 반죽으로 손이 젖어 있어도 화면을 계속 만질 필요가 없어요.</p></div>
    <div class="card"><span class="icon">👂</span><h4>지금 단계만 듣고 싶을 때</h4><p>긴 레시피를 한 번에 듣지 않고 지금 필요한 단계만 안내받을 수 있어요.</p></div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# 3. 사용 예시
st.markdown(
    """
<div class="section">
  <div class="section-label">How it works</div>
  <div class="section-title">이렇게 대화하듯 요리해요</div>
  <div class="scenario">
    <div class="bubble user"><div class="msg">된장찌개 만드는 법 알려줘</div></div>
    <div class="bubble ai"><div class="msg">된장찌개 레시피를 찾았어요. 이걸로 시작할까요?</div></div>
    <div class="bubble user"><div class="msg">응</div></div>
    <div class="bubble ai"><div class="msg">1단계, 물을 넣고 끓여주세요.</div></div>
    <div class="bubble user"><div class="msg">다시 알려줘</div></div>
    <div class="bubble ai"><div class="msg">현재 단계를 다시 알려드릴게요.</div></div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# 4. 사용 방법
st.markdown(
    """
<div class="section">
  <div class="section-title" style="margin-top:0;">사용 방법</div>
  <div class="flow">
    <span class="step">🎙️ 원하는 요리 말하기</span><span class="arrow">→</span>
    <span class="step">🔎 레시피 찾기</span><span class="arrow">→</span>
    <span class="step">🍳 단계별 요리</span><span class="arrow">→</span>
    <span class="step">🔁 다음 · 다시</span><span class="arrow">→</span>
    <span class="step">✅ 요리 완성</span>
  </div>
  <div class="principle" style="margin-top:26px;">👂 화면을 계속 확인하지 않아도 괜찮아요. 필요한 순간에 말하면 현재 요리 단계에 맞춰 안내받을 수 있어요.</div>
</div>
""",
    unsafe_allow_html=True,
)

# 5. 주요 기능
st.markdown(
    """
<div class="section">
  <div class="section-label">Core Features</div>
  <div class="section-title">무엇을 할 수 있나요</div>
  <div class="card-grid">
    <div class="card"><span class="icon">🗣️</span><h4>음성 레시피 조회</h4><p>원하는 요리를 말하면 ChefEar가 레시피를 찾아드려요.</p></div>
    <div class="card"><span class="icon">📶</span><h4>단계별 조리 안내</h4><p>전체 레시피를 한 번에 읽지 않고 한 단계씩 필요한 만큼 안내해요.</p></div>
    <div class="card"><span class="icon">🔁</span><h4>진행 / 재청취</h4><p>"다음", "다시", "한 번 더"처럼 편하게 말하며 요리를 이어갈 수 있어요.</p></div>
    <div class="card"><span class="icon">💾</span><h4>나만의 레시피 저장</h4><p>원하는 레시피를 나만의 레시피로 저장할 수 있어요.</p></div>
    <div class="card"><span class="icon">🖥️</span><h4>화면으로도 확인</h4><p>현재 단계와 재료, 최근 안내를 화면에서도 함께 확인할 수 있어요.</p></div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# 6. ChefEar 장점
st.markdown(
    """
<div class="section">
  <div class="section-label">Why ChefEar</div>
  <div class="section-title">요리할 때 더 편한 이유</div>
  <div style="max-width:640px; margin:0 auto;">
    <div class="diff-row"><span class="old">긴 레시피를 처음부터 끝까지 확인</span><span class="new">내 진행 속도에 맞춰 단계별 안내</span></div>
    <div class="diff-row"><span class="old">요리 중 화면을 계속 조작</span><span class="new">말로 다음 단계와 다시 듣기 요청</span></div>
    <div class="diff-row"><span class="old">이전 안내를 다시 찾기 번거로움</span><span class="new">음성 안내와 화면 확인을 함께 사용</span></div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# 7. 레시피 규모
st.markdown(
    """
<div class="section">
  <div class="section-label">Recipes</div>
  <div class="section-title">다양한 요리를 만나보세요</div>
  <div class="section-sub">익숙한 집밥부터 다양한 메뉴까지 원하는 요리를 찾아볼 수 있어요.</div>
  <div class="stat-grid">
    <div class="stat"><div class="num">60,282</div><div class="label">다양한 요리명</div></div>
    <div class="stat"><div class="num">234,538</div><div class="label">레시피 정보</div></div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# 8. 사용 표현 예시
st.markdown(
    """
<div class="section">
  <div class="section-label">Try saying</div>
  <div class="section-title">이렇게 말해보세요</div>
  <div class="section-sub">특별한 명령어를 외울 필요 없이 평소 말하듯 요청하면 돼요.</div>
  <div class="card-grid-2">
    <div class="card"><span class="icon">🍲</span><h4>요리 찾기</h4><p>"김치찌개 만드는 법 알려줘"</p></div>
    <div class="card"><span class="icon">➡️</span><h4>다음 단계</h4><p>"다음 단계 알려줘"</p></div>
    <div class="card"><span class="icon">🔁</span><h4>다시 듣기</h4><p>"방금 거 다시 알려줘"</p></div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# 9. 하단
st.markdown(
    """
<div class="footer-note">🍳 ChefEar — 화면을 계속 확인하지 않아도,<br/>말하고 듣고 내 속도에 맞춰 한 단계씩 요리해보세요.</div>
""",
    unsafe_allow_html=True,
)