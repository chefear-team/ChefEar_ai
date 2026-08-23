"""ui/html/assets/style.css와 같은 디자인 토큰을 Streamlit용으로 옮긴 공통 스타일/컴포넌트.

Streamlit 기본 위젯(st.button 등)은 그대로 쓰고, 배지·카드·재료칩·대화 로그처럼
Streamlit 기본 컴포넌트로 표현하기 어려운 조각만 st.markdown(unsafe_allow_html=True)로
그린다. docs/ChefEar_PRD_SDD_v0.8.md 3.3의 화면 구성(①~⑥)을 그대로 따른다.
"""
import base64
import io
import json
from pathlib import Path
from string import Template

import numpy as np
import soundfile as sf
import streamlit as st

CSS = """
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
  --positive-icon-bg: #dcebc9;
  --danger-bg: #f6e4de;
  --danger-text: #a24a34;
}

/* Streamlit 기본 크롬(헤더 툴바·메뉴·푸터)을 최소화해서 ui/html 버전처럼 화면 자체만
   보이게 한다. 사이드바 열기 화살표는 남겨둔다(개발용 "화면 바로가기" 접근용). */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
[data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; box-shadow: none; }
/* 버그 실측(2026-08-19, Playwright): background만 투명하게 해도 헤더 <header> 자체는
   여전히 화면 맨 위(y=0~약 46px)를 뷰포트 기준 고정으로 덮고 있어서, 그 자리에 있는
   콘텐츠(recipe_confirm의 "처음으로" 링크가 order:-1로 맨 위까지 끌어올려짐)를 클릭해도
   투명한 헤더가 클릭을 가로채 버렸다(눈엔 안 보이니 원인 파악이 어려웠음,
   document.elementFromPoint()로 실제 확인). 헤더 전체를 클릭 통과시키고, 남겨두기로 한
   사이드바 열기 버튼만 다시 클릭 가능하게 되돌린다. */
[data-testid="stHeader"] { pointer-events: none; }
[data-testid="stExpandSidebarButton"] { pointer-events: auto; }

/* ui/html/assets/style.css의 body(#e9e2d3 바깥 배경) + .screen(카드 자체) 2단 구조를 그대로 옮김 */
.stApp { background: #e9e2d3; }
.block-container {
  max-width: 430px; background: var(--bg);
  padding: 20px 22px 44px;
  box-shadow: 0 20px 46px rgba(36, 28, 21, 0.14);
  min-height: 100vh;
  display: flex; flex-direction: column;
  /* block-container(stMainBlockContainer) 자신이 stMain(overflow:auto인 진짜 스크롤
     컨테이너)의 flex 자식이라, 기본값인 flex-shrink:1 때문에 콘텐츠가 길어지면(예: 대화
     구역이 항상 보이도록 바뀌며 화면이 길어진 경우) 실제 콘텐츠 높이(예: 1041px)를
     무시하고 min-height 한계선(예: 뷰포트 900px)까지 찌그러들어서, 넘친 부분이 바깥
     stApp의 overflow:hidden에 잘려 보이는 버그가 있었다(DevTools 실측으로 확인).
     flex-shrink:0으로 고정해 절대 안 찌그러들게 한다. */
  flex-shrink: 0;
}
/* block-container 바로 밑의 큰 stVerticalBlock 하나가 전체 화면 내용을 담는데, 기본값으로는
   내용물 높이만큼만 차지해서(auto) block-container의 min-height:100vh가 남겨준 여유 공간을
   실제로 갖지 못했다(그래서 render_spacer()의 flex:1 방식이 예전에 안 먹혔던 진짜 원인 -
   부모가 flex가 아니어서 자식이 늘어날 공간 자체가 없었음). block-container를 flex column으로
   만들고 이 자식을 flex:1로 늘려서, 그 안의 .ce-spacer(flex:1)들이 진짜 남는 공간을 나눠
   가지며 화면 크기가 바뀌어도(창 크기 조절·브라우저 확대/축소) 반응형으로 중앙 정렬되게 한다. */
/* flex-shrink을 0으로 고정한다 - flex:1 1 auto(shrink:1)였을 때, 콘텐츠 실제 높이가
   min-height:100vh보다 커지면(예: 대화 구역이 항상 보이게 바뀌면서 콘텐츠가 길어짐)
   브라우저가 이 블록을 부모 높이에 맞춰 억지로 찌그러뜨리려 하면서, 넘친 부분이
   화면에 잘려 보이는(ghost/cut) 렌더링 버그가 있었다(DevTools로 stMainBlockContainer/
   stVerticalBlock에서 실측 확인함). shrink:0으로 고정하면 콘텐츠가 짧을 때 grow:1로
   남는 공간을 채우는 동작은 그대로 유지하면서, 콘텐츠가 길어져도 절대 안 찌그러진다. */
.block-container > [data-testid="stVerticalBlock"] { flex: 1 0 auto !important; }
/* .ce-spacer 자체에 flex:1을 줘도 소용없다 - 실제로 stVerticalBlock의 flex 아이템인 건
   .ce-spacer의 4단계 위 조상인 stElementContainer이고, .ce-spacer는 그 안에 block으로
   납작하게 들어있는 손자뻘이라 flex:1이 그 자리에서 먹히지 않는다(DOM 구조를 실제로
   찍어봐서 확인함). 그래서 .ce-spacer를 담은 stElementContainer 쪽에 직접 flex:1을 준다.
   Streamlit 자체 CSS(Emotion)가 .element-container에 flex:0 1 auto를 이미 주고 있어서
   단순 규칙으로는 안 먹혀 !important로 덮어썼다. */
[data-testid="stElementContainer"]:has(.ce-spacer) { flex: 1 1 auto !important; }
/* 재료 칩 그리드(.ce-chip-grid)와 바로 아래 "응, 시작할게요" 버튼 사이 간격을 다른 구역보다
   더 띄우고 싶을 때, 칩 자체에 margin-bottom을 주면 위 문단에서 설명한 바로 그 겹침 버그가
   재현된다(margin은 stElementContainer 높이 측정에 반영 안 됨). 대신 padding은 박스 모델상
   항상 높이에 포함되므로, 칩을 담은 stElementContainer 쪽에 padding-bottom을 준다. */
[data-testid="stElementContainer"]:has(.ce-chip-grid) { padding-bottom: 14px; }
/* cooking_step의 "나:/ChefEar:" 대화 카드(.ce-transcript)와 바로 아래 "듣는 중" 마이크바
   사이 간격을 다른 구역보다 더 띄운다. 같은 이유로 margin이 아니라 padding-bottom을 쓴다. */
[data-testid="stElementContainer"]:has(.ce-transcript) { padding-bottom: 14px; }
/* cooking_step의 "듣는 중" 마이크바(.ce-mic-bar)와 바로 아래 이전/다시/다음 버튼 줄
   사이 간격을 더 띄운다. 같은 이유로 margin이 아니라 padding-bottom을 쓴다. */
[data-testid="stElementContainer"]:has(.ce-mic-bar) { padding-bottom: 14px; }
/* complete 화면의 "원본 레시피 보존됨"/"나만의 레시피로 저장됨" 상태 배지 줄과 바로 아래
   설명 카드 사이 간격을 더 띄운다. 같은 이유로 margin이 아니라 padding-bottom을 쓴다. */
[data-testid="stElementContainer"]:has(.ce-status-badge) { padding-top: 14px; padding-bottom: 14px; }
/* substitution_confirm의 레시피 교체 비교 카드(된장찌개 → 바지락된장찌개)와 바로 아래
   "네, 바꿔주세요"/"아니요, 원래대로" 버튼 줄 사이 간격을 더 띄운다. */
[data-testid="stLayoutWrapper"]:has([class*="st-key-sc_swap_card"]) { padding-bottom: 14px; }
html, body, [class*="css"] { font-family: "Pretendard", -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; }

/* 시작·매칭실패·등록제안·완료·인식실패 화면(01/05/06/10/11)은 ui/html에서
   .screen을 flex column으로 두고 중간 콘텐츠에 flex:1 + justify-content:center를 줘서
   로고 밑 남는 공간에 내용을 수직 중앙 정렬한다. Streamlit은 네이티브 위젯(st.button 등)을
   그렇게 감쌀 수 없어서(각 위젯이 별도 컨테이너로 렌더링됨), 대신 중앙에 둘 콘텐츠
   앞뒤에 flex:1짜리 빈 블록을 넣어 위아래가 남는 공간을 똑같이 나눠 갖게 한다(위
   .block-container > stVerticalBlock 규칙과 짝을 이뤄야 실제로 늘어난다). 뷰포트/창
   크기가 바뀌면 남는 공간도 같이 바뀌므로 브라우저 확대·축소나 창 크기 조절에도
   반응형으로 중앙 정렬이 유지된다. */
.ce-spacer { width: 100%; flex: 1 1 auto; }

/* 커스텀 컴포넌트(.ce-*)는 각각 별도의 st.markdown() 호출로 그려지는데, Streamlit이
   그 감싸는 컨테이너(stElementContainer) 높이를 CSS margin을 반영하지 않고 먼저
   측정해버려서, 그 컴포넌트 자체에 위/아래 margin을 주면 다음 요소와 실제로 겹치는
   문제가 있었다("이전/다시/다음" 버튼 줄이 마이크 상태줄과 겹쳐 보인 원인).
   그래서 요소 사이 간격은 개별 margin이 아니라 부모의 flex gap 하나로만 통일한다. */
[data-testid="stVerticalBlock"] { gap: 1.35rem; }
.block-container hr { border-color: var(--border); margin: 10px 0; }
.block-container small, [data-testid="stCaptionContainer"] { color: var(--text-secondary) !important; font-size: 12.5px !important; }
[data-testid="stAlert"] { border-radius: 16px; }
div.stTextInput input {
  border-radius: 14px; border: 1.5px solid var(--border); background: var(--surface-alt);
  color: var(--text); font-family: inherit;
}
div.stTextArea textarea {
  border-radius: 14px; border: 1.5px solid var(--border); background: transparent;
  color: var(--text); font-family: inherit;
}
/* 비밀번호 입력칸의 "표시/숨기기"(눈 모양) 토글 버튼 - Streamlit이 클래스명을
   렌더링마다 새로 해시해서(st-emotion-cache-*) 클래스로는 못 짚고, 값이 고정인
   aria-label(Show/Hide password)로 짚는다. 버튼 자체 배경은 원래도 투명이지만,
   버튼을 감싸는 바로 위 div가 회색 배경(rgb(240,242,246))을 따로 갖고 있어서
   버튼만 투명하게 해선 그 사각 회색 박스가 그대로 남는다 - 그 감싸는 div까지
   :has()로 같이 짚어서 투명하게 만든다(실측 확인, 2026-08-21).*/
button[aria-label="Show password"], button[aria-label="Hide password"] {
  background: transparent; border: none; box-shadow: none;
}
div:has(> button[aria-label="Show password"]), div:has(> button[aria-label="Hide password"]) {
  background: transparent; border: none;
}

.ce-back-link { display:inline-flex; align-items:center; gap:4px; font-size:13px; color: var(--text-secondary); font-weight:700; margin-bottom: 4px; }

.ce-brand { display:flex; align-items:center; gap:8px; font-size:22px; font-weight:800; color:var(--text); }
.ce-brand .icon { color: var(--accent); display:inline-flex; }

.ce-section-title { display:flex; align-items:center; gap:7px; font-size:15px; font-weight:800; color:var(--text); margin-top: 18px; }
.ce-section-title .icon { color: var(--text-secondary); display:inline-flex; }

.ce-badge {
  display:inline-flex; align-items:center; gap:6px;
  background: var(--accent-soft); color: var(--accent-soft-text);
  font-size:13px; font-weight:700; padding:7px 15px; border-radius:999px;
}

.ce-card {
  background: var(--surface); border-radius: 22px; padding: 22px 20px;
  box-shadow: 0 10px 24px rgba(36,28,21,0.07);
}
/* cooking_step의 조리 카드 - 재생바가 실제 오디오(iframe)일 때는 순수 HTML(.ce-card
   div)로 못 감싸서(별도 Streamlit 엘리먼트라 하나의 st.markdown 안에 못 넣음) 진짜
   st.container(key="cs_step_card")를 카드로 쓴다. 그 컨테이너의 실제 DOM 래퍼에
   .ce-card와 동일한 스타일을 입힌다(theme.render_step_card() 참고). 두 속성 선택자
   조합이라 전역 gap 규칙([data-testid="stVerticalBlock"] { gap: 1.35rem; })보다
   specificity가 높아 !important 없이 아래 gap이 이긴다. */
[data-testid="stVerticalBlock"][class*="st-key-cs_step_card"] {
  background: var(--surface); border-radius: 22px; padding: 22px 20px;
  box-shadow: 0 10px 24px rgba(36,28,21,0.07); gap: 14px;
}

/* 마이 레시피 목록의 레시피 한 건 카드 - cs_step_card와 같은 이유로(안에 실제
   st.button이 들어가서 순수 HTML .ce-card로 못 감쌈) 진짜 컨테이너를 카드로 쓴다.
   레시피마다 키가 다르니(st-key-my_recipe_card_<id>) 부분일치 선택자로 짚는다. */
[data-testid="stVerticalBlock"][class*="st-key-my_recipe_card_"] {
  background: var(--surface); border-radius: 18px; padding: 16px 18px;
  box-shadow: 0 6px 16px rgba(36,28,21,0.06); gap: 6px;
}
.ce-recipe-name { display:flex; align-items:center; gap:8px; font-size:15px; font-weight:700; color: var(--text); }
.ce-recipe-name .icon { color: var(--accent); display:inline-flex; }

/* 마이 레시피 목록 전체를 감싸는 컨테이너 - 레시피 개수가 많아지면 화면 밖으로 한없이
   길어지던 걸, 일정 높이(60vh)가 넘으면 그 안에서만 스크롤되게 한다(2026-08-22 요청).
   overflow가 오른쪽 카드 그림자(box-shadow)를 잘라먹지 않도록 카드 padding만큼
   여유(4px)를 좌우에 더 준다. */
[data-testid="stVerticalBlock"][class*="st-key-my_recipes_list"] {
  max-height: 60vh; overflow-y: auto; padding: 4px; margin: -4px;
}

/* 마이 레시피 카드의 수정/삭제 버튼 두 개 - st.columns로 나누면 감싸는 칸이 넓어질
   때마다 두 버튼도 같이 벌어져서(각자 칸의 절반씩 차지) 화면이 넓을수록 간격이
   커지는 문제가 있었다(2026-08-21, 실측). 대신 세로 블록 하나(stVerticalBlock)에
   버튼 둘을 넣고 여기서 가로 배치로 강제한다 - flex-shrink:0이라 칸이 넓어져도
   버튼 자체 크기만큼만 차지하고, justify-content:flex-end로 오른쪽에 붙는다. */
[data-testid="stVerticalBlock"][class*="st-key-my_recipe_actions_"] {
  flex-direction: row; flex-wrap: nowrap; gap: 6px; justify-content: flex-end;
  flex-shrink: 0; width: auto;
}
[data-testid="stVerticalBlock"][class*="st-key-my_recipe_actions_"] [data-testid="stElementContainer"] {
  width: auto;
}

/* start 화면 상단 로그인 버튼 - 자기 칸 안에서 왼쪽에 붙어있던 걸 오른쪽 끝으로 민다. */
[data-testid="stVerticalBlock"][class*="st-key-brand_login_wrap"] {
  display: flex; align-items: flex-end; justify-content: flex-end;
}

/* 레시피 등록 · 조리 순서 화면(register_steps)의 순서 번호 배지 - 원형 배지 + 문장,
   마이 레시피 카드(.ce-recipe-name)와 같은 둥근 배지 언어를 재사용한다(2026-08-21).
   줄 전체 박스는 이제 st-key-reg_step_row_(위 참고)가 담당한다(2026-08-22, 수정/삭제
   버튼을 넣으려고 순수 HTML 대신 진짜 컨테이너로 바꾸면서 .ce-step-list/.ce-step-row는
   더 안 쓰게 됨). */
.ce-step-num {
  width:26px; height:26px; min-width:26px; border-radius:50%; background: var(--accent);
  color:#fff; display:grid; place-items:center; font-weight:800; font-size:13px; margin-top:1px;
}

/* register_steps 화면의 순서 한 줄(2026-08-22 요청, 수정/삭제 버튼 추가) - 안에 실제
   st.button이 들어가서 순수 HTML .ce-step-row로 못 감싸므로(cs_step_card/my_recipe_card_와
   같은 이유) 진짜 컨테이너를 카드로 쓴다. 줄마다 키가 다르니(st-key-reg_step_row_<i>)
   부분일치 선택자로 짚는다. */
[data-testid="stVerticalBlock"][class*="st-key-reg_step_row_"] {
  background: var(--surface); border-radius: 16px; padding: 10px 16px;
  box-shadow: 0 4px 12px rgba(36,28,21,0.05); gap: 4px;
}
/* 수정/삭제 버튼 두 개 - my_recipe_actions_와 같은 이유(2026-08-21, 칸이 넓어질수록
   버튼이 벌어지는 문제)로 세로 블록 하나에 담고 가로 배치 + 오른쪽 붙임으로 강제한다. */
[data-testid="stVerticalBlock"][class*="st-key-reg_step_actions_"] {
  flex-direction: row; flex-wrap: nowrap; gap: 6px; justify-content: flex-end;
  flex-shrink: 0; width: auto;
}
[data-testid="stVerticalBlock"][class*="st-key-reg_step_actions_"] [data-testid="stElementContainer"] {
  width: auto;
}

.ce-dots { display:flex; justify-content:center; gap:9px; }
.ce-dots .d { width:9px; height:9px; border-radius:50%; background: var(--border); }
.ce-dots .d.active { background: var(--accent); transform: scale(1.25); }
.ce-dots .d.done { background: var(--accent-soft-text); opacity:.45; }

/* cooking_step 상단 점을 실제로 눌러서 그 단계로 바로 이동할 수 있게 만든 버전
   (2026-08-21 요청) - _dots_html()의 장식용 span 대신 진짜 st.button()을 한 줄에
   나란히 놓는다. st.columns로 나누면 my_recipe_actions_와 같은 이유로 화면이
   넓을수록 점 사이 간격이 벌어지므로, 세로 블록 하나에 버튼들을 넣고 여기서
   가로 배치로 강제한다. 버튼 상태(active/done/todo)를 키 이름 자체에 인코딩해서
   (cs_dot_active_01 등) CSS가 셀렉터만으로 바로 스타일을 입힐 수 있게 한다. */
[data-testid="stVerticalBlock"][class*="st-key-cs_dots_row"] {
  flex-direction: row; flex-wrap: nowrap; justify-content: center; gap: 2px;
}
[class*="st-key-cs_dots_row"] [data-testid="stElementContainer"] { width: auto; }
[class*="st-key-cs_dot_todo_"] button,
[class*="st-key-cs_dot_done_"] button,
[class*="st-key-cs_dot_active_"] button {
  position: relative; width: 22px; height: 22px; min-width: 22px; min-height: 22px;
  padding: 0; border: none; background: transparent; box-shadow: none; cursor: pointer;
  color: transparent; font-size: 0; line-height: 0;
}
[class*="st-key-cs_dot_todo_"] button::after,
[class*="st-key-cs_dot_done_"] button::after,
[class*="st-key-cs_dot_active_"] button::after {
  content: ""; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: 9px; height: 9px; border-radius: 50%; background: var(--border);
}
[class*="st-key-cs_dot_done_"] button::after { background: var(--accent-soft-text); opacity: .45; }
[class*="st-key-cs_dot_active_"] button::after {
  background: var(--accent); transform: translate(-50%, -50%) scale(1.25);
}

/* 2026-08-22 리포트 — 위아래 margin이 32px/14px로 비대칭이었어서, vertical_alignment=
   "center"가 화살표 칸과 텍스트 칸을 각자의 박스(margin 포함) 높이 기준으로 정렬하다 보니
   텍스트가 화살표보다 아래로 처져 보였다(짧은 한 줄 문장일수록 그 9px 안팎의 어긋남이
   전체 높이에서 차지하는 비중이 커서 더 두드러짐). margin을 0으로 맞춰서 텍스트 박스
   높이 = 실제 글자 높이가 되게 하고, 점(dots)과의 간격은 아래 stHorizontalBlock의
   margin-top으로 화살표·텍스트 칸 셋을 한 덩어리로 같이 밀어서 만든다. */
.ce-step-title { font-size:22px; font-weight:800; text-align:center; line-height:1.45; margin: 0 !important; }
/* 조리순서 단계 텍스트 양옆의 이전/다음 화살표(2026-08-21 요청) - 화살표는 각자 칸
   가장자리에 붙어있고 가운데 텍스트 칸만 늘어나면 되므로(2개 아이콘이 서로 벌어지는
   my_recipe_actions_ 문제와 달리 여기선 오히려 벌어지는 게 의도된 배치), st.columns를
   그대로 써도 된다. */
[class*="st-key-cs_step_card"] div[data-testid="stHorizontalBlock"] { margin-top: 18px; }
[class*="st-key-cs_prev_arrow"] button, [class*="st-key-cs_next_arrow"] button {
  background: var(--surface-alt); border: 1px solid var(--border); color: var(--accent);
  /* use_container_width=True가 버튼을 칸 전체 너비로 늘리는데, 아이콘 하나만 들어있어서
     칸을 좁게 잡아도(st.columns([1,7,1])) 버튼이 뚱뚱해 보인다는 지적(2026-08-22)으로
     버튼 자체 너비를 강제로 좁혀 칸 안에서 가운데 정렬한다. */
  width: 36px !important; min-width: 36px !important; margin: 0 auto;
}
/* 2026-08-22: st.columns([1,10,1])로 비율을 줘도 화면엔 반영 안 됐는데, 원인은 위(298줄
   근처) "컬럼이 항상 가로로 나란히 있도록" 규칙의 `div[data-testid="stColumn"] { flex: 1 1
   0 !important; }` — 이게 이 앱의 모든 st.columns()를 강제로 똑같은 너비(1:1:1)로 만들어서
   Python 쪽 비율 인자를 완전히 무시하고 있었다. cs_step_card 안의 컬럼(화살표-텍스트-화살표)
   에만 더 구체적인 선택자로 그 규칙을 다시 덮어써서, 화살표 칸은 좁게 고정하고 텍스트
   칸이 남는 공간을 전부 차지하게 한다. */
[class*="st-key-cs_step_card"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-of-type(1),
[class*="st-key-cs_step_card"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-of-type(3) {
  flex: 0 0 44px !important; width: 44px !important;
}
[class*="st-key-cs_step_card"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-of-type(2) {
  flex: 1 1 auto !important; width: auto !important;
}

.ce-chip-grid { display:flex; flex-wrap:wrap; column-gap:9px; row-gap:16px; }
.ce-chip { display:inline-flex; align-items:center; gap:6px; background: var(--surface-alt); border:1px solid var(--border);
  border-radius:999px; padding:9px 14px; font-size:14px; font-weight:600; color: var(--text); }
.ce-chip.substituted { background: var(--positive-bg); border-color: var(--positive-bg); color: var(--positive-text); }

.ce-transcript { background: var(--surface); border-radius:16px; box-shadow: 0 2px 8px rgba(36,28,21,0.05); overflow:hidden; }
.ce-row { display:flex; gap:12px; padding:18px 18px; }
.ce-row + .ce-row { border-top:1px solid var(--border); }
.ce-avatar { width:30px; height:30px; min-width:30px; border-radius:50%; display:grid; place-items:center; font-size:14px; }
.ce-avatar.user { background: var(--accent); color: #fff; }
.ce-avatar.ai { background: var(--positive-icon-bg); color: var(--positive-text); }
.ce-row .who { font-weight:800; margin-right:3px; }
.ce-row .who.user { color: var(--accent-dark); }
.ce-row .who.ai { color: var(--positive-text); }
.ce-row p { margin:4px 0 0; font-size:14.5px; line-height:1.65; }

.ce-center { text-align:center; }
.ce-center h1 { font-size:22px; font-weight:800; margin:6px 0 8px; }
.ce-center p { font-size:14.5px; color: var(--text-secondary); line-height:1.6; margin:0; }

.ce-lead-icon { width:56px; height:56px; border-radius:50%; display:grid; place-items:center; margin: 0 auto; }
.ce-lead-icon.positive { background: var(--positive-bg); color: var(--positive-text); }
.ce-lead-icon.warn { background: var(--danger-bg); color: var(--danger-text); }
.ce-lead-icon.neutral { background: var(--accent-soft); color: var(--accent-soft-text); }

.ce-checkpoint { background: var(--accent-soft); border-radius:16px; padding:14px 16px; }
.ce-checkpoint .title { font-weight:800; color: var(--accent-soft-text); font-size:13.5px; margin-bottom:4px; }
.ce-checkpoint p { margin:0; font-size:13.5px; color: var(--accent-soft-text); line-height:1.5; }

.ce-status-badge { display:inline-flex; align-items:center; gap:6px; background: var(--positive-bg); color: var(--positive-text);
  font-size:12.5px; font-weight:700; padding:7px 13px; border-radius:999px; margin: 0 4px 0 0; }

.ce-hint { text-align:center; font-size:12.5px; color: var(--text-secondary); }

/* Streamlit은 좁은 화면에서 st.columns()를 자동으로 세로로 쌓는다(반응형 기본 동작).
   이 앱은 일부러 폰 너비(430px)로 좁게 만들어서 그 반응형 기준을 항상 넘겨버리기
   때문에, 이전/다시/다음 같은 가로 버튼 줄이 항상 세로로 쌓이고 그 위 요소와
   겹쳐 보였다. 컬럼이 항상 가로로 나란히 있도록 강제로 되돌린다. */
div[data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 10px !important; }
div[data-testid="stColumn"] { width: unset !important; flex: 1 1 0 !important; min-width: 0 !important; }

div.stButton > button {
  border-radius: 18px; font-weight: 700; padding: 0.65rem 1rem; border: 1.5px solid var(--border);
  background: var(--surface); color: var(--text); box-shadow: 0 2px 8px rgba(36,28,21,0.05);
  cursor: pointer;
}
div.stButton > button[kind="primary"] {
  background: var(--accent); border-color: var(--accent); color: #fff;
  box-shadow: 0 10px 22px rgba(238,123,54,0.32); font-weight: 800;
}
div.stButton > button[kind="primary"]:hover { background: var(--accent-dark); border-color: var(--accent-dark); }

.ce-player {
  display:flex; align-items:center; gap:14px; background: var(--surface-alt);
  border-radius:999px; padding:10px 14px; margin-top: 6px;
}
.ce-play-btn {
  width:38px; height:38px; min-width:38px; border-radius:50%;
  background: var(--accent-soft); color: var(--accent); display:grid; place-items:center;
}
.ce-wave { flex:1; display:flex; align-items:center; gap:1.5px; height:26px; overflow:hidden; }
.ce-wave span { flex:1 1 0; min-width:0; border-radius:1px; background: var(--accent); opacity:.85; }

.ce-mic-bar {
  display:flex; align-items:center; gap:14px; background: var(--surface);
  border-radius:999px; padding:8px 18px 8px 8px; box-shadow: 0 10px 24px rgba(36,28,21,0.07);
  /* 브라우저 줌이 100%가 아니거나 Windows 디스플레이 배율이 걸려있을 때, 둥근 모서리 +
     box-shadow 조합이 정수 픽셀에 안 맞으면 가장자리가 이중으로 겹쳐 보이는(고스팅)
     크로미움 렌더링 버그가 있다. 이 요소를 별도 GPU 레이어로 승격시켜 서브픽셀
     반올림 오차를 줄인다. */
  transform: translateZ(0);
}
.ce-mic-icon { width:50px; height:50px; min-width:50px; border-radius:50%; display:grid; place-items:center; position:relative; }
.ce-mic-icon.listening { background: var(--accent); color:#fff; box-shadow: 0 0 0 7px rgba(238,123,54,0.16); }
.ce-mic-icon.idle { background: var(--surface-alt); color: var(--accent); border:2px solid var(--border); }
/* "듣는 중" 마이크가 정말 활성화된 것처럼 보이도록 링이 바깥으로 퍼지며 옅어지는
   펄스 애니메이션 - 정적인 고리(box-shadow)만으로는 그냥 켜져있는 건지 실제로
   듣고 있는 건지 구분이 안 된다는 지적으로 추가함(2026-08-21). idle 상태에는
   안 붙는다(듣고 있지 않을 땐 펄스도 없어야 앞뒤가 맞음). */
.ce-mic-icon.listening::after {
  content:""; position:absolute; inset:-7px; border-radius:50%;
  border:2px solid var(--accent); opacity:.6;
  animation: ce-mic-pulse 1.6s ease-out infinite;
}
@keyframes ce-mic-pulse {
  0% { transform: scale(1); opacity:.6; }
  100% { transform: scale(1.6); opacity:0; }
}
.ce-mic-status .state { font-weight:800; color: var(--accent-dark); font-size:14.5px; display:block; }
.ce-mic-status .hint { font-size:12px; color: var(--text-secondary); display:block; }

/* cooking_step의 실제 녹음 가능한 "듣는 중" 바(render_mic_bar_interactive) - ce_big_mic와
   같은 투명 버튼 오버레이 패턴. div.stButton에 height:100%를 처음부터 같이 넣어서
   ce_big_mic에서 겪은 "버튼이 부모 높이를 못 물려받아 클릭 영역이 위쪽 일부만 되는" 버그를
   재발시키지 않는다(원인은 ce_big_mic 관련 주석 참고). */
[class*="st-key-cs_mic_bar"] { position: relative; }
[class*="st-key-cs_mic_bar"] [data-testid="stElementContainer"]:has(div.stButton) {
  position: absolute; inset: 0; z-index: 2;
}
[class*="st-key-cs_mic_bar"] div.stButton { height: 100%; }
[class*="st-key-cs_mic_bar"] div.stButton > button {
  width: 100%; height: 100%; padding: 0; border: none; background: transparent;
  box-shadow: none; color: transparent; cursor: pointer;
}

.ce-big-mic-wrap { display:flex; justify-content:center; margin: 34px 0 8px; }
.ce-big-mic { width:84px; height:84px; border-radius:50%; display:grid; place-items:center;
  background: var(--surface-alt); color: var(--accent); border: 2px solid var(--border);
  animation: ce-big-mic-pulse 1.8s ease-in-out infinite; transition: background .25s, border-color .25s, box-shadow .25s; }
/* 2026-08-23 추가 — "준비됐는지 안 됐는지 모르겠다"는 리포트로, 상시 마이크가 실제로
   연결됐을 때(webrtc_ctx.state.playing)만 .ce-mic-icon.listening(다른 화면의 "듣는 중"
   표시)과 같은 색(accent) + 번지는 링으로 바뀐다 — 연결 전엔 계속 회색(기존 그대로)이라
   "아직 준비 안 됨"이 한눈에 구분된다. */
.ce-big-mic.ready { background: var(--accent); color:#fff; border-color: var(--accent);
  box-shadow: 0 0 0 10px rgba(238,123,54,0.16); }
/* start 화면 큰 마이크 아이콘이 커졌다 작아지길 반복해서 "지금 듣고 있다"는 느낌을 주는
   숨쉬기(breathing) 애니메이션 - ce-mic-icon.listening::after의 퍼지는 링과는 다르게,
   여긴 아이콘 자체가 확대/축소된다(2026-08-21 요청). */
@keyframes ce-big-mic-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.12); }
}

/* start 화면의 실제 녹음 위젯(st.audio_input) - 장식용 원형 마이크 바로 아래 놓고, 앱
   색감에 맞춰 폭을 카드 안쪽으로 좁히고 둥글게 다듬는다. */
[data-testid="stAudioInput"] {
  max-width: 320px; margin: 4px auto 0; border-radius: 999px !important;
  border-color: var(--border) !important; background: var(--surface) !important;
}
/* 녹음/재생 버튼 아이콘은 fill="currentColor"라서 color만 바꾸면 앱 강조색으로 물든다.
   실시간 파형 자체는 wavesurfer.js가 그리는 라이브 렌더링이라(캔버스 기반) CSS로
   색을 못 바꾼다 - 재생 버튼·테두리·배경만 앱 색감에 맞춘다. */
[data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"] { color: var(--accent) !important; }

/* 큰 원형 마이크(장식용 그림 + 안내 문구) 전체를 클릭 영역으로 만들어, 눌렀을 때만
   실제 녹음 위젯(st.audio_input)이 나타나게 한다 - hint_chip과 같은 방식으로 투명
   버튼을 그 위에 겹친다.

   버그 실측(2026-08-19, Playwright로 실제 클릭 좌표 확인): stElementContainer는
   position:absolute+inset:0로 부모(151px 높이) 전체를 정확히 덮었지만, 그 안의
   실제 <button>은 40px 높이로만 렌더링돼서 아이콘 아래쪽·안내 문구 영역은 눌러도
   반응이 없었다. 원인은 button { height:100% }가 자기 직계 부모인 div.stButton
   기준으로 계산되는데, div.stButton 자체엔 height가 없어(기본값 auto) 퍼센트
   높이가 안 먹혔기 때문(width는 block 요소가 기본으로 부모 너비를 꽉 채우는 것과
   달리 height:auto는 내용물 높이만큼만 차지함 - 그래서 width:100%는 이미 되고
   있었는데 height:100%만 깨져 있었다). div.stButton 자체에도 height:100%를 줘서
   퍼센트 체인을 이어준다 - 아래 hint_chip/ce_back_link도 같은 패턴이라 동일하게
   고침. */
[class*="st-key-ce_big_mic"] { position: relative; }
[class*="st-key-ce_big_mic"] [data-testid="stElementContainer"]:has(div.stButton) {
  position: absolute; inset: 0; z-index: 2;
}
[class*="st-key-ce_big_mic"] div.stButton { height: 100%; }
[class*="st-key-ce_big_mic"] div.stButton > button {
  width: 100%; height: 100%; padding: 0; border: none; background: transparent;
  box-shadow: none; color: transparent; cursor: pointer;
}

/* ui/html의 .hint-chip은 <a> 안에 <span class="quote">로 일부만 굵게+주황색을 준다.
   st.button 라벨은 순수 텍스트만 지원해서 그 안에서 글자색을 섞어 쓸 수 없다 - 그래서
   "글씨는 서식 있는 st.markdown으로 진짜처럼 그리고, 그 위에 완전히 투명한 st.button을
   똑같은 크기로 겹쳐서 클릭만 받는" 방식으로 우회한다. st.container(key=...)로 감싼
   두 자식(markdown, button) 중 markdown이 정상 흐름으로 박스 크기를 결정하고, button은
   position:absolute로 그 위에 정확히 덮인다. */
[class*="st-key-hint_chip"] { position: relative; margin-bottom: 10px; }
[class*="st-key-hint_chip"] [data-testid="stElementContainer"]:has(div.stButton) {
  position: absolute; inset: 0; z-index: 2;
}
/* div.stButton 자체에도 height:100%를 줘야 그 안의 button { height:100% }가 실제로
   부모(stElementContainer, 여기서 카드 전체 높이로 늘어남) 기준으로 계산된다 - 안
   주면 button이 자기 내용물 높이(~40px)로만 렌더링돼서 클릭 영역이 카드 위쪽 일부만
   덮는 버그가 생긴다(ce_big_mic에서 Playwright로 실측 확인한 것과 동일한 원인). */
[class*="st-key-hint_chip"] div.stButton { height: 100%; }
[class*="st-key-hint_chip"] div.stButton > button {
  width: 100%; height: 100%; padding: 0; border: none; background: transparent;
  box-shadow: none; color: transparent; cursor: pointer;
}

.ce-hint-chip {
  display: block; background: var(--surface); border: 1px solid var(--border);
  border-radius: 18px; padding: 14px 18px; font-size: 14.5px; font-weight: 600;
  color: var(--text); box-shadow: 0 2px 8px rgba(36,28,21,0.05); line-height: 1.5;
}
.ce-hint-chip .quote { color: var(--accent-dark); font-weight: 800; }

/* "처음으로" 뒤로가기 링크. render_brand()가 app.py에서 화면 공통으로 먼저 그려지기
   때문에 recipe_confirm 화면에서만 이 링크를 브랜드보다 "위"에 두려면 DOM 순서가 아니라
   CSS로 되돌려야 한다. st.container(key=...)는 stLayoutWrapper > stVerticalBlock 두
   겹으로 감싸는데, [class*="st-key-..."]가 잡는 건 안쪽 stVerticalBlock이라 거기에
   order를 줘도 진짜 형제(render_brand의 markdown)와 순서가 안 바뀐다 - 바깥쪽
   stLayoutWrapper가 진짜 flex 형제라 그쪽에 order:-1을 줘야 한다(DOM 직접 확인함). */
/* 부모 stVerticalBlock의 gap(1.35rem)이 모든 형제 사이에 균일하게 적용되는데, 처음으로↔
   ChefEar 사이만 더 붙이고 싶어서 이 항목에만 음수 margin-bottom을 줘서 gap을 상쇄한다.
   flex 아이템 자체(stLayoutWrapper)에 준 margin이라 콘텐츠 내부 margin 미반영 버그와는
   무관하게 정상적으로 다음 형제와의 간격을 줄인다. */
[data-testid="stLayoutWrapper"]:has([class*="st-key-ce_back_link"]) { order: -1; margin-bottom: -14px; }
[class*="st-key-ce_back_link"] { position: relative; margin-bottom: 4px; display: inline-block; }
[class*="st-key-ce_back_link"] [data-testid="stElementContainer"]:has(div.stButton) {
  position: absolute; inset: 0; z-index: 2;
}
[class*="st-key-ce_back_link"] div.stButton { height: 100%; }
[class*="st-key-ce_back_link"] div.stButton > button {
  width: 100%; height: 100%; padding: 0; border: none; background: transparent;
  box-shadow: none; color: transparent; cursor: pointer;
}

/* 화면 하단 버튼 줄을 화면 밑에 고정한다(recipe_confirm의 응/시작·다른 레시피,
   substitution_confirm의 네/아니요 등 - 컨테이너 key가 "_footer_buttons"로 끝나는
   화면마다 재사용). position:fixed는 뷰포트 기준이라 스크롤은 물론 Ctrl+휠 브라우저
   확대/축소로 뷰포트 배율이 바뀌어도 항상 화면 맨 아래에 붙어있다(별도 JS 없이 CSS
   표준 동작). block-container 자체는 안 건드리고 이 컨테이너만 흐름에서 빼내는
   것이라, 그 자리에는 각 화면에서 같은 높이만큼 빈 여백(spacer)을 넣어 마지막
   콘텐츠가 고정 버튼에 가려지지 않게 한다. */
[data-testid="stLayoutWrapper"]:has([class*="_footer_buttons"]) {
  position: fixed; left: 50%; bottom: 0; transform: translateX(-50%);
  width: 100%; max-width: 430px;
  background: transparent;
  padding: 14px 22px calc(20px + env(safe-area-inset-bottom, 0px));
  z-index: 50;
}
[data-testid="stVerticalBlock"][class*="_footer_buttons"] { gap: 10px; }

/* cooking_step 하단의 데모용 예시 버튼들 - ui/html의 .footer-nav 알약 버튼처럼 작게,
   가운데 정렬로 줄바꿈되게 만든다. 이 컨테이너의 내부 stVerticalBlock은 기본이
   flex-direction:column(세로 쌓기)인데, row+wrap으로 바꿔서 가로로 흐르다 넘치면
   다음 줄로 줄바꿈되게 한다. 각 버튼은 use_container_width=False로 둬서 텍스트
   길이만큼만 폭을 차지하게 한다(cooking_step.py에서 이미 그렇게 호출함). */
[data-testid="stVerticalBlock"][class*="st-key-cs_demo_buttons"] {
  flex-direction: row; flex-wrap: wrap; justify-content: center; gap: 8px;
}
[class*="st-key-cs_demo_buttons"] [data-testid="stElementContainer"] { width: auto !important; }
[class*="st-key-cs_demo_buttons"] div.stButton > button {
  background: rgba(36,28,21,0.82); color: #fff; border: none; border-radius: 999px;
  padding: 9px 16px; font-size: 12.5px; font-weight: 600; box-shadow: none; white-space: normal;
}
[class*="st-key-cs_demo_buttons"] div.stButton > button:hover { background: rgba(36,28,21,0.95); }

/* 화면 전환(goto) 중 잠깐 끼워 넣는 로딩 스피너(.ce-loading) - 2026-08-20, "화면마다
   로딩화면" 요청. 다른 중앙 정렬 화면들과 같은 render_spacer() 패턴으로 수직 중앙에 둔다. */
.ce-loading { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:16px; }
.ce-spinner {
  width:42px; height:42px; border-radius:50%;
  border:4px solid var(--accent-soft); border-top-color: var(--accent);
  animation: ce-spin 0.8s linear infinite;
}
.ce-loading p { margin:0; font-size:14px; font-weight:700; color: var(--text-secondary); }
@keyframes ce-spin { to { transform: rotate(360deg); } }
</style>
"""


