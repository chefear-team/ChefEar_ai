"""ChefEar 공용 스타일·화면 컴포넌트(CSS, 아이콘, 배지, 카드, 재료칩, 대화 로그, 오디오 재생).

Streamlit 기본 위젯(st.button 등)은 그대로 쓰고, 배지·카드·재료칩·대화 로그처럼
Streamlit 기본 컴포넌트로 표현하기 어려운 조각만 st.markdown(unsafe_allow_html=True)로
그린다. docs/ChefEar_PRD_SDD_v0.9.md 3.4의 화면 구성을 따른다.
"""
import base64
import io
import json
import re
import time
from pathlib import Path
from string import Template

import numpy as np
import soundfile as sf
import streamlit as st

_LOGO_PATH = Path(__file__).resolve().parent / "images" / "chefear_logo_투명.png"
try:
    _LOGO_DATA_URI = "data:image/png;base64," + base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
except Exception:
    _LOGO_DATA_URI = None

_GOOGLE_ICON_PATH = Path(__file__).resolve().parent.parent / "src" / "ui" / "images" / "google_icon.png"
try:
    _GOOGLE_ICON_DATA_URI = "data:image/png;base64," + base64.b64encode(_GOOGLE_ICON_PATH.read_bytes()).decode("ascii")
except Exception:
    _GOOGLE_ICON_DATA_URI = None

_BG_PATH = Path(__file__).resolve().parent / "images" / "chefear_배경.png"
_BG_OPTIMIZED_PATH = Path(__file__).resolve().parent / "images" / "_chefear_배경_optimized.jpg"