# ui/html/assets/style.css의 인라인 SVG 아이콘을 그대로 재사용한다(HTML 버전과 아이콘을
# 통일하기 위함 - 이전에는 이모지를 썼는데 OS/브라우저마다 이모지 렌더링이 달라 HTML과
# 어긋나 보였다). st.button 라벨은 순수 텍스트만 지원해서 HTML을 못 그리므로, 버튼 위의
# 마이크 표시만은 이모지(🎙️)를 그대로 둔다.
_SVG = '<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'

ICON_POT = _SVG.format(
    size=28,
    body='<path d="M4 3c0 1.5 1 2 1 3M8 3c0 1.5 1 2 1 3M12 3c0 1.5 1 2 1 3"/>'
    '<path d="M3 9h18v2a8 8 0 0 1-8 8h-2a8 8 0 0 1-8-8V9Z"/>'
    '<line x1="1" y1="9" x2="3" y2="9"/><line x1="21" y1="9" x2="23" y2="9"/>',
)
ICON_MIC = _SVG.format(
    size=15,
    body='<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z"/>'
    '<path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>',
)
ICON_SPEAKER = _SVG.format(
    size=14,
    body='<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>',
)
ICON_CHECK_CIRCLE = _SVG.format(size=26, body='<circle cx="12" cy="12" r="10"/><polyline points="8 12.5 11 15.5 16 9"/>')
ICON_CHECK_SMALL = _SVG.format(size=12, body='<path d="M20 6 9 17l-5-5"/>')
ICON_X_CIRCLE = _SVG.format(
    size=26, body='<circle cx="12" cy="12" r="10"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/>'
)
ICON_QUESTION_CIRCLE = _SVG.format(
    size=26,
    body='<circle cx="12" cy="12" r="10"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1.3 1-1.3 1.9"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
)
ICON_SPARKLE = _SVG.format(size=26, body='<path d="M12 3v6M12 15v6M3 12h6M15 12h6"/>')
_BASKET_BODY = '<path d="M3 11h18M12 3v3M7 5v1M17 5v1"/><path d="M4 11l1.2 8.4A2 2 0 0 0 7.2 21h9.6a2 2 0 0 0 2-1.6L20 11"/>'
ICON_BASKET = _SVG.format(size=21, body=_BASKET_BODY)
# 재료 이름별로 식재료 이모지를 하나씩 골라줄 파서가 없는 곳(실제 Supabase 조회 재료처럼
# 자유 형식 텍스트라 재료명만으로 식재료 종류를 안정적으로 못 알아냄 - start.py의
# _ingredients_text_to_chips() 참고)에서 재료 종류와 무관하게 두루 쓸 칩 아이콘.
# 이전엔 모든 칩에 당근(🥕) 이모지를 그대로 썼는데, 스팸·떡처럼 안 맞는 음식에도 당근이
# 붙어 보였다(2026-08-20, 사용자 지적) - 위 섹션 제목과 같은 바구니 아이콘을 작게 재사용.
ICON_BASKET_SM = _SVG.format(size=14, body=_BASKET_BODY)
_MIC_BODY = (
    '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z"/>'
    '<path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>'
)
ICON_MIC_MD = _SVG.format(size=22, body=_MIC_BODY)
ICON_MIC_LG = _SVG.format(size=34, body=_MIC_BODY)
ICON_PLAY = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 3 20 12 6 21 6 3"/></svg>'
ICON_CHEVRON_LEFT = _SVG.format(size=12, body='<polyline points="15 18 9 12 15 6"/>')


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def render_loading_overlay(message: str = "처리하고 있어요...") -> None:
    """전체 화면을 덮는 반투명 로딩 팝업(2026-08-23 요청) — 발화 인식 후 다음 화면으로
    넘어가기 전(LLM/DB 조회, TTS 합성 등 몇 초 블로킹되는 구간, voice_io._drain_mic_while()
    참고) 동안, "지금 뭔가 처리 중이니 다른 동작을 하지 말아달라"는 걸 명확하게 보여준다.

    st.dialog()(진짜 모달)는 버튼 클릭 등으로 여러 번의 rerun에 걸쳐 열고 닫는 흐름에
    맞춰져 있어서, "이 스크립트 실행 안에서 블로킹 대기가 끝나면 그냥 사라진다"는 이번
    쓰임새와는 안 맞는다 — 대신 이 markdown 하나만 그리면 되는 순수 CSS 오버레이를 쓴다.
    z-index를 최상단으로 두고 pointer-events:all로 밑에 있는 버튼/입력 클릭을 막아서
    시각적으로도 실질적으로도 "팝업"처럼 동작한다. 이 함수를 호출하는 코드가 블로킹
    작업을 끝내고 다음 st.rerun()으로 넘어가면(또는 이 함수를 그냥 다시 안 부르면) 다음
    화면 렌더링엔 이 markdown 자체가 없으니 자연히 사라진다 - 별도로 "닫기" 처리가 필요
    없다.
    """
    st.markdown(
        f'''
        <div style="position:fixed; inset:0; z-index:9999; background:rgba(0,0,0,0.45);
                    display:flex; align-items:center; justify-content:center;
                    pointer-events:all;">
          <div style="background:var(--surface); border-radius:20px; padding:28px 36px;
                      display:flex; flex-direction:column; align-items:center; gap:14px;
                      box-shadow:0 12px 32px rgba(0,0,0,0.25);">
            <div style="width:36px; height:36px; border-radius:50%;
                        border:4px solid var(--accent-soft); border-top-color:var(--accent);
                        animation:ce-loading-spin 0.8s linear infinite;"></div>
            <p style="margin:0; font-size:14.5px; font-weight:700; color:var(--text);">{message}</p>
          </div>
        </div>
        <style>
          @keyframes ce-loading-spin {{ to {{ transform:rotate(360deg); }} }}
        </style>
        ''',
        unsafe_allow_html=True,
    )


def render_spacer() -> None:
    """ui/html의 flex:1(수직 중앙 정렬용 빈 공간)에 대응하는 여백.

    HTML은 콘텐츠를 `<div style="flex:1;justify-content:center">` 하나로 감싸면 되지만,
    Streamlit은 st.button 같은 네이티브 위젯을 그렇게 감쌀 수 없다(각 위젯이 별도
    컨테이너로 렌더링됨). 대신 중앙에 두고 싶은 콘텐츠 앞뒤에 flex:1짜리 빈 블록을
    넣어 남는 공간을 위아래로 똑같이 나눠 갖게 한다(CSS의 .ce-spacer 및
    .block-container > stVerticalBlock 규칙 참고). 창 크기나 브라우저 확대/축소가
    바뀌어도 남는 공간 자체가 다시 계산되므로 항상 반응형으로 중앙 정렬된다.
    """
    st.markdown('<div class="ce-spacer"></div>', unsafe_allow_html=True)


def render_loading_screen(message: str = "불러오는 중...") -> None:
    """goto()로 화면을 전환할 때 실제 화면 대신 한 프레임 보여주는 스피너.

    특히 진짜 백엔드를 붙인 화면(recipe_confirm의 handle_utterance 조회, cooking_step의
    TTS 합성 등)으로 넘어갈 땐 다음 화면이 준비되기까지 몇 초씩 걸릴 수 있는데, 그 사이
    화면이 그냥 멈춘 것처럼 비어 보이지 않도록 render_spacer()로 다른 중앙 정렬 화면과
    같은 방식으로 화면 가운데에 띄운다(app.py의 두 단계 rerun 패턴과 짝을 이룸).
    """
    render_spacer()
    st.markdown(
        f'<div class="ce-loading"><div class="ce-spinner"></div><p>{message}</p></div>',
        unsafe_allow_html=True,
    )
    render_spacer()