def _load_bg_data_uri() -> str | None:
    try:
        if _BG_PATH.exists() and (
            not _BG_OPTIMIZED_PATH.exists() or _BG_PATH.stat().st_mtime > _BG_OPTIMIZED_PATH.stat().st_mtime
        ):
            from PIL import Image

            im = Image.open(_BG_PATH).convert("RGB")
            target_w = 1600
            if im.width > target_w:
                ratio = target_w / im.width
                im = im.resize((target_w, round(im.height * ratio)), Image.LANCZOS)
            im.save(_BG_OPTIMIZED_PATH, "JPEG", quality=78, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(_BG_OPTIMIZED_PATH.read_bytes()).decode("ascii")
    except Exception:
        return None


_BG_DATA_URI = _load_bg_data_uri()

CSS = """
<style>
:root {
  --bg: #FFF7ED;
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

[data-testid="stHeader"] { pointer-events: none; }
[data-testid="stExpandSidebarButton"] { pointer-events: auto; }

/* ui/html/assets/style.css의 body(#e9e2d3 바깥 배경) + .screen(카드 자체) 2단 구조를 그대로 옮김 */
.stApp { background: #e9e2d3; }
.block-container {
  max-width: 430px; background: var(--bg);
  padding: 20px 22px 44px;
  box-shadow: 0 20px 46px rgba(36, 28, 21, 0.14);

  margin: 20px auto;
  border-radius: 28px;
  border-top: 4px solid var(--accent);
  min-height: calc(100vh - 40px);
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

[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_my_recipes"]),
[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_edit_recipe"]) {
  flex: 1 0 auto !important;
}
[data-testid="stVerticalBlock"][class*="st-key-screen_my_recipes"],
[data-testid="stVerticalBlock"][class*="st-key-screen_edit_recipe"] {
  flex: 1 0 auto !important; display: flex !important; flex-direction: column !important;
}
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


[data-testid="stVerticalBlock"] { gap: 1.75rem; }
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

button[aria-label="Show password"], button[aria-label="Hide password"] {
  background: transparent; border: none; box-shadow: none;
}
div:has(> button[aria-label="Show password"]), div:has(> button[aria-label="Hide password"]) {
  background: transparent; border: none;
}

.ce-back-link { display:inline-flex; align-items:center; gap:4px; font-size:13px; color: var(--text-secondary); font-weight:700; margin-bottom: 4px; }

.ce-brand { display:flex; align-items:center; gap:8px; font-size:22px; font-weight:800; color:var(--text); margin-top: -10px; }
.ce-brand .icon { color: var(--accent); display:inline-flex; }

.ce-brand-logo { height: 90px; width: auto; display: block; }

[class*="st-key-brand_login_wrap"] { margin-top: -15px; }

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


[data-testid="stVerticalBlock"][class*="st-key-my_recipes_list"] {
  max-height: 60vh; overflow-y: auto; padding: 4px; margin: -4px;
}


[data-testid="stVerticalBlock"][class*="st-key-my_recipe_actions_"] {
  flex-direction: row; flex-wrap: nowrap; gap: 6px; justify-content: flex-end;
  flex-shrink: 0; width: auto;
}
[data-testid="stVerticalBlock"][class*="st-key-my_recipe_actions_"] [data-testid="stElementContainer"] {
  width: auto;
}

/* start 화면 상단 로그인 버튼 - 자기 칸 안에서 왼쪽에 붙어있던 걸 오른쪽 끝으로 민다. */
[data-testid="stVerticalBlock"][class*="st-key-brand_login_wrap"] {
  display: flex; align-items: center; justify-content: flex-end;
}

[class*="st-key-brand_row"] [data-testid="stHorizontalBlock"] {
  align-items: center;
}


.ce-step-num {
  width:26px; height:26px; min-width:26px; border-radius:50%; background: var(--accent);
  color:#fff; display:grid; place-items:center; font-weight:800; font-size:13px; margin-top:1px;
}


[data-testid="stVerticalBlock"][class*="st-key-reg_step_row_"] {
  background: var(--surface); border-radius: 16px; padding: 10px 16px;
  box-shadow: 0 4px 12px rgba(36,28,21,0.05); gap: 4px;
}

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


.ce-step-title { font-size:22px; font-weight:800; text-align:center; line-height:1.45; margin: 0 !important; }

[class*="st-key-cs_step_card"] div[data-testid="stHorizontalBlock"] { margin-top: 18px; }
[class*="st-key-cs_prev_arrow"] button, [class*="st-key-cs_next_arrow"] button {
  background: var(--surface-alt); border: 1px solid var(--border); color: var(--accent);

  width: 36px !important; min-width: 36px !important; margin: 0 auto;
}

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

.ce-center h1 { font-size:30px; font-weight:800; margin:6px 0 10px; }
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

.ce-big-mic.ready { background: var(--accent); color:#fff; border-color: var(--accent);
  box-shadow: 0 0 0 10px rgba(238,123,54,0.16); }

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


[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_login"]),
[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_signup"]),
[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_cooking_complete"]),
[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_register_dish_name"]),
[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_register_ingredients"]),
[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_register_steps"]),
[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_my_recipes"]),
[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_edit_recipe"])
{ order: 0; }

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
ICON_INBOX = _SVG.format(
    size=26,
    body='<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>'
    '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
)
_BASKET_BODY = '<path d="M3 11h18M12 3v3M7 5v1M17 5v1"/><path d="M4 11l1.2 8.4A2 2 0 0 0 7.2 21h9.6a2 2 0 0 0 2-1.6L20 11"/>'
ICON_BASKET = _SVG.format(size=21, body=_BASKET_BODY)
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
    if _BG_DATA_URI:
        st.markdown(
            f"<style>.stApp {{ background-image: url('{_BG_DATA_URI}'); "
            "background-size: cover; background-position: center; background-repeat: no-repeat; "
            "background-attachment: fixed; }}</style>",
            unsafe_allow_html=True,
        )

    if _GOOGLE_ICON_DATA_URI:
        st.markdown(
            "<style>"
            '[class*="st-key-login_google_btn"] button,'
            '[class*="st-key-signup_google_btn"] button {'
            f"background-image: url('{_GOOGLE_ICON_DATA_URI}') !important;"
            "background-repeat: no-repeat !important; background-position: 16px center !important;"
            "background-size: 20px 20px !important;"
            "}</style>",
            unsafe_allow_html=True,
        )


def render_loading_overlay(message: str = "말씀 잘 들었어요, 잠시만요...") -> None:
    """전체 화면을 덮는 반투명 로딩 팝업 — 발화 인식 후 다음 화면으로
    넘어가기 전(LLM/DB 조회, TTS 합성 등 몇 초 블로킹되는 구간, voice_io._drain_mic_while
    참고) 동안, "지금 뭔가 처리 중이니 다른 동작을 하지 말아달라"는 걸 명확하게 보여준다.
    """
    st.markdown(
        f'''
        <div style="position:fixed; inset:0; z-index:9999; background:rgba(0,0,0,0.45);
                    display:flex; align-items:center; justify-content:center;
                    pointer-events:all; animation:ce-overlay-fadein 0.18s ease-out;">
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
          @keyframes ce-overlay-fadein {{ from {{ opacity:0; }} to {{ opacity:1; }} }}
        </style>
        ''',
        unsafe_allow_html=True,
    )


def render_error_notice(message: str = "잠시 후 재시도 해주시길 바랍니다.") -> None:
    """예상 못한 예외가 화면 그리다 말고 터졌을 때 쓰는 전체 화면 안내. app.py::main의 최상위 try/except가
    부른다.
    """
    st.markdown(
        f'''
        <div style="position:fixed; inset:0; z-index:9999; background:rgba(0,0,0,0.6);
                    display:flex; align-items:center; justify-content:center;
                    pointer-events:all;">
          <div style="background:var(--surface); border-radius:20px; padding:28px 36px;
                      display:flex; flex-direction:column; align-items:center; gap:14px;
                      box-shadow:0 12px 32px rgba(0,0,0,0.25); max-width:320px; text-align:center;">
            <div style="width:44px; height:44px; border-radius:50%; background:var(--danger-bg);
                        color:var(--danger-text); display:flex; align-items:center;
                        justify-content:center; font-size:22px; font-weight:800;">!</div>
            <p style="margin:0; font-size:15px; font-weight:700; color:var(--text);">{message}</p>
          </div>
        </div>
        ''',
        unsafe_allow_html=True,
    )


def render_access_blocked() -> None:
    """랜딩페이지(https://chefear-landingpage.vercel.app) 버튼을 거치지 않은 직접 URL
    접근을 막는 안내 화면( "토큰 붙은 URL" 방식, app.py::main
    상단의 _access_gate_ok 참고).
    """
    st.markdown(
        '''
        <div style="position:fixed; inset:0; z-index:9999; background:var(--bg);
                    display:flex; align-items:center; justify-content:center;
                    pointer-events:all;">
          <div style="background:var(--surface); border-radius:20px; padding:32px 36px;
                      display:flex; flex-direction:column; align-items:center; gap:14px;
                      box-shadow:0 12px 32px rgba(0,0,0,0.25); max-width:340px; text-align:center;">
            <div style="width:44px; height:44px; border-radius:50%; background:var(--accent-soft);
                        color:var(--accent); display:flex; align-items:center;
                        justify-content:center; font-size:22px; font-weight:800;">🔒</div>
            <p style="margin:0; font-size:15px; font-weight:700; color:var(--text);">
              ChefEar 소개 페이지를 통해 들어와주세요.</p>
            <a href="https://chefear-landingpage.vercel.app" target="_blank" rel="noopener noreferrer"
               style="margin-top:4px; background:var(--accent); color:#fff; padding:10px 20px;
                      border-radius:999px; font-size:14px; font-weight:700; text-decoration:none;">
              ChefEar 소개 페이지로 이동
            </a>
          </div>
        </div>
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


def render_brand(show_login: bool = False, username: str | None = None) -> bool:
    """show_login=True면 "ChefEar" 제목과 같은 줄 오른쪽에 로그인 아이콘 버튼을 나란히
    놓는다. 로그인 내비게이션(goto)은 이 파일이 모르는 app.py 쪽
    개념이라, 여기서는 버튼이 눌렸는지 bool만 돌려주고 실제 화면 전환은 호출부가 한다
    (render_back_link와 같은 패턴).
    """
    if _LOGO_DATA_URI:
        brand_html = f'<div class="ce-brand"><img class="ce-brand-logo" src="{_LOGO_DATA_URI}" alt="ChefEar"></div>'
    else:
        brand_html = f'<div class="ce-brand"><span class="icon">{ICON_POT}</span> ChefEar</div>'
    if not show_login:
        st.markdown(brand_html, unsafe_allow_html=True)
        return False
    with st.container(key="brand_row"):
        left, right = st.columns([6, 1])
        with left:
            st.markdown(brand_html, unsafe_allow_html=True)
        with right:
            with st.container(key="brand_login_wrap"):
                if username:
                    label = f":material/person: {truncate_display_name(username)}"
                    return st.button(label, key="brand_login_btn", help=username)
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


_DISPLAY_NAME_LIMIT = 9


def truncate_display_name(name: str) -> str:
    if len(name) <= _DISPLAY_NAME_LIMIT:
        return name
    return name[:_DISPLAY_NAME_LIMIT] + "..."


_CHAT_TRAILING_PUNCT_RE = re.compile(r"[?!.,~…\s]+$")


def _clean_chat_text(text: str) -> str:
    return _CHAT_TRAILING_PUNCT_RE.sub("", text)


def render_chat(rows: list[tuple[str, str]]) -> None:
    """rows: [(role, text), ...], role은 'user' 또는 'ai'."""
    parts = ['<div class="ce-transcript">']
    for role, text in rows:
        if not text:
            continue
        who = "나" if role == "user" else "ChefEar"
        icon = ICON_MIC if role == "user" else ICON_SPEAKER
        display_text = _clean_chat_text(text)
        parts.append(
            f'<div class="ce-row"><span class="ce-avatar {role}">{icon}</span>'
            f'<p><span class="who {role}">{who}:</span>{display_text}</p></div>'
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
    """render_step_card의 점(dots) - _dots_html과 똑같이 생겼지만 실제 st.button이라
    눌러서 그 단계로 바로 이동할 수 있다. 클릭된 단계
    번호(1..total)를 반환하고, 아무 것도 안 눌렸으면 None을 반환한다.
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
<audio id="audio" src="$audio_src#$nonce" preload="auto" autoplay></audio>
<script>
// 2026-08-28 — 이 스크립트 본문 전체를 IIFE로 감싼다. 인라인 <script>는 전역 스코프에서
// 실행되는데, render_audio_player()가 rerun마다(조리 진행/"다시" 등) 다시 렌더되면
// Streamlit이 replaceChild로 이 <script>를 재주입하면서 이전 렌더의 `const audio`가
// 아직 전역에 살아있어 "Identifier 'audio' has already been declared" SyntaxError가 났다.
// 이 에러는 원래부터 계속 났는데, render_screen_cleanup()의 스윕 스크립트(window.onerror
// 핸들러를 설치함)가 DOMPurify에 잘려 안 돌던 동안엔 안 보였다 — base64 로더로 스윕이
// 실제로 돌기 시작하자 이 에러를 잡아 "잠시 후 재시도" 토스트를 반복해서 띄웠다.
// IIFE로 감싸면 const가 함수 스코프가 돼 재주입돼도 전역 충돌이 없다.
(function () {
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
  // 확인: audio 엘리먼트의 autoplay 속성이 이미 자체적으로 재생을 시작한 직후(비동기) 이 스크립트가
  // 곧장 audio.play()를 한 번 더 불러서, 크롬이 그 두 시작 신호가 겹치는 걸 재생 살짝
  // 되감기/재시작으로 처리해 첫 음절이 손실됐던 것으로 보인다(정확한 내부 동작은 미확인).
  // 2026-08-27 추가 발견 — 이 주석 안에 태그 모양 텍스트를 꺾쇠괄호로 직접 써넣으면
  // st.html(unsafe_allow_javascript=True)가 쓰는 DOMPurify 새니타이저가 스크립트 태그
  // 자체를 통째로 걸러내 버린다(Playwright로 실측 재현 — 이 스크립트를 한 줄씩 늘려가며
  // 이진탐색한 결과 바로 이 줄에서 처음 사라짐을 확인, ADD_TAGS로 script를 허용해놔도
  // 마찬가지). 이 재생바가 안 움직이고 "다시" 재생 시 소리 자체가 하나도 안 들리던
  // 실사용 리포트의 진짜 원인이 이거였다 — JS 문법 에러가 아니라 주석 문구가 우연히
  // 태그처럼 생겨서 새니타이저를 착각하게 만든 것. 이 주석(과 위 주석)에서 꺾쇠괄호를
  // 다 빼서 풀어 쓴 이유이니, 앞으로 이 스크립트 블록 안 주석에는 꺾쇠괄호를 쓰지 말 것.
  // autoplay가 이미 시작한 상태(paused=false)라면 이 명시적 호출을 건너뛰어서 이중 트리거를
  // 피한다 - autoplay가 막혀서 여전히 paused인 경우에만 이 폴백이 실행된다.
  if (audio.paused) {
    audio.play().catch(function () {});
  }
})();
</script>
""")


def _compute_wave_bars(audio_path: str | Path, num_bars: int = 60, min_h: int = 4, max_h: int = 28) -> list[int]:
    """실제 wav 파형을 num_bars개 구간으로 나눠 구간별 RMS 진폭을 막대 높이(px)로 바꾼다."""
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


def _wav_bytes_with_lead_silence(audio_path: str | Path, pad_ms: int = 450, tail_ms: int = 0) -> bytes:
    """TTS 재생 시작 부분이 브라우저에서 살짝 씹혀 들리는 문제 완화용."""
    audio, sr = sf.read(str(audio_path), dtype="float32")
    lead_samples = int(sr * pad_ms / 1000)
    tail_samples = int(sr * tail_ms / 1000)
    lead_shape = (lead_samples,) if audio.ndim == 1 else (lead_samples, audio.shape[1])
    tail_shape = (tail_samples,) if audio.ndim == 1 else (tail_samples, audio.shape[1])
    padded = np.concatenate(
        [np.zeros(lead_shape, dtype=np.float32), audio, np.zeros(tail_shape, dtype=np.float32)],
        axis=0,
    )
    buf = io.BytesIO()
    sf.write(buf, padded, sr, format="WAV")
    return buf.getvalue()


def render_audio_player(audio_path: str | Path, height: int = 64, nonce: int | str = 0) -> None:
    """theme.py의 장식용 재생바(.ce-player)와 똑같이 생긴, 실제로 재생되는 위젯."""
    data = _wav_bytes_with_lead_silence(audio_path)
    audio_src = "data:audio/wav;base64," + base64.b64encode(data).decode("ascii")
    bar_heights = _compute_wave_bars(audio_path)
    bars_html = "".join(f'<span style="height:{h}px"></span>' for h in bar_heights)
    html = _AUDIO_PLAYER_TEMPLATE.substitute(
        bars=bars_html,
        audio_src=audio_src,
        nonce=nonce,
    )
    st.html(html, unsafe_allow_javascript=True)


def render_audio_autoplay(audio_path: str | Path, nonce: int | str = 0) -> None:
    """재생바(원형 버튼+파형)는 안 보이고 음성만 자동재생되는, render_audio_player()의
    화면 없는 버전. "저장이 완료됐어요!" 화면처럼 안내 문구를 음성으로만 들려주고
    """
    data = _wav_bytes_with_lead_silence(audio_path)
    audio_src = "data:audio/wav;base64," + base64.b64encode(data).decode("ascii")
    html = f'<audio src="{audio_src}#{nonce}" autoplay></audio>'
    st.html(html)


def render_processing_chime(nonce: int | str = 0) -> None:
    """"처리 중" 정적을 메우는 짧은 효과음 한 번. STT 인식 후 LLM/DB/TTS 처리가 몇 초 걸리는 동안
    (voice_io._drain_mic_while 참고) 화면을 안 보고 있어도(이 프로젝트 핵심 컨셉
    자체가 "화면 안 보고 음성만으로") "지금 듣고 처리 중"이라는 걸 알 수 있게 하는
    청각 신호. render_loading_overlay(화면 팝업)와 같은 지점, 같은 조건(0.4초 넘게
    """
    sr = 24000
    duration_s = 0.16
    freq_hz = 880.0  # A5 — 튀지 않으면서 정적 사이에서 또렷하게 들리는 높이
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    tone = (0.25 * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)
    # 끝부분 20ms를 선형으로 0까지 내려서 뚝 끊기는 클릭음을 방지한다.
    fade_samples = int(sr * 0.02)
    if fade_samples > 0:
        tone[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, tone, sr, format="WAV")
    audio_src = "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    html = f'<audio src="{audio_src}#{nonce}" autoplay></audio>'
    st.html(html)


def render_step_card(
    total: int,
    current_step: int,
    step_text: str,
    show_player: bool = True,
    audio_path: str | Path | None = None,
    audio_nonce: int | str = 0,
) -> int | None:
    """조리 화면의 카드(점 표시 + 단계 텍스트 + 재생바)를 흰 박스 안에 그린다."""
    nav_target: int | None = None
    with st.container(key="cs_step_card"):
        nav_target = render_interactive_dots(total, current_step)

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
            if st.button(
                ":material/chevron_right:", key="cs_next_arrow", help="다음 단계",
                use_container_width=True,
            ):
                nav_target = current_step + 1

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
    """render_mic_bar()의 실제 녹음 가능한 버전 - "듣는 중" 표시가 장식으로 끝나지 않고"""
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
    """
    cls = "ce-big-mic ready" if ready else "ce-big-mic"
    hint = (
        "듣고 있어요 · 편하게 말씀해주세요"
        if ready
        else "마이크 연결을 위해 최적화 중이에요. 잠시만 기다려주세요. ( 약 10초 ~ 60초 소요 )"
    )
    with st.container(key="ce_big_mic"):
        st.markdown(
            f'<div class="ce-big-mic-wrap"><span class="{cls}">{ICON_MIC_LG}</span></div>'
            f'<p class="ce-hint">{hint}</p>',
            unsafe_allow_html=True,
        )


_AUDIO_FREE_SCREENS = (
    "start",
    "register_ingredients",
    "register_steps",
    "register_dish_name",
    "login",
    "signup",
    "my_recipes",
    "edit_recipe",
)

_NO_TEXT_FALLBACK_SCREENS = (
    "start",
    "recipe_confirm",
    "register_ingredients",
    "register_steps",
    "login",
    "signup",
    "my_recipes",
    "edit_recipe",
)

_STALE_CONTENT_MARKERS = {
    "재료 추가(쉼표로 여러 개 가능)": ["register_ingredients"],
    "순서 추가": ["register_steps"],
    "짐작한 이름": ["register_dish_name"],
    "네, 저장할게요": ["register_steps"],
    "네, 맞아요": ["register_ingredients"],
    '"이전" · "다시" · "다음"': ["cooking_step"],
    "음성이 잘 안 될 땐 아래 버튼으로도 진행할 수 있어요": ["cooking_step", "unclassified"],
    "조회수 1위 표준 레시피": ["recipe_confirm"],
    "다른 레시피 찾을래요": ["recipe_confirm"],
    '"응" 또는 다른 요청을 말씀해주세요': ["recipe_confirm"],
    # 위와 같은 이유로 예방적으로 추가 — render_typewriter_message()의 나머지 고정
    # 문구 두 줄(요리명은 매번 달라서 마커로 못 씀, 이 둘은 고정 문구라 가능).
    "조회수 1위 표준 레시피예요.": ["recipe_confirm"],
    "이걸로 시작할까요?": ["recipe_confirm"],
    "재료 미리보기": ["recipe_confirm"],
    "처음 화면으로": [
        "cooking_complete",
        "register_dish_name",
        "register_ingredients",
        "register_steps",
        "complete",
        "login",
        "my_recipes",
    ],
    # edit_recipe는 "마이레시피로"라는 자기 전용 문구로 render_back_link()를 화면 맨
    # 앞에서 부른다(signup이 "로그인 화면으로"를 쓰는 것과 같은 패턴) — 위와 같은
    # 이유로 자기 자신을 owner로 등록해둔다.
    "마이레시피로": ["edit_recipe"],
}

_CHAT_LOG_SCREENS = ("cooking_step", "recipe_confirm")

_CHIP_GRID_SCREENS = ("recipe_confirm", "cooking_step", "register_ingredients")

_MIC_BAR_SCREENS = ("recipe_confirm", "cooking_step", "unclassified", "register_dish_name")

_SINGLE_OWNER_WIDGET_KEYS = {
    "recipe_confirm_other_recipe_btn": "recipe_confirm",
    "register_dish_name_cancel_btn": "register_dish_name",
    "cooking_step_fallback": "cooking_step",
    "unclassified_fallback": "unclassified",
}

LOGIN_KEY_PREFIXES = ("login_", "signup_", "my_recipes_", "edit_recipe_")

_CE_SWEEP_JS = r"""
<script>
(function () {
  var DATA = __CE_SWEEP_DATA__;
  var CURRENT = DATA.current;
  var LT = String.fromCharCode(60); // 꺾쇠 리터럴 회피용(위 경고 참고)

  function hide(el) {
    if (!el) return;
    el.style.display = "none";
    el.style.pointerEvents = "none";
    el.setAttribute("aria-hidden", "true");
    el.setAttribute("data-ce-hidden", "1");
  }

  function unhide(el) {
    if (!el) return;
    if (el.getAttribute("data-ce-hidden") === "1") {
      el.style.display = "";
      el.style.pointerEvents = "";
      el.removeAttribute("aria-hidden");
      el.removeAttribute("data-ce-hidden");
    }
  }

  // 같은 화면이 자기 자신을 다시 그리며 생기는 중복(예: 미분류 발화로 인한 재실행)
  // 대응 — DOM 순서상 마지막 인스턴스만 남기고 나머지는 숨긴다. allowList에 CURRENT가
  // 없으면 이 화면엔 원래 있으면 안 되는 잔상이므로 전부 숨긴다.
  function keepLastOnly(selector, allowList) {
    var nodes = document.querySelectorAll(selector);
    if (allowList.indexOf(CURRENT) === -1) {
      for (var i = 0; i < nodes.length; i++) hide(nodes[i]);
      return;
    }
    for (var i = 0; i < nodes.length; i++) {
      if (i === nodes.length - 1) unhide(nodes[i]);
      else hide(nodes[i]);
    }
  }

  // 2026-08-26 — "RTCPeerConnection을 더 못 만든다"류 브라우저 수준 예외(파이썬
  // try/except가 원천적으로 못 잡는 영역 — streamlit_webrtc 프론트엔드 내부에서 던지는
  // JS 예외라 서버로 넘어오지도 않음, 오래 켜둔 탭에서 마이크 세대 재연결이 쌓이면
  // 브라우저의 PeerConnection 개수 상한에 부딪혀 발생)를 사용자에게 원본 에러 문구
  // 그대로 노출하는 대신, 친절한 안내로 갈아 보여준다. innerHTML 대신 createElement로
  // 조립한다(태그 문자열 자체를 아예 안 씀).
  //
  // 2026-08-28 수정 — 원래는 error/unhandledrejection을 무조건 다 잡아 토스트를 띄웠는데
  // (그땐 catch-all이 의도였음), 사소한 JS 에러에도 5초마다 반복해서 뜨는 게 실측
  // 확인됐다(예: 인라인 <script> 재주입 시 const 재선언 SyntaxError — 이건 별도로
  // _AUDIO_PLAYER_TEMPLATE를 IIFE로 감싸 고쳤지만, 다른 무해한 예외도 얼마든지 있을 수
  // 있음). 원래 이 안내가 겨냥한 "복구하면 되는 연결/WebRTC 예외"로만 좁힌다 — 그 외
  // 예외는 콘솔에만 남기고 토스트는 안 띄운다.
  function _looksRecoverableConnError(detail) {
    var s = String(detail || "").toLowerCase();
    return (
      s.indexOf("rtcpeerconnection") !== -1 ||
      s.indexOf("peerconnection") !== -1 ||
      s.indexOf("cannot create so many") !== -1 ||
      s.indexOf("setremotedescription") !== -1 ||
      s.indexOf("setlocaldescription") !== -1 ||
      (s.indexOf("ice") !== -1 && s.indexOf("connect") !== -1) ||
      s.indexOf("websocket") !== -1
    );
  }
  function _onGlobalError(e) {
    var detail =
      (e && e.message) ||
      (e && e.error && (e.error.message || e.error)) ||
      (e && e.reason && (e.reason.message || e.reason)) ||
      (e && e.reason);
    if (_looksRecoverableConnError(detail)) showRetryToast();
  }
  function showRetryToast() {
    if (document.getElementById("ce-error-toast")) return; // 이미 떠 있으면 중복 표시 안 함
    var toast = document.createElement("div");
    toast.id = "ce-error-toast";
    toast.style.cssText =
      "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;" +
      "background:#241c15;color:#fff;padding:14px 22px;border-radius:14px;" +
      "font-size:14.5px;font-weight:700;box-shadow:0 10px 28px rgba(0,0,0,0.3);" +
      "max-width:88vw;text-align:center;cursor:pointer;";
    toast.textContent = "잠시 후 재시도 해주시길 바랍니다.";
    toast.addEventListener("click", function () {
      toast.remove();
    });
    document.body.appendChild(toast);
    setTimeout(function () {
      if (toast.parentNode) toast.remove();
    }, 5000);
  }

  if (!window.__ceErrorToastInstalled) {
    window.__ceErrorToastInstalled = true;
    window.addEventListener("error", _onGlobalError);
    window.addEventListener("unhandledrejection", _onGlobalError);
  }

  // 규칙 1 — 화면 컨테이너(app.py::main()의 st.container(key=f"screen_{screen}")).
  // CURRENT와 클래스명이 안 맞는 이전 화면 컨테이너를 숨긴다.
  function ruleScreenContainers() {
    var wanted = "st-key-screen_" + CURRENT;
    var nodes = document.querySelectorAll('[class*="st-key-screen_"]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if ((el.className || "").indexOf(wanted) !== -1) unhide(el);
      else hide(el);
    }
  }

  // 규칙 2 — 오디오를 절대 안 만드는 화면(_AUDIO_FREE_SCREENS)에서 오디오를 담은
  // st.iframe이 남아있으면 숨긴다(컨테이너 삭제만으론 못 잡는 경우가 실측 확인됨).
  function ruleAudioFrames() {
    var isFree = DATA.audioFreeScreens.indexOf(CURRENT) !== -1;
    var frames = document.querySelectorAll("iframe");
    var audioTag = (LT + "audio").toLowerCase();
    for (var i = 0; i < frames.length; i++) {
      var f = frames[i];
      var srcdoc = (f.srcdoc || "").toLowerCase();
      if (srcdoc.indexOf(audioTag) === -1) continue; // 오디오 iframe이 아님
      if (isFree) {
        // 2026-08-26 사용자 실사용 재현 보고 — cooking_complete에서 "처음"으로 start로
        // 넘어간 뒤에도 완료 멘트가 계속 들림. hide()는 iframe 자체를 display:none으로
        // 숨길 뿐, 그 iframe은 완전히 별개 문서(같은 origin이지만 진짜 iframe 경계)라
        // 안의 오디오 재생 자체는 안 멈춘다 — 화면만 안 보이고 소리는 계속 나는 것.
        // hide() 전에 iframe 내부 문서로 들어가 오디오 요소를 직접 pause+mute한다
        // (기존 st.iframe() 시절에도 같은 이유로 있었던 로직, 재구성 시 누락됐던 부분).
        try {
          var doc = f.contentDocument;
          var audios = doc ? doc.querySelectorAll("audio") : [];
          for (var j = 0; j < audios.length; j++) {
            audios[j].pause();
            audios[j].muted = true;
            audios[j].volume = 0;
          }
        } catch (e) {
          // 크로스오리진 등으로 접근 자체가 막히면 조용히 넘어간다 — hide()만이라도 적용.
        }
        hide(f);
      } else {
        unhide(f);
      }
    }
  }

  // 규칙 2b — 2026-08-27 st.iframe()->st.html() 전환(autoplay 차단 버그 수정) 이후
  // 새로 생긴 구멍. render_audio_player()/render_audio_autoplay()가 이제 오디오 태그를
  // iframe 없이 메인 문서에 직접 그린다 — 그래서 위 규칙 2(iframe 안쪽 오디오를
  // pause+mute하는 로직)가 더 이상 이 오디오들을 못 찾는다. 화면 컨테이너를
  // display:none으로 숨겨도(규칙 1) 오디오 태그 재생 자체는 안 멈춘다는 건 규칙 2의
  // 2026-08-26 발견과 완전히 같은 문제라 — st.iframe() 시절엔 audio-free 화면만
  // 챙기면 됐지만(다른 화면 오디오는 iframe 경계 안에서 자연히 격리됐었으므로), 이제는
  // 모든 오디오가 한 문서 안에 같이 있어서 화면이 뭐든 "지금 화면 소속이 아닌 오디오는
  // 다 멈춘다"로 일반화해야 한다 — 안 그러면 예: cooking_step 단계 음성이 아직 재생
  // 중인데 "완료"로 넘어가면 완료 멘트와 겹쳐 들리는 회귀가 재현될 수 있다(예전에
  // "두 번 겹쳐 들린다"로 여러 번 리포트됐던 것과 같은 부류).
  function ruleStaleAudio() {
    var audios = document.querySelectorAll("audio");
    for (var i = 0; i < audios.length; i++) {
      var a = audios[i];
      var screenEl = a.closest('[class*="st-key-screen_"]');
      if (!screenEl) continue; // 화면 컨테이너 밖(아직 마운트 중 등)이면 건드리지 않음
      var m = (screenEl.className || "").match(/st-key-screen_(\S+)/);
      if (!m) continue;
      var owner = m[1];
      // 2026-08-27(추가) — "초기메뉴로 돌아가도 파형 카드가 화면에 남아있다" 실측
      // 리포트. 원인: 이 규칙은 소리(재생)만 멈추지 화면에 보이는 파형 카드
      // (render_audio_player()의 .player + 파형)는 안 지운다 — st.iframe() 시절엔
      // ruleAudioFrames()가 iframe 통째로 hide()해서 소리+화면이 한 번에 없어졌는데,
      // st.html() 전환 뒤로는 <audio>와 .player가 같은 문서의 형제 노드로 바뀌어서
      // 오디오만 멈추면 그 옆 파형 카드는 그대로 남는다. .player 자체의 파형 애니메이션
      // 스크립트(_AUDIO_PLAYER_TEMPLATE)는 안 건드리고, 그 바깥의 stElementContainer
      // (Streamlit이 이 st.html() 위젯 하나에 씌우는 표준 래퍼, ruleTextFallback()가
      // 이미 같은 선택자를 씀)를 화면 소속에 따라 껐다 켰다만 한다.
      var widgetContainer = a.closest('[data-testid="stElementContainer"]') || a.parentElement;
      if (owner === CURRENT) {
        unhide(widgetContainer);
        // 2026-08-27(추가, 실사용 리포트 — "1단계 음성이 아예 안 나옴") — 화면 전환
        // 찰나의 레이스로 옛 화면(예: recipe_confirm) 기준의 낡은 감시 인터벌이 이
        // 오디오를 아직 못 지워진 채 살아있다가 "소속 아님"으로 오판해 바로 아래
        // 분기로 먼저 pause+mute+volume=0을 걸어버리는 경우가 실측 확인됐다(그 다음
        // 틱에서야 CURRENT가 정정돼 여기로 들어옴). hide()/unhide()는 data-ce-hidden
        // 마커로 짝이 맞는데, 이 mute 로직만 짝(원상복구)이 없어서 한 번 꺼지면
        // 영원히 안 켜지는 게 진짜 원인이었다 — 우리가 직접 끈 경우(data-ce-muted
        // 마커로 표시)에 한해서만 여기서 되돌린다(자연 종료(ended)나 사용자가 건드린
        // 경우는 마커가 없으므로 안 건드림).
        if (a.getAttribute("data-ce-muted") === "1") {
          a.removeAttribute("data-ce-muted");
          a.muted = false;
          a.volume = 1;
          console.log("[AUDIO_SWEEP] recover(was-wrongly-paused) owner=" + owner +
            " paused=" + a.paused + " ended=" + a.ended +
            " currentTime=" + a.currentTime.toFixed(2) + " duration=" + (a.duration || 0).toFixed(2));
          if (a.paused && !a.ended) a.play().catch(function () {});
        }
        continue; // 지금 화면 소속 — 정상
      }
      // 2026-09-02 — "끝음절 1~2글자가 잘려 들린다" 리포트 조사. 아직 실측으로 확정은
      // 못 했지만(1.5 원칙 — 지어내지 않되 잠정 대응임을 밝힘), 코드에 이미 문서화된
      // 레이스(2026-08-27 주석, 위 owner===CURRENT 분기 참고) — 화면 전환 찰나에 이
      // 감시 인터벌이 실제로는 지금 화면 소속인 오디오를 "낡은 화면 소속"으로 오판해
      // pause()를 걸었다가 다음 틱에서야 정정하는 경우가 있음 — 가 유력한 후보다.
      // 정정이 안 따라잡으면 그 지점에서 멈춘 채 다시 안 이어질 수 있다. 오디오가
      // 자연히 끝나기 1초도 안 남았으면(진짜 stale이든 오판이든) pause()를 걸지 않고
      // 그냥 끝까지 재생되게 둔다 — 진짜 stale 오디오가 1초 더 들리는 부작용은
      // 미미하지만, 라이브 오디오가 실수로 멈춰서 영영 안 이어지는 쪽이 훨씬 나쁘다.
      // console.log는 다음 실측 때 이 판단이 실제로 발동하는지(오판인지 진짜 stale인지)
      // 바로 확인하기 위한 진단용 — 원인 확정되면 정리할 것.
      var nearEnd = a.duration && !isNaN(a.duration) && (a.duration - a.currentTime) < 1.0;
      if (!a.paused && nearEnd) {
        console.log("[AUDIO_SWEEP] skip-pause(near-end) owner=" + owner + " current=" + CURRENT +
          " currentTime=" + a.currentTime.toFixed(2) + " duration=" + a.duration.toFixed(2));
      } else if (!a.paused) {
        console.log("[AUDIO_SWEEP] pause(stale) owner=" + owner + " current=" + CURRENT +
          " currentTime=" + a.currentTime.toFixed(2) + " duration=" + (a.duration || 0).toFixed(2));
        a.pause();
        a.muted = true;
        a.volume = 0;
        a.setAttribute("data-ce-muted", "1");
      }
      hide(widgetContainer);
    }
  }

  // 규칙 3 — 텍스트 대체 입력칸을 절대 안 만드는 화면(_NO_TEXT_FALLBACK_SCREENS)에서
  // listen()의 범용 텍스트 입력칸이 남아있으면 그 stElementContainer 조상을 숨긴다.
  function ruleTextFallback() {
    var isNoFallback = DATA.noTextFallbackScreens.indexOf(CURRENT) !== -1;
    var inputs = document.querySelectorAll(
      'input[placeholder="마이크 대신 직접 타이핑해도 돼요"]'
    );
    for (var i = 0; i < inputs.length; i++) {
      var container = inputs[i].closest('[data-testid="stElementContainer"]');
      if (!container) continue;
      if (isNoFallback) hide(container);
      else unhide(container);
    }
  }

  // 규칙 4 — fallback_buttons()의 [이전][다시][다음] 버튼. key=f"{screen}_{한글버튼}"인데
  // Streamlit이 한글을 CSS 클래스로 낼 때 전부 "--"로 뭉개서 화면 접두사로만 판정한다.
  function ruleFallbackButtons() {
    var nodes = document.querySelectorAll('[class*="st-key-"]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var cls = el.className;
      if (typeof cls !== "string") continue;
      var at = cls.indexOf("st-key-");
      if (at === -1) continue;
      var rest = cls.slice(at + "st-key-".length);
      var tail = rest.indexOf("_--");
      if (tail === -1) continue;
      var owner = rest.slice(0, tail);
      if (owner === CURRENT) unhide(el);
      else hide(el);
    }
  }

  // 규칙 4b — 2026-08-27 추가. "취소"처럼 여러 화면이 같이 쓰는 흔한 버튼 문구는
  // 텍스트 마커로 소속 화면을 특정할 수 없다(_STALE_CONTENT_MARKERS에 "취소"를 못
  // 넣는 이유와 같음). 그런 위젯엔 화면 전용 key를 직접 줬고(예:
  // recipe_confirm_other_recipe_btn, register_dish_name_cancel_btn), 여기서
  // DATA.singleOwnerWidgetKeys({key: 소유 화면})를 순회하며 구조적으로(텍스트 무관)
  // 잡는다 — ruleScreenContainers()와 같은 원리, 대상만 화면 전체가 아니라 위젯 하나.
  function ruleSingleOwnerWidgets() {
    for (var key in DATA.singleOwnerWidgetKeys) {
      if (!Object.prototype.hasOwnProperty.call(DATA.singleOwnerWidgetKeys, key)) continue;
      var owner = DATA.singleOwnerWidgetKeys[key];
      var nodes = document.querySelectorAll('[class*="st-key-' + key + '"]');
      for (var i = 0; i < nodes.length; i++) {
        if (CURRENT === owner) unhide(nodes[i]);
        else hide(nodes[i]);
      }
    }
  }

  // 규칙 5(구 8번, 로그인/회원가입/마이레시피 등) — login_*/signup_*/my_recipes_*/
  // edit_recipe_* 같은 key 접두사를 가진 위젯은 그 접두사의 소유 화면 밖으로 새면
  // 숨긴다(_STALE_CONTENT_MARKERS 텍스트 마커보다 안정적인 구조적 규칙).
  //
  // 2026-09-01 — 원래는 "CURRENT === 'login' || CURRENT === 'signup'"처럼 소유
  // 화면을 하드코딩한 OR 목록이었다. signup_google_btn처럼 "signup_" 접두사 key를
  // 가진 위젯이 signup 화면 자신에서도 숨어버리는 버그(login만 있고 signup이
  // 빠짐)로 한 번 걸렸는데, 화면을 추가할 때마다 이 목록도 매번 같이 고쳐야 하는
  // 구조라 재발 가능성이 그대로 남는다 — 대신 접두사 자체("login_" -> "login")에서
  // 소유 화면 이름을 매번 계산해서, LOGIN_KEY_PREFIXES에 접두사만 추가하면 이 목록도
  // 자동으로 따라오게 일반화했다(ruleSingleOwnerWidgets()의 owner 기반 방식과 동일).
  function ruleLoginSignup() {
    var prefixes = DATA.loginKeyPrefixes;
    var nodes = document.querySelectorAll('[class*="st-key-"]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var cls = el.className;
      if (typeof cls !== "string") continue;
      var at = cls.indexOf("st-key-");
      if (at === -1) continue;
      var rest = cls.slice(at + "st-key-".length);
      var owner = null;
      for (var p = 0; p < prefixes.length; p++) {
        if (rest.indexOf(prefixes[p]) === 0) {
          owner = prefixes[p].slice(0, -1); // "login_" -> "login"
          break;
        }
      }
      if (owner === null) continue;
      if (CURRENT === owner) unhide(el);
      else hide(el);
    }
  }

  // 규칙 6 — 텍스트 마커 기반 "꼬리 전체 제거"(_STALE_CONTENT_MARKERS). CURRENT 화면
  // 컨테이너의 직계 자식을 매번 전부 unhide()로 초기화한 뒤, 그 화면 소속이 아닌 마커
  // 문구를 담은 자식을 찾으면 그 지점부터 끝까지 전부 숨긴다.
  function ruleStaleMarkers() {
    var container = document.querySelector(
      '[class*="st-key-screen_' + CURRENT + '"]'
    );
    if (!container) return;
    var children = Array.prototype.slice.call(container.children);
    for (var i = 0; i < children.length; i++) unhide(children[i]);

    for (var i = 0; i < children.length; i++) {
      // 2026-08-26 사용자 실사용 재현 보고 — cooking_step에서 대화 기록 전체가
      // 안 보임. 원인: render_chat()이 이제(같은 날 "전체 다 보이게" 재요청으로)
      // chat_log 전체를 보여주는데, 그 안엔 recipe_confirm에서 나온 옛 AI 메시지
      // ("조회수 1위 표준 레시피예요." 등, _STALE_CONTENT_MARKERS의 recipe_confirm
      // 전용 마커와 텍스트가 똑같음)가 **정상적으로** 남아있다 — 근데 아래 마커
      // 매칭이 이 자식의 textContent를 통째로 검사하다가 그 문구를 "recipe_confirm
      // 잔상이 cooking_step에 샜다"로 착각해서 대화 기록 전체를 숨겨버렸다(실측
      // 확인 — 부모 stElementContainer에 data-ce-hidden="1"). .ce-transcript/
      // .ce-chip-grid는 규칙 7/8(ruleChatAndChips(), 구조적 클래스 기반)이 이미
      // 전담하고 있으므로, 여기 텍스트 마커 검사에서는 그 내용을 통째로 건너뛴다
      // — 두 규칙이 같은 대상을 서로 다른 기준으로 판정하다 충돌하는 걸 막는다.
      if (children[i].querySelector(".ce-transcript, .ce-chip-grid")) continue;

      var text = children[i].textContent || "";
      var stale = false;
      for (var marker in DATA.staleMarkers) {
        if (!Object.prototype.hasOwnProperty.call(DATA.staleMarkers, marker)) continue;
        var owners = DATA.staleMarkers[marker];
        if (owners.indexOf(CURRENT) !== -1) continue; // 이 화면 소속 — 잔상 아님
        if (text.indexOf(marker) !== -1) {
          stale = true;
          break;
        }
      }
      if (stale) {
        for (var j = i; j < children.length; j++) hide(children[j]);
        break;
      }
    }
  }

  // 규칙 7/8/9 — render_chat()/render_chips()/render_mic_bar()의 고정 wrapper
  // (.ce-transcript/.ce-chip-grid/.ce-mic-bar). 내용이 매번 달라 텍스트 마커로 못
  // 잡는 대신, 항상 같은 클래스로 구조적으로 잡는다. keepLastOnly()는 전역
  // querySelectorAll이라 컨테이너 중첩 위치와 무관하게 잡는다는 점이 핵심 —
  // ruleStaleMarkers()(직계 자식만 훑음)가 못 잡는 깊이/위치의 잔상도 여기선 잡힌다.
  function ruleChatAndChips() {
    keepLastOnly(".ce-transcript", DATA.chatLogScreens);
    keepLastOnly(".ce-chip-grid", DATA.chipGridScreens);
    keepLastOnly(".ce-mic-bar", DATA.micBarScreens);
  }

  function sweep() {
    ruleScreenContainers();
    ruleAudioFrames();
    ruleStaleAudio();
    ruleTextFallback();
    ruleFallbackButtons();
    ruleSingleOwnerWidgets();
    ruleLoginSignup();
    ruleStaleMarkers();
    ruleChatAndChips();
  }

  sweep();

  // 뒤늦게 도착하는 잔상(느린 rerun 연쇄 등)까지 잡기 위한 감시 — 화면 전환마다 이전
  // 감시자를 갈아치워서(전역 플래그로 중복 설치만 막던 예전 방식은 옛 화면 기준
  // closure가 새 화면 전환 뒤에도 계속 도는 문제가 있어, 재구성 시 항상 최신 closure로
  // 교체하는 쪽으로 정리함) 항상 지금 CURRENT 기준으로만 청소되게 한다.
  if (window.__ceSweepObserver) {
    window.__ceSweepObserver.disconnect();
    window.__ceSweepObserver = null;
  }
  if (window.__ceSweepInterval) {
    clearInterval(window.__ceSweepInterval);
    window.__ceSweepInterval = null;
  }

  window.__ceSweepObserver = new MutationObserver(function () {
    sweep();
  });
  window.__ceSweepObserver.observe(document.body, { childList: true, subtree: true });
  setTimeout(function () {
    if (window.__ceSweepObserver) {
      window.__ceSweepObserver.disconnect();
      window.__ceSweepObserver = null;
    }
  }, 60000);

  var ticks = 0;
  window.__ceSweepInterval = setInterval(function () {
    sweep();
    ticks += 1;
    if (ticks >= 20) {
      clearInterval(window.__ceSweepInterval);
      window.__ceSweepInterval = null;
    }
  }, 100);
})();
</script>
"""


def render_screen_cleanup(current_screen: str) -> None:
    """화면 전환 잔상(이전 화면의 버튼/텍스트/오디오/재료칩/대화기록 등이 새 화면 위에
    그대로 남는 문제) 최후 수단 — 브라우저에서 직접 이전 화면의 잔재를 찾아 숨긴다.
    """
    payload = {
        "current": current_screen,
        "nonce": time.monotonic(),
        "audioFreeScreens": list(_AUDIO_FREE_SCREENS),
        "noTextFallbackScreens": list(_NO_TEXT_FALLBACK_SCREENS),
        "chatLogScreens": list(_CHAT_LOG_SCREENS),
        "chipGridScreens": list(_CHIP_GRID_SCREENS),
        "micBarScreens": list(_MIC_BAR_SCREENS),
        "singleOwnerWidgetKeys": dict(_SINGLE_OWNER_WIDGET_KEYS),
        "loginKeyPrefixes": list(LOGIN_KEY_PREFIXES),
        "staleMarkers": _STALE_CONTENT_MARKERS,
    }
    js = _CE_SWEEP_JS.replace("__CE_SWEEP_DATA__", json.dumps(payload, ensure_ascii=False))
    # _CE_SWEEP_JS는 <script>...</script> 래퍼로 감싸여 있다 — base64 로더가 다시
    # <script>를 붙이므로 여기선 순수 JS 본문만 남긴다.
    js = js.strip()
    js = js.removeprefix("<script>").removesuffix("</script>").strip()

    js_b64 = base64.b64encode(js.encode("utf-8")).decode("ascii")
    st.html(
        f'<script>(0,eval)(decodeURIComponent(escape(atob("{js_b64}"))))</script>',
        unsafe_allow_javascript=True,
    )