# 2026-08-22~23 이력: TTS 합성 대기 중 로딩 인디케이터를 GIF → SVG 냄비 마스코트로
# 두 번 갈아탔었는데(render_tts_loading()/_TTS_LOADING_MASCOT_SVG였음), 2026-08-23
# 사용자가 "로딩바 다 제거하자, 의미없다 - 렉만 더 걸리는 느낌"이라고 확인해서 아예
# 없앴다. 원인은 voice_io.py::speak()가 0.2초마다 placeholder를 다시 그리던 폴링
# 루프였다 — 그 루프째 제거하고 지금은 그냥 블로킹으로 조용히 기다린다(자세한 경위는
# voice_io.py::speak() 주석 참고). 여기 함수·CSS(ce-tts-*)·SVG 상수가 전부 그 루프
# 안에서만 불렸어서 호출부가 없어지며 같이 죽은 코드가 됐길래 통째로 지웠다.


def render_brand(show_login: bool = False, username: str | None = None) -> bool:
    """show_login=True면 "ChefEar" 제목과 같은 줄 오른쪽에 로그인 아이콘 버튼을 나란히
    놓는다(2026-08-21, start 화면 요청 - 원래는 화면 쪽에서 별도 줄로 그렸었는데 제목과
    안 나란해서 여기로 옮김). 로그인 내비게이션(goto)은 이 파일이 모르는 app.py 쪽
    개념이라, 여기서는 버튼이 눌렸는지 bool만 돌려주고 실제 화면 전환은 호출부가 한다
    (render_back_link()와 같은 패턴).

    username이 주어지면(로그인 상태) 로그인 아이콘 대신 그 아이디를 보여준다
    (2026-08-22 요청) - 눌렀을 때 어디로 갈지(마이 레시피)도 이 파일이 모르는
    app.py 쪽 개념이라, 여기서도 클릭 여부만 bool로 돌려준다. 로그아웃은 여기서
    바로 하지 않고 그 마이 레시피 화면의 로그아웃 버튼에 맡긴다.
    """
    if not show_login:
        st.markdown(f'<div class="ce-brand"><span class="icon">{ICON_POT}</span> ChefEar</div>', unsafe_allow_html=True)
        return False
    left, right = st.columns([6, 1])
    with left:
        st.markdown(f'<div class="ce-brand"><span class="icon">{ICON_POT}</span> ChefEar</div>', unsafe_allow_html=True)
    with right:
        # 버튼이 자기 칸 왼쪽에 붙어서 화면 오른쪽 끝까지 안 갔다(실측 지적,
        # 2026-08-21) - my_recipe_actions_와 같은 방식으로 감싸는 세로 블록에
        # justify-content:flex-end를 줘서 칸 안에서 오른쪽 끝으로 민다.
        with st.container(key="brand_login_wrap"):
            if username:
                return st.button(f":material/person: {username}", key="brand_login_btn", help="마이 레시피")
            return st.button(":material/login:", key="brand_login_btn", help="로그인")


def render_back_link(label: str = "처음으로", key: str = "ce_back_link") -> bool:
    """ui/html의 .top-nav-back(뒤로가기 링크). 클릭되면 True를 반환한다."""
    with st.container(key=key):
        st.markdown(f'<div class="ce-back-link">{ICON_CHEVRON_LEFT}{label}</div>', unsafe_allow_html=True)
        return st.button(label, key=f"{key}_btn")


def render_section_title(text: str) -> None:
    st.markdown(f'<div class="ce-section-title"><span class="icon">{ICON_BASKET}</span>{text}</div>', unsafe_allow_html=True)


def render_badge(text: str) -> None:
    st.markdown(f'<span class="ce-badge">{text}</span>', unsafe_allow_html=True)


def render_typewriter_message(lines: list[str], *, key: str, speed_ms: int = 28) -> None:
    """AI 메시지를 아바타 아이콘·이름표·말풍선 카드 없이(2026-08-22 요청 — "챗봇 느낌
    안 나게, 글씨만 보이게") 여러 줄로 줄바꿈해서, 한 글자씩 순서대로 타자기처럼
    나타나게 그린다(recipe_confirm의 "이걸로 시작할까요?" 확인 질문용, 2026-08-22
    재요청 — 요리명/문장을 줄바꿈하고 요리명만 크게 강조).

    lines: 화면에 줄 단위로 보여줄 목록(예: ["된장찌개", "조회수 1위 표준 레시피예요.",
    "이걸로 시작할까요?"]). 첫 줄(보통 요리명)은 크고 굵게, 나머지는 보통 크기로
    그린다. 애니메이션은 줄 순서대로 한 줄씩 다 친 뒤 다음 줄로 넘어간다.

    st.markdown()에 <script>를 넣어도 브라우저가 innerHTML로 삽입된 스크립트는 실행하지
    않는다(render_audio_player()가 st.iframe()을 쓰는 것과 같은 이유) — 그래서 여기도
    st.iframe()으로 그려서 JS가 실제로 동작하게 한다.

    key로 세션 안에서 이미 재생한 메시지인지 추적한다 — 같은 화면이 다른 이유로(마이크
    입력 대기 등) 다시 그려질 때마다 애니메이션이 처음부터 또 재생되면 거슬리므로,
    한 번 재생된 key는 이후 정적 텍스트로 바로 보여준다.
    """
    played = st.session_state.setdefault("_typewriter_played", set())

    style = """
    <style>
      body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; text-align:center; }
      p { margin:0 0 4px; line-height:1.4; text-align:center; }
      p:last-child { margin-bottom:0; }
      .head { font-size:26px; font-weight:800; color:#ee7b36; }
      .rest { font-size:15px; font-weight:600; color:#241c15; }
    </style>
    """

    def _cls(idx: int) -> str:
        return "head" if idx == 0 else "rest"

    if key in played:
        rows = "".join(f'<p><span class="{_cls(i)}">{line}</span></p>' for i, line in enumerate(lines))
        st.iframe(f"{style}{rows}", height="content")
        return

    played.add(key)
    placeholders = "".join(
        f'<p><span class="{_cls(i)}" id="tw-{i}"></span></p>' for i in range(len(lines))
    )
    html = f"""
    {style}
    {placeholders}
    <script>
      const linesText = {json.dumps(lines)};
      let lineIdx = 0;
      let charIdx = 0;
      function tick() {{
        if (lineIdx >= linesText.length) return;
        const el = document.getElementById("tw-" + lineIdx);
        const text = linesText[lineIdx];
        if (charIdx <= text.length) {{
          el.textContent = text.slice(0, charIdx);
          charIdx += 1;
          setTimeout(tick, {speed_ms});
        }} else {{
          lineIdx += 1;
          charIdx = 0;
          setTimeout(tick, {speed_ms});
        }}
      }}
      tick();
    </script>
    """
    st.iframe(html, height="content")


def render_chat(rows: list[tuple[str, str]]) -> None:
    """rows: [(role, text), ...], role은 'user' 또는 'ai'."""
    parts = ['<div class="ce-transcript">']
    for role, text in rows:
        if not text:
            continue
        who = "나" if role == "user" else "ChefEar"
        icon = ICON_MIC if role == "user" else ICON_SPEAKER
        parts.append(
            f'<div class="ce-row"><span class="ce-avatar {role}">{icon}</span>'
            f'<p><span class="who {role}">{who}:</span>{text}</p></div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_chips(ingredients: list[dict], substituted_name: str | None = None, show_qty: bool = True) -> None:
    parts = ['<div class="ce-chip-grid">']
    for ing in ingredients:
        is_sub = ing["name"] == substituted_name
        cls = "ce-chip substituted" if is_sub else "ce-chip"
        suffix = " (대체)" if is_sub else ""
        qty_part = f' {ing["qty"]}' if show_qty and "qty" in ing else ""
        parts.append(f'<span class="{cls}">{ing["emoji"]} {ing["name"]}{qty_part}{suffix}</span>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _dots_html(total: int, current: int) -> str:
    parts = ['<div class="ce-dots">']
    for i in range(1, total + 1):
        cls = "active" if i == current else ("done" if i < current else "")
        parts.append(f'<span class="d {cls}"></span>')
    parts.append("</div>")
    return "".join(parts)


def render_dots(total: int, current: int) -> None:
    st.markdown(_dots_html(total, current), unsafe_allow_html=True)


def render_interactive_dots(total: int, current: int) -> int | None:
    """render_step_card()의 점(dots) - _dots_html()과 똑같이 생겼지만 실제 st.button()이라
    눌러서 그 단계로 바로 이동할 수 있다(2026-08-21, 조리순서 화면 요청). 클릭된 단계
    번호(1..total)를 반환하고, 아무 것도 안 눌렸으면 None을 반환한다.

    register_intro 등 다른 화면의 render_dots()(진행 단계 안내용, 클릭 불가)는 그대로
    둔다 - 이건 cooking_step처럼 "실제로 그 단계로 건너뛸 수 있어야" 의미 있는 화면
    전용이다.
    """
    target: int | None = None
    with st.container(key="cs_dots_row"):
        for i in range(1, total + 1):
            state = "active" if i == current else ("done" if i < current else "todo")
            if st.button(" ", key=f"cs_dot_{state}_{i:02d}", help=f"{i}단계로 이동"):
                target = i
    return target


_WAVE_HEIGHTS = [6, 10, 16, 24, 14, 22, 28, 18, 26, 12, 20, 9, 16, 24, 14, 8, 12, 6, 10, 6]


def _player_html() -> str:
    bars = "".join(f'<span style="height:{h}px"></span>' for h in _WAVE_HEIGHTS)
    return f'<div class="ce-player"><span class="ce-play-btn">{ICON_PLAY}</span><span class="ce-wave">{bars}</span></div>'


def render_player() -> None:
    """ui/html의 .player(재생 버튼 + 파형) - 카드 밖에서 단독으로 쓸 때만 이 함수를 쓴다.
    카드 안에 넣을 땐 render_step_card()를 써야 한다(아래 설명 참고)."""
    st.markdown(_player_html(), unsafe_allow_html=True)

_AUDIO_PLAYER_TEMPLATE = Template("""
<style>
  * { margin:0; padding:0; box-sizing:border-box;
      font-family: "Pretendard", -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; }
  .player { display:flex; align-items:center; gap:14px; background:#fbf6ec;
    border-radius:999px; padding:10px 16px; }
  .wave { flex:1; display:flex; align-items:center; gap:1.5px; height:26px; overflow:hidden; }
  .wave span { flex:1 1 0; min-width:0; border-radius:1px; background:#ee7b36; opacity:.4;
    align-self:center; transition: opacity .1s linear; }
  .wave span.played { opacity:1; }
</style>
<div class="player">
  <span class="wave" id="wave">$bars</span>
</div>
<audio id="audio" src="$audio_src" preload="auto" autoplay></audio>
<script>
  const audio = document.getElementById('audio');
  const wave = document.getElementById('wave');
  const bars = wave.querySelectorAll('span');

  // 실제 재생 위치에 맞춰 막대를 하나씩 "지나갔다"는 색으로 칠한다(진짜 파형 진행 표시).
  // 막대 높이 자체는 이미 실제 오디오 진폭으로 그려져 있다(render_audio_player 참고),
  // 여기서는 재생 헤드 위치만 표시한다.
  function updateProgress() {
    if (!audio.duration) { return; }
    const ratio = audio.currentTime / audio.duration;
    const played = Math.round(ratio * bars.length);
    bars.forEach(function (bar, i) { bar.classList.toggle('played', i < played); });
  }
  audio.addEventListener('timeupdate', updateProgress);
  audio.addEventListener('ended', function () {
    bars.forEach(function (bar) { bar.classList.remove('played'); });
  });
  // 2026-08-21: 재생 버튼을 없앴다(요청) - 자동재생만 믿는다. 브라우저 자동재생 정책으로
  // 막히면(드묾 - 사용자가 이미 페이지와 상호작용한 뒤라 대부분 허용됨) 이 위젯 안에서는
  // 더 이상 수동으로 재생을 시작할 방법이 없다 - "다시" 음성 명령/버튼으로 다시 이
  // 화면에 들어오면 재생을 다시 시도한다.
  // 2026-08-23 수정 — "재생 시작 부분이 씹혀 들림"(크롬에서 특히) 리포트 원인 중 하나로
  // 확인: <audio autoplay> 속성이 이미 자체적으로 재생을 시작한 직후(비동기) 이 스크립트가
  // 곧장 audio.play()를 한 번 더 불러서, 크롬이 그 두 시작 신호가 겹치는 걸 재생 살짝
  // 되감기/재시작으로 처리해 첫 음절이 손실됐던 것으로 보인다(정확한 내부 동작은 미확인).
  // autoplay가 이미 시작한 상태(paused=false)라면 이 명시적 호출을 건너뛰어서 이중 트리거를
  // 피한다 - autoplay가 막혀서 여전히 paused인 경우에만 이 폴백이 실행된다.
  if (audio.paused) {
    audio.play().catch(function () {});
  }
</script>
""")


def _compute_wave_bars(audio_path: str | Path, num_bars: int = 60, min_h: int = 4, max_h: int = 28) -> list[int]:
    """실제 wav 파형을 num_bars개 구간으로 나눠 구간별 RMS 진폭을 막대 높이(px)로 바꾼다.

    기존 _WAVE_HEIGHTS는 모든 문장에 똑같이 재사용되는 가짜(장식용) 값이었다 — 이 함수는
    합성된 wav를 실제로 읽어서, 조용한 구간은 낮게 시끄러운(강세가 있는) 구간은 높게
    나오도록 진짜 파형 모양을 만든다(2026-08-19, 사용자 요청).

    num_bars: 막대 폭은 CSS(_AUDIO_PLAYER_TEMPLATE의 .wave span, flex:1 1 0)가 재생바
    전체 너비를 이 개수만큼 나눠 정하므로, 개수를 늘리면 그만큼 막대 하나하나가 가늘어진다
    (2026-08-22 요청 — 막대가 두꺼운 블록처럼 보이지 말고 더 촘촘한 파형처럼 보이게, 20 ->
    60으로 늘림).
    """
    data, _ = sf.read(str(audio_path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if len(data) == 0:
        return [min_h] * num_bars
    chunk_size = max(1, len(data) // num_bars)
    rms_values = []
    for i in range(num_bars):
        start = i * chunk_size
        end = len(data) if i == num_bars - 1 else start + chunk_size
        chunk = data[start:end]
        rms_values.append(float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0)
    peak = max(rms_values) or 1.0
    return [round(min_h + (v / peak) * (max_h - min_h)) for v in rms_values]


def _wav_bytes_with_lead_silence(audio_path: str | Path, pad_ms: int = 250) -> bytes:
    """TTS 재생 시작 부분이 브라우저(특히 크롬)에서 살짝 씹혀 들리는 문제 완화용
    (2026-08-23 리포트 — "된장찌개"가 "장찌개"로 들림, 크롬에서 특히 뚜렷함).

    정확한 브라우저 내부 메커니즘은 확정 못 했다(크롬이 autoplay로 막 시작한 오디오에
    pop 방지용으로 아주 짧은 페이드인을 거는 것으로 추정 — 그렇다면 그 페이드인이
    실제 말소리의 첫 파열음(ㄷ 등)을 깎아먹는 것과 증상이 정확히 일치함, Chrome
    한정이라는 리포트와도 들어맞음). 원인을 정확히 몰라도, **재생용 데이터 맨 앞에
    짧은 무음을 붙여두면** 그 페이드인/시작 손실이 무음을 깎아먹지 실제 말소리를
    깎아먹지 않으므로 안전하게 완화된다.

    원본 캐시 파일(디스크)은 그대로 둔다 — _arm_tts_mute()가 그 파일의 실제 길이로
    마이크 무음 구간을 계산하므로 원본을 건드리면 안 된다(이 패딩만큼 재생 시간이
    늘어나는 건 그 함수의 0.6초 여유 안에서 대체로 흡수됨). 화면에 실제로 내보내는
    재생용 바이트만 이 함수를 거쳐서 만든다.
    """
    audio, sr = sf.read(str(audio_path), dtype="float32")
    pad_samples = int(sr * pad_ms / 1000)
    silence_shape = (pad_samples,) if audio.ndim == 1 else (pad_samples, audio.shape[1])
    padded = np.concatenate([np.zeros(silence_shape, dtype=np.float32), audio], axis=0)
    buf = io.BytesIO()
    sf.write(buf, padded, sr, format="WAV")
    return buf.getvalue()


def render_audio_player(audio_path: str | Path, height: int = 64, nonce: int | str = 0) -> None:
    """theme.py의 장식용 재생바(.ce-player)와 똑같이 생긴, 실제로 재생되는 위젯.

    st.audio()는 브라우저 기본 재생 컨트롤(탐색바 포함)을 그대로 노출해서 앱 디자인과
    안 어울린다 — 브라우저 네이티브 미디어 컨트롤은 CSS로 커스터마이징이 사실상 불가능하다
    (표준화된 크로스 브라우저 방법이 없음, Chromium의 ::-webkit-media-controls는 비표준·
    브라우저 업데이트마다 깨질 수 있음). 그래서 st.iframe()으로 이 카드와 똑같은
    모양(둥근 배경 + 막대 파형)의 HTML/JS를 직접 그려서 자동재생한다. render_step_card()의
    장식용 재생바는 건드리지 않고, 그 아래에 이 진짜 위젯을 별도로 놓는다.

    2026-08-21: 원래는 파형 옆에 원형 재생/정지 버튼도 있었는데(눌러서 수동 재생/정지),
    자동재생만으로 충분하다는 요청으로 버튼은 없애고 파형만 남겼다 - 이제 이 위젯은
    순전히 "재생 중" 진행 표시용이고 클릭해도 아무 반응이 없다.

    iframe이라 부모 문서의 CSS 변수(:root)를 못 물려받아서, .ce-player/.ce-wave와
    같은 색상값을 여기서 다시 하드코딩했다(위 CSS :root의 --surface-alt/--accent/
    --accent-soft 값과 동일 — 그쪽이 바뀌면 여기도 같이 바꿔야 함).

    막대 높이는 _compute_wave_bars()로 이 파일의 실제 진폭을 읽어서 그린다(고정된 가짜
    파형이 아님). <audio autoplay>를 넣어서 "다음"/"이전"으로 이 위젯이 새로 렌더링될
    때마다(=화면이 다시 그려질 때마다) 자동 재생을 시도한다 — 브라우저 자동재생 정책상
    100% 보장되진 않지만(사용자가 이미 페이지와 상호작용한 뒤라 대부분 허용됨), 막히면
    조용히 대기 상태로 남는다 - 2026-08-21 요청으로 재생 버튼을 없애서, 막혔을 때 이
    위젯 안에서 수동으로 다시 시작할 방법은 이제 없다(파형만 표시, 클릭 불가).

    nonce: "다시"(재청취)처럼 같은 파일을 같은 단계에서 다시 재생해야 할 때 쓴다 — audio_src가
    이전 렌더와 완전히 같은 문자열이면 Streamlit 프론트엔드(React)가 iframe의 srcDoc이
    안 바뀐 걸로 보고 DOM을 그대로 유지해버려서(리마운트 안 함) <audio autoplay>가 다시
    실행되지 않는다(2026-08-21, "다시" 재생 요청으로 확인됨). html 맨 앞에 안 보이는
    주석으로 넣어 매 호출마다 문자열 자체를 다르게 만들면 프론트엔드가 새 iframe으로
    인식해서 다시 로드 -> autoplay가 재실행된다.
    """
    data = _wav_bytes_with_lead_silence(audio_path)
    audio_src = "data:audio/wav;base64," + base64.b64encode(data).decode("ascii")
    bar_heights = _compute_wave_bars(audio_path)
    bars_html = "".join(f'<span style="height:{h}px"></span>' for h in bar_heights)
    html = f"<!-- replay-nonce:{nonce} -->\n" + _AUDIO_PLAYER_TEMPLATE.substitute(
        bars=bars_html,
        audio_src=audio_src,
    )
    st.iframe(html, height=height)


def render_audio_autoplay(audio_path: str | Path, nonce: int | str = 0) -> None:
    """재생바(원형 버튼+파형)는 안 보이고 음성만 자동재생되는, render_audio_player()의
    화면 없는 버전. "저장이 완료됐어요!" 화면처럼 안내 문구를 음성으로만 들려주고
    재생 컨트롤 자체는 화면에 남기고 싶지 않을 때 쓴다(2026-08-21).

    height=1(최소값 — st.iframe은 0을 허용 안 함, StreamlitInvalidHeightError)이라
    화면에 거의 자리를 차지하지 않지만, 안의 <audio autoplay>는 render_audio_player()와
    똑같이 동작한다 — nonce로 매 호출마다 문자열을 다르게 만들어야 재렌더 시에도
    프론트엔드가 iframe을 새로 마운트해 autoplay가 다시 실행된다(같은 이유는
    render_audio_player() 문서 참고).
    """
    data = _wav_bytes_with_lead_silence(audio_path)
    audio_src = "data:audio/wav;base64," + base64.b64encode(data).decode("ascii")
    html = f"<!-- replay-nonce:{nonce} -->\n<audio src=\"{audio_src}\" autoplay></audio>"
    st.iframe(html, height=1)


def render_step_card(
    total: int,
    current_step: int,
    step_text: str,
    show_player: bool = True,
    audio_path: str | Path | None = None,
    audio_nonce: int | str = 0,
) -> int | None:
    """조리 화면의 카드(점 표시 + 단계 텍스트 + 재생바)를 흰 박스 안에 그린다.

    순수 HTML(`<div class="ce-card">`)로 카드를 열고 여러 st.markdown 호출을 거쳐
    나중에 닫으면 안의 내용이 카드 밖으로 빠져나간다(각 st.markdown은 완전히 분리된
    HTML 조각이라 — 예전엔 이래서 카드 내용을 전부 한 st.markdown 호출로 합쳤었다).
    그런데 render_audio_player()가 쓰는 st.iframe()은 markdown 문자열 안에 넣을 수
    없는 별도 Streamlit 엘리먼트라 그 방법이 안 통한다. 그래서 실제 오디오가 있을 땐
    진짜 Streamlit 컨테이너(st.container(key="cs_step_card"))를 카드로 쓴다 — 그
    컨테이너가 만드는 실제 DOM 래퍼에 .ce-card와 같은 스타일을 입혀뒀고(위 CSS 참고),
    그 컨테이너의 자식으로 dots+제목(markdown)과 재생바(markdown 또는 iframe)를
    순서대로 넣으면 진짜로 같은 흰 박스 안에 nesting된다(2026-08-19, 재생바를 카드
    안에 넣어달라는 요청으로 구조 변경).

    audio_path가 주어지면 그 wav를 render_audio_player()로 카드 안에서 자동재생하고
    재생바(파형)도 그대로 보여준다(2026-08-22). audio_path가 None이면 아무것도 안 그린다.

    2026-08-21: 점을 눌러 그 단계로 바로 이동하고, 단계 텍스트 양옆 화살표로
    이전/다음 단계로 넘어갈 수 있게 해달라는 요청 - 이 함수는 순수 표시만 담당하고
    (theme.py는 orchestration을 모른다) 실제 단계 전환(세션 갱신·음성 재생)은
    호출부(screen_cooking_step())가 반환값을 보고 처리한다. 점 클릭과 화살표 클릭
    둘 다 같은 반환값(이동할 단계 번호)으로 합쳐서 돌려준다 - 호출부가 "누가
    눌렀는지"까지 구분할 필요는 없어서다.
    """
    nav_target: int | None = None
    with st.container(key="cs_step_card"):
        nav_target = render_interactive_dots(total, current_step)

        # vertical_alignment="center": 단계 텍스트가 여러 줄로 길어져도 화살표가 위쪽에
        # 붙지 않고 텍스트 블록 세로 중앙에 맞춰져서, 화살표와 텍스트가 시각적으로
        # "같은 줄"에 있는 것처럼 보이게 한다(2026-08-22 요청, 기본값 "top"이라 긴 텍스트일
        # 때 화살표가 첫 줄에만 붙어 보였음).
        # 화살표 버튼 자체는 CSS(cs_prev_arrow/cs_next_arrow, 36px 고정)로 이미 좁혀놔서
        # 칸을 예전만큼 넓게(1) 안 잡아도 된다 — 화살표 칸을 줄이고 그만큼 가운데 텍스트
        # 칸을 넓힌다(2026-08-22 요청).
        arrow_l, mid, arrow_r = st.columns([1, 10, 1], vertical_alignment="center")
        with arrow_l:
            if st.button(
                ":material/chevron_left:", key="cs_prev_arrow", help="이전 단계",
                disabled=current_step <= 1, use_container_width=True,
            ):
                nav_target = current_step - 1
        with mid:
            st.markdown(f'<p class="ce-step-title">{step_text}</p>', unsafe_allow_html=True)
        with arrow_r:
            # 2026-08-22 요청: 마지막 단계에서도 화살표를 막아두지 않는다 — 이 화살표가
            # "완료"로 넘어가는 유일한 화면 접점이 되도록, current_step==total일 때도
            # 눌리게 두고 nav_target을 total+1(범위 밖)로 돌려준다. 호출부
            # (screen_cooking_step())가 그 값을 "요리 완성" 신호로 해석해서 완료 화면으로
            # 보낸다 — 이 함수 자체는 orchestration을 몰라서 여기서 직접 화면 전환은 안 한다.
            if st.button(
                ":material/chevron_right:", key="cs_next_arrow", help="다음 단계",
                use_container_width=True,
            ):
                nav_target = current_step + 1

        # 2026-08-22 재요청: 단계 텍스트 밑에 재생바(파형)가 보여야 한다는 요청으로
        # render_audio_player()를 다시 쓴다(같은 날 있었던 "재생 버튼 없애기" 요청은
        # 화면 전환 중 반짝이는 별개의 speak() 호출들에만 적용 — voice_io.speak()의
        # hidden=True 파라미터 참고, 이 카드 자체의 상시 표시 재생바와는 다른 문제).
        if audio_path is not None:
            render_audio_player(audio_path, nonce=audio_nonce)
    return nav_target


def render_mic_bar(state: str, hint: str, listening: bool = True) -> None:
    """ui/html의 .mic-bar - 조리 화면(듣는 중)·등록 화면·인식 실패 화면(idle)에서 쓴다."""
    cls = "listening" if listening else "idle"
    st.markdown(
        f'<div class="ce-mic-bar"><span class="ce-mic-icon {cls}">{ICON_MIC_MD}</span>'
        f'<div class="ce-mic-status"><span class="state">{state}</span><span class="hint">{hint}</span></div></div>',
        unsafe_allow_html=True,
    )


def render_mic_bar_interactive(hint: str, key: str = "cs_mic_bar"):
    """render_mic_bar()의 실제 녹음 가능한 버전 - "듣는 중" 표시가 장식으로 끝나지 않고
    진짜 마이크 입력을 받는다(2026-08-19, cooking_step용으로 추가).

    render_big_mic()과 같은 2단계 구조: 이 바를 누르면 그 아래 진짜 st.audio_input()이
    나타나고, 그 위젯 자체의 녹음 버튼을 눌러야 브라우저 마이크 권한 프롬프트가 뜬다
    (커스텀 오버레이 버튼 하나로 브라우저 getUserMedia() 권한 요청까지 한 번에 흉내낼
    수 없음 - render_big_mic() 문서 참고). 녹음된 오디오(UploadedFile) 또는 아직 없으면
    None을 반환한다.

    register_dish_name.py/unclassified.py는 여전히 장식용 render_mic_bar()를 쓴다 -
    요청받은 화면(cooking_step)만 바꿨다.
    """
    state_key = f"{key}_show_recorder"
    st.session_state.setdefault(state_key, False)

    with st.container(key=key):
        st.markdown(
            f'<div class="ce-mic-bar"><span class="ce-mic-icon listening">{ICON_MIC_MD}</span>'
            f'<div class="ce-mic-status"><span class="state">듣는 중</span><span class="hint">{hint}</span></div></div>',
            unsafe_allow_html=True,
        )
        if st.button("마이크로 말하기", key=f"{key}_btn", use_container_width=True):
            st.session_state[state_key] = True

    if not st.session_state[state_key]:
        return None
    return st.audio_input("음성으로 말씀해주세요", key=f"{key}_input", label_visibility="collapsed")


def render_big_mic(ready: bool = False):
    """ui/html 01_start.html의 큰 원형 마이크 아이콘 — 상시(실시간) 마이크 연결의 상태
    표시용 장식 요소.

    2026-08-23 이전엔 이 아이콘 밑에 "마이크 켜기" 버튼을 누르면 st.audio_input()(그때그때
    녹음하는 옛날 방식)이 나타나는 구조였는데, 실시간 스트리밍 마이크(voice_io.listen(),
    webrtc_streamer(desired_playing_state=True))로 넘어오면서 그 흐름 자체가 안 맞게
    됐다(리포트: "저건 녹음 기능이지 실시간 대화 시작 버튼이 아니다") — 실제 연결은
    이 화면이 그리는 listen()이 화면에 렌더링되는 순간 자동으로 시작되므로(사용자가
    브라우저에 마이크 권한을 이미 준 적 있으면 클릭 없이 곧장 연결됨), 버튼을 눌러야
    뭔가 시작되는 구조 자체가 필요 없어졌다. 그래서 아이콘 모양(펄스 애니메이션 포함)은
    그대로 두고, 버튼과 옛 녹음 위젯만 없앴다 — 이제 순수하게 "지금 실시간으로 듣고
    있다"는 상태를 보여주는 장식 요소다(실제 듣기/인식은 이 화면이 별도로 부르는
    listen("start")가 담당).

    ready(2026-08-23 추가) — "준비됐는지 안 됐는지 모르겠다"는 리포트로 추가. 호출부
    (screen_start())가 voice_io.mic_is_playing()으로 실제 webrtc 연결 상태를 확인해서
    넘겨준다 — 연결 전엔 계속 회색(기존 그대로), 연결되고 나면 다른 화면의 "듣는 중"
    표시와 같은 강조색+번지는 링(.ce-big-mic.ready, theme.py CSS 참고)으로 바뀌고
    안내문도 "듣고 있어요"로 바뀐다. 아직 연결 전에 말해봐야 안 들리므로, 이 색 전환
    자체가 "지금은 말해도 소용없다"는 신호 역할을 한다.
    """
    cls = "ce-big-mic ready" if ready else "ce-big-mic"
    hint = "듣고 있어요 · 편하게 말씀해주세요" if ready else "마이크 연결 중이에요, 잠시만 기다려주세요"
    with st.container(key="ce_big_mic"):
        st.markdown(
            f'<div class="ce-big-mic-wrap"><span class="{cls}">{ICON_MIC_LG}</span></div>'
            f'<p class="ce-hint">{hint}</p>',
            unsafe_allow_html=True,
        )
