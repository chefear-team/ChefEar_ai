"""ui/html/assets/style.css와 같은 디자인 토큰을 Streamlit용으로 옮긴 공통 스타일/컴포넌트.

Streamlit 기본 위젯(st.button 등)은 그대로 쓰고, 배지·카드·재료칩·대화 로그처럼
Streamlit 기본 컴포넌트로 표현하기 어려운 조각만 st.markdown(unsafe_allow_html=True)로
그린다. docs/ChefEar_PRD_SDD_v0.8.md 3.3의 화면 구성(①~⑥)을 그대로 따른다.
"""
import base64
import io
import json
import re
from pathlib import Path
from string import Template

import numpy as np
import soundfile as sf
import streamlit as st

# 2026-08-26 요청 — 상단 "ChefEar" 아이콘+글자 로고를 실제 브랜드 로고 이미지로 교체.
# ui/theme.py 자신이 ui/ 바로 밑에 있어서 .parent가 곧 ui/ 폴더 — images/ 하위 경로만
# 더하면 된다(voice_io.py의 PROJECT_ROOT 패턴과 같은 방식, 계층만 하나 덜 올라감).
# 모듈 임포트 시 딱 한 번만 파일을 읽어 base64로 인코딩해서 캐시해둔다(Streamlit이
# 매 rerun마다 이 모듈을 다시 import하지 않고 이미 로드된 모듈 객체를 재사용하므로,
# 모듈 최상단 코드는 프로세스 생애주기 동안 한 번만 실행됨 — 매번 디스크에서 다시
# 안 읽어도 됨). 파일이 없거나(팀원 로컬 등) 읽기 실패해도 서비스가 죽으면 안 되므로
# (EC-05와 같은 정신) 조용히 None으로 남겨서 render_brand()가 예전 아이콘+글자로
# 대체(fallback)하게 한다.
_LOGO_PATH = Path(__file__).resolve().parent / "images" / "chefear_logo_투명.png"
try:
    _LOGO_DATA_URI = "data:image/png;base64," + base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
except Exception:
    _LOGO_DATA_URI = None

# 2026-08-26 요청 — 바깥 배경(.stApp, 모바일 폭 카드 바깥쪽 뷰포트 전체)에 배경 이미지를
# 입힌다. 원본(ui/images/chefear_배경.png)이 2816x1536 PNG로 6.2MB나 돼서 그대로
# base64로 CSS에 박으면 매 페이지 로드마다 8MB 넘게 더 얹는 꼴이라(무거운 화면 잔상
# 스크립트에 시달린 오늘 밤 성능 감각으로 볼 때 절대 좋을 게 없음), 미리 리사이즈+JPEG
# 재압축해서 로컬에 별도 캐시 파일로 저장해두고(_BG_OPTIMIZED_PATH) 그걸 읽어서 인코딩한다
# (최초 1회만 리사이즈, 이후엔 캐시 파일만 읽음 — PIL을 매 프로세스 시작마다 또 돌릴
# 필요 없음). 원본이 사람 손으로 바뀔 수 있어서 원본보다 캐시가 더 오래됐으면(또는
# 캐시가 아직 없으면) 그때만 다시 만든다.
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

.ce-brand { display:flex; align-items:center; gap:8px; font-size:22px; font-weight:800; color:var(--text); margin-top: -35px; }  /* 2026-08-26: 로고 위로 15px -> 로그인 버튼과 별도로 20px 추가(-35px) 재요청 */
.ce-brand .icon { color: var(--accent); display:inline-flex; }
/* 2026-08-26 — 로고 이미지 버전(.ce-brand-logo). 원본(1024x559)엔 "당신의 AI 요리
   파트너" 부제도 같이 그려져 있어서, 아이콘+글자 한 줄(22px)보다 세로로 더 크다 —
   상단 한 줄(로그인 버튼과 나란한 자리)에 자연스럽게 앉도록 높이만 고정하고 너비는
   원본 비율 그대로 따라가게(auto) 한다. */
.ce-brand-logo { height: 90px; width: auto; display: block; }  /* 2026-08-26: 40->60->1.5배(90px) 재요청 */
/* 2026-08-26 — 로고와 같은 줄(render_brand()의 st.columns 오른쪽 칸)에 있는 로그인
   아이콘 버튼도 같이 위로 15px 옮겨서 로고와 나란한 높이를 유지한다. */
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
/* 2026-08-26 — 실제 DOM/computed style로 확인해보니 위 규칙의 :has()가 back-link의
   바로 안쪽 wrapper뿐 아니라, back-link를 자손으로 가진 *바깥* stLayoutWrapper까지
   같이 잡고 있었다 — st.container(key=f"screen_{screen}")로 화면 전체를 한 번 더
   감싸는 바깥 stLayoutWrapper도 "back-link를 안의 어딘가 자손으로 가진다"는 조건을
   만족하기 때문(:has()는 직계 자식이 아니라 모든 깊이의 자손을 다 잡음). 그 결과
   back-link가 있는 화면(전체)가 브랜드보다 앞으로 밀린다(대부분 화면은 내용이 짧아
   눈에 잘 안 띄었을 뿐, login처럼 폼이 길면 브랜드가 맨 아래로 밀려나는 게 뚜렷이
   보인다(실제 리포트: login 화면만 예외로 이 바깥 wrapper를 되돌린다) —
   [class*="st-key-screen_login"]을 자손으로 가진 stLayoutWrapper를 콕 집어서(back-link
   자체가 아니라 컨테이너 전체를 감싼 바깥 wrapper) order를 0으로 되돌린다, 그 안의
   back-link 자체는(더 안쪽 규칙이 그대로 적용돼) 화면 본문 맨 위(원래 자기 위치)에
   남고, 화면 브랜드 뒤에 정상적으로 온다 — 결과적으로 브랜드(그 첫 줄 back-link)
   순서가 된다.

   2026-08-26 추가 — cooking_complete에서 같은 증상(로고가 아래로 밀림)이 재현돼
   일반화한다. render_back_link()를 화면 맨 앞에서 부르는 화면은 전부 같은 구조적
   문제를 겪는다(register.py 3곳 + my_recipes.py 3곳 + cooking.py 1곳, grep으로 확인) —
   login 하나만 고치고 나머지는 리포트 들어올 때마다 하나씩 고치는 대신, 그 화면들
   전부를 미리 이 목록에 넣는다.

   ⚠️ 2026-08-26 이 규칙이 두 번째로 사라졌다가 복구됨 — VS Code에서 이 파일을 같이
   열어두고 있으면, VS Code 자체 버퍼(이 편집 이전 상태로 캐시된)를 저장(Ctrl+S)할 때
   방금 여기서 한 편집을 그대로 덮어써버리는 것으로 추정된다(git 커밋에도 이 규칙이
   빠진 채로 들어간 적 있음). 이 파일을 VS Code에서도 동시에 열어두고 있다면, Claude
   Code가 이 파일을 고친 직후엔 VS Code에서 그 파일을 반드시 새로고침(다시 불러오기)
   한 뒤에 저장할 것 — 안 그러면 이 규칙(그리고 이 파일의 다른 최근 수정분)이 또
   조용히 사라질 수 있다. */
[data-testid="stLayoutWrapper"]:has([class*="st-key-screen_login"]),
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
    # 2026-08-26 요청 — 배경 이미지(위 _BG_DATA_URI, 모듈 최상단 문서 참고). CSS 문자열
    # 전체를 f-string으로 바꾸면(중괄호가 수백 개라) 이스케이프 위험이 커서, 이 작은
    # 규칙 하나만 별도 <style> 블록으로 뒤에 이어붙인다 — 나중에 오는 규칙이 같은
    # 선택자(.stApp)의 앞쪽 규칙(단색 background)을 자연스럽게 덮어써서 !important
    # 없이도 이긴다. 이미지 로딩 실패 시(_BG_DATA_URI가 None) 아무것도 안 그려서
    # 원래 단색 배경 그대로 유지된다.
    if _BG_DATA_URI:
        st.markdown(
            f"<style>.stApp {{ background-image: url('{_BG_DATA_URI}'); "
            "background-size: cover; background-position: center; background-repeat: no-repeat; "
            "background-attachment: fixed; }}</style>",
            unsafe_allow_html=True,
        )


def render_loading_overlay(message: str = "말씀 잘 들었어요, 잠시만요...") -> None:
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
    # 2026-08-26 요청 — "자꾸 깜박깜박거려서 불편하다"는 지적으로 페이드인 추가. 이
    # div는 뜰 때마다 DOM에 새로 삽입되고 지워질 때는 그냥 통째로 제거되는 구조라(진짜
    # 모달이 아니라 markdown 하나짜리 순수 오버레이, 위 문서 참고), CSS transition으로
    # "사라질 때"까지 부드럽게 만들 수는 없다(이미 지워진 노드에 애니메이션을 걸 수
    # 없음) — 대신 "나타날 때"만 짧게 페이드인시켜서 뚝 튀어나오는 느낌을 줄인다.
    # 사라지는 쪽의 "반짝임"(뜨자마자 바로 없어짐)은 _drain_mic_while()의 최소 표시
    # 시간 보장으로 따로 막는다.
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
    """예상 못한 예외가 화면 그리다 말고 터졌을 때 쓰는 전체 화면 안내(2026-08-26 요청 —
    "예방 차원으로 다른 에러들에 대해서도 셋팅"). app.py::main()의 최상위 try/except가
    부른다.

    render_loading_overlay()와 같은 순수 CSS 오버레이 패턴(스피너 대신 경고 아이콘) —
    이미 일부 그려진 화면 위를 덮어서, 사용자에게 원본 스택트레이스/기술적 에러 문구
    대신 이 문구 하나만 보이게 한다. 실제 예외 내용은 화면에 안 보이고 서버 콘솔에만
    남는다(EC-05와 같은 정신 — 사용자에게는 조용히 실패하되 개발자는 원인을 추적할 수
    있어야 함, 호출부인 app.py::main()의 except 블록 참고).

    이건 화면 안 개별 실패(TTS 합성 실패 등, speak() 자신의 st.warning())를 대체하는
    게 아니다 — 그런 곳들은 이미 더 구체적이고 유용한 문구를 따로 갖고 있어서 그대로
    둔다. 이 함수는 그 어디서도 안 잡힌, 완전히 예상 못한 예외의 최후 방어선이다.
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
    접근을 막는 안내 화면(2026-08-26 요청 — "토큰 붙은 URL" 방식, app.py::main()
    상단의 _access_gate_ok() 참고).

    render_error_notice()와 같은 순수 CSS 풀스크린 오버레이 패턴을 재사용하지만
    쓰임새는 다르다 — 저건 "이미 그려진 화면 위를 덮는" 최후 방어선이고, 이건 그
    자체로 유일하게 그려지는 화면이다(호출부가 이 함수 직후 st.stop()으로 나머지
    렌더링/모델 워밍업/DB 연결을 전부 건너뛴다). inset:0 풀스크린 div라 밑에 아무것도
    안 그려져 있어도(= init_state() 등을 아직 안 거쳐도) 레이아웃이 안 깨진다.

    이 게이트는 완전한 보안이 아니다 — 랜딩페이지 버튼의 URL(?key=...)은 그 페이지
    HTML/JS를 열어보면(view-source) 그대로 노출된다. "우연히 주소를 직접 쳐보는"
    정도의 진입만 막는 용도다.
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
    # 2026-08-26 요청 — 아이콘+글자 로고를 실제 브랜드 로고 이미지(ui/images/
    # chefear_logo_투명.png)로 교체. 이미지를 못 읽은 경우(_LOGO_DATA_URI가 None —
    # 위 모듈 최상단 로딩부 참고)에는 예전 아이콘+글자로 조용히 대체해서 서비스가
    # 안 죽게 한다(EC-05와 같은 정신).
    if _LOGO_DATA_URI:
        brand_html = f'<div class="ce-brand"><img class="ce-brand-logo" src="{_LOGO_DATA_URI}" alt="ChefEar"></div>'
    else:
        brand_html = f'<div class="ce-brand"><span class="icon">{ICON_POT}</span> ChefEar</div>'
    if not show_login:
        st.markdown(brand_html, unsafe_allow_html=True)
        return False
    left, right = st.columns([6, 1])
    with left:
        st.markdown(brand_html, unsafe_allow_html=True)
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


# 2026-08-26 재요청 — 대화 기록(render_chat())에 "나: 다음...." 처럼 STT가 붙인 끝
# 문장부호(마침표·물음표·느낌표·쉼표·물결·말줄임표)가 그대로 노출돼 지저분해 보인다는
# 지적으로, 표시 직전에만 정규식으로 잘라낸다. classify_intent()가 이미 같은 목적으로
# 쓰는 문자 집합(intent_classifier.py의 `.rstrip("?!.,~ ")` 패턴)과 맞춰서 일관성을
# 유지한다 — 다만 거긴 str.rstrip()이고 여긴 사용자가 명시적으로 정규식을 요청해서
# re.sub()로 구현. 문장 끝에서 저 문자들이 연속으로(말줄임표 등) 몇 개가 오든 한 번에
# 다 떼어낸다. 중간에 있는 물음표/쉼표는 의미에 영향을 줄 수 있어 안 건드린다(끝만).
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


def _wav_bytes_with_lead_silence(audio_path: str | Path, pad_ms: int = 450) -> bytes:
    """TTS 재생 시작 부분이 브라우저(특히 크롬)에서 살짝 씹혀 들리는 문제 완화용
    (2026-08-23 리포트 — "된장찌개"가 "장찌개"로 들림, 크롬에서 특히 뚜렷함).

    2026-08-24 — 250ms로도 여전히 앞부분이 들린다는 재확인 리포트로 450ms로 올림.
    _arm_tts_mute()의 0.6초 여유 안에는 여전히 들어오므로(0.45 < 0.6) 그쪽 계산은
    안 건드려도 된다. 그래도 여전히 잘려 들리면 다음 단계는 이 값을 더 올리기보다,
    브라우저 쪽 실제 페이드인 길이를 직접 재서(예: 개발자도구로 파형 캡처) 정확한
    원인부터 좁히는 게 낫다 — 무작정 올리면 문장 시작이 그만큼 늦게 들리기 시작해서
    "밀린다"는 인상을 오히려 키울 수 있다.

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


def render_processing_chime(nonce: int | str = 0) -> None:
    """"처리 중" 정적을 메우는 짧은 효과음 한 번(2026-08-26 요청 — "강사님이 얘가 진짜
    움직이고 뭔가를 하고있는지를 모르겠다고 하시는데" 피드백, 사용 중 정적이 길어서
    답답했다는 확인 후 도입). STT 인식 후 LLM/DB/TTS 처리가 몇 초 걸리는 동안
    (voice_io._drain_mic_while() 참고) 화면을 안 보고 있어도(이 프로젝트 핵심 컨셉
    자체가 "화면 안 보고 음성만으로") "지금 듣고 처리 중"이라는 걸 알 수 있게 하는
    청각 신호. render_loading_overlay()(화면 팝업)와 같은 지점, 같은 조건(0.4초 넘게
    걸릴 때만)에서 같이 트리거된다.

    TTS로 만든 음성이 아니라 순수 사인파를 그 자리에서 합성한다 — 실제 TTS(GPU,
    _GPU_LOCK)를 쓰면 지금 처리 중인 진짜 작업과 GPU를 다시 두고 경합해서 오히려
    응답이 더 늦어진다(이 신호음 자체가 "처리가 오래 걸린다"는 신호인데, 그걸 알리려고
    처리를 더 늦추는 건 앞뒤가 안 맞는다). render_audio_player()/render_audio_autoplay()가
    쓰는 _wav_bytes_with_lead_silence()는 TTS 씹힘 방지용 450ms 무음 패딩이 있어서
    여기엔 안 맞다(효과음은 트리거되는 바로 그 순간 들려야 의미가 있음) — 그래서
    디스크 파일도 안 거치고 패딩 없이 매번 새로 합성한다(짧은 사인파라 비용도 무시할
    만큼 작음).

    nonce: 호출마다 다른 값을 넘겨야 한다 — audio_src 문자열이 이전 렌더와 완전히
    같으면 프론트엔드가 iframe을 리마운트 안 해서 autoplay가 다시 실행되지 않는다
    (render_audio_player() 문서의 같은 이유). 호출부(_drain_mic_while())가 자기
    시작 시각(time.monotonic())을 그대로 넘겨서 매 호출마다 자연히 달라진다.
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
    html = f'<!-- chime-nonce:{nonce} -->\n<audio src="{audio_src}" autoplay></audio>'
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
    # 2026-08-26 재요청 — "그냥 연결 중"이라고만 하면 마이크 연결 자체가 실측으로
    # 9~10초, 느리면(다른 기기/네트워크 상황에 따라) 수십 초까지 걸리는 걸(위 문서
    # 참고, streamlit-webrtc 구조적 특성) 사용자가 얼마나 더 기다려야 할지 모른다는
    # 지적으로, 무엇을 하는 중인지+예상 소요 시간을 같이 안내한다.
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


# 2026-08-25 — render_screen_cleanup()이 쓰는, "오디오를 절대 안 만드는 화면" 목록.
# src/app.py::SCREENS의 각 screen_*() 함수 본문을 직접 확인해서 정함(speak()/
# _render_cached_speech()/render_step_card(audio_path=...) 호출이 하나도 없는 화면만).
# 화면을 새로 추가하거나 기존 화면에 오디오 호출을 새로 넣을 땐 이 목록도 같이 검토할 것.
_AUDIO_FREE_SCREENS = (
    "start",
    "register_ingredients",
    "register_steps",
    "register_dish_name",
    "register_intro",
    "login",
    "my_recipes",
    "edit_recipe",
)

# 2026-08-25 — render_screen_cleanup()이 쓰는, "텍스트 대체 입력칸을 절대 안 만드는
# 화면" 목록. src/app.py::main()의 화면별 listen() 호출부에서 show_text_fallback=False로
# 넘기는 화면만(voice_io.py::listen() 참고 — False면 st.text_input() 자체를 안 그림).
# 오디오 iframe과 같은 패턴의 잔상(cooking_complete의 "또는 텍스트로 입력" 칸이 start로
# 넘어간 뒤에도 남는 것)이 실측 확인돼 같은 방식으로 추가.
# no_match(2026-08-25 추가) — "초기"/"등록" 두 키워드만 반응하는 좁은 화면으로 바뀌면서
# (register.py::handle_no_match() 참고) show_text_fallback=False로 바뀜.
#
# 2026-08-27 전수 점검 — src/app.py::main()의 실제 listen()/listen_background_only()
# 호출부를 전부 교차검증한 결과, show_text_fallback=False로 부르는 화면이 이 목록에
# 5개 빠져 있었다(register_ingredients/register_steps/login/my_recipes/edit_recipe —
# 전부 직접 False를 넘기거나 listen_background_only()를 거쳐서 항상 False로 불림).
# ruleTextFallback()은 "이 목록에 없으면 = 이 화면이 정상적으로 만든 것"으로 간주해서
# unhide()해버리므로, 이 5개 화면에 있는 동안 다른 화면(cooking_step/register_intro/
# register_dish_name 등, show_text_fallback 기본값 True)에서 새어든 범용 텍스트
# 입력칸("또는 텍스트로 입력") 잔상을 못 잡고 오히려 되살렸을 것 — 아직 실사용
# 재현 리포트로 확인된 건 아니라(다른 마커들처럼 "재현됨"이 아니라 코드 대조로 찾은
# 것), 배포 전 실제 화면 전환으로 재검증할 것.
_NO_TEXT_FALLBACK_SCREENS = (
    "start",
    "recipe_confirm",
    "no_match",
    "register_ingredients",
    "register_steps",
    "login",
    "my_recipes",
    "edit_recipe",
)

# 2026-08-25 — fallback_buttons()와 같은 부류의 잔상을 no_match 화면에서도 실측 확인:
# screen_no_match()의 두 버튼(st.button()에 key= 없이 호출돼서 fallback_buttons()처럼
# 화면 접두사로 잡아낼 CSS key가 없음 — 버튼 문구로 직접 특정한다)이 no_match ->
# start(음성 "처음") 전환 뒤에도, 심지어 새로 생긴 st-key-screen_start 컨테이너
# *안에* 자식으로 남아있는 게 확인됐다(단순히 컨테이너 밖으로 새는 정도가 아니라
# React 재조정 과정에서 이전 화면의 자식 일부가 새 컨테이너 밑에 그대로 붙어버림).
# {"버튼 문구": "그 버튼이 원래 속한 화면"} — CURRENT가 그 화면이 아니면 잔상으로
# 판정해 지운다. 같은 증상이 다른 화면에서도 나오면 여기 계속 추가할 것.
#
# 2026-08-25 추가 확장 — register_dish_name -> start(음성 "처음") 전환에서 더 심한
# 사례를 발견: "취소" 버튼뿐 아니라 캡션("짐작한 이름: ...")·마이크 바 문구까지
# 통째로 새 screen_start 컨테이너 *안쪽 자식*으로 남아있었다. "취소"는 my_recipes.py/
# register.py 여러 화면이 같이 쓰는 흔한 문구라 그것만으론 어느 화면 잔상인지 특정할
# 수 없어서(잘못 지우면 다른 화면의 진짜 취소 버튼을 지울 위험) 버튼 문구 대신, 그
# 화면에서만 나오는 고유한 문구(예: register_dish_name의 "짐작한 이름")를 마커로 삼고
# "그 마커를 담은 자식부터 화면 컨테이너 끝까지(꼬리 전체)"를 지우는 방식으로 일반화했다
# — 뒤에 뭐가 더 붙어있든(캡션+마이크바+취소 버튼처럼 여러 종류가 섞여도) 한 번에 잡힌다.
#
# 2026-08-25 추가 — 값이 항상 화면 이름 "리스트"다(예전엔 문자열 하나였는데, "처음
# 화면으로" 문구가 cooking_complete/register_dish_name/register_ingredients/
# register_steps/complete 다섯 군데에서 같이 쓰이는 게 실측 확인돼 단일 소유자로는
# 표현이 안 됨 — CURRENT가 이 리스트 안에 있으면 정상, 없으면 잔상으로 판정).
#
# 2026-08-25 추가 통찰 — **음성으로 전환할 때가 버튼 클릭보다 잔상이 더 잘 남는다.**
# 버튼 클릭(예: cooking_complete의 "처음 화면으로")은 screen_*() 함수 "본문 실행
# 도중"에 reset_to_start()가 불려서 그 스크립트 실행이 그 자리에서 바로 끊긴다 —
# 그 화면 자신의 뒷부분(이 경우엔 버튼 자체)조차 이 실행에서 완전히 커밋되기 전이라
# 남을 거리 자체가 적다. 반면 음성 "처음"은 화면 본문이 SCREENS[screen]()로 완전히
# 다 그려진 *뒤에*, app.py 하단 dispatch 블록에서 별도로 처리되므로 화면 전체가
# 완전히 커밋된 상태에서 전환이 일어난다 — 남길 거리가 더 많다. 그래서 이 세션에서
# 버튼 클릭 테스트는 깨끗했던 케이스도 실제 음성으로 하면 새 잔상이 나오는 경우가
# 있었다(cooking_complete "처음 화면으로" 버튼 자체가 실사용 전체 플로우 테스트에서
# 잔상으로 남는 것 확인, 2026-08-25). **앞으로 잔상 테스트는 반드시 음성(또는 음성과
# 동등한 debug_panel 경로)으로 할 것 — 버튼 클릭만으로는 과소평가된다.**
_STALE_CONTENT_MARKERS = {
    "원래 레시피로 계속하기": ["no_match"],
    "새 레시피로 등록할래요": ["no_match"],
    # 2026-08-25(같은 날 밤) 사용자 실사용 재현 보고 — no_match 화면의 st.caption()
    # 안내문(register.py, EC-05/1.5 원칙 문구)이 "새 레시피로 등록할래요" 버튼 마커보다
    # *앞쪽*에 렌더링돼서, 그 버튼만 잡는 기존 마커로는 이 캡션까지는 못 잡았다(꼬리
    # 제거는 마커를 찾은 지점부터 뒤만 지우므로, 이 캡션은 그 버튼 마커보다 앞에 있어서
    # 버튼 마커의 "꼬리"에 포함이 안 됨) — 실측: "처음"으로 start 전환한 뒤에도 이
    # 캡션 문구만 혼자 남아있었음. 독립 마커로 추가.
    "실데이터 검색만으로 판단해요": ["no_match"],
    # 2026-08-26 추가 — no_match의 "새 레시피로 등록할래요" 버튼 바로 아래 로그인
    # 유도 배지(render_badge(), 2026-08-25에 st.caption()에서 바꾼 것)도 "실데이터
    # 검색만으로..." 마커의 꼬리에 원래 포함되긴 하지만, 이 잔상 부류가 조각마다
    # 비동기로 따로 새는 사례가 반복 확인돼서(위 "다른 레시피 찾을래요"/"비밀번호"
    # 마커들과 같은 이유) 이것도 독립 마커로 예방 추가.
    "로그인을 하시면 레시피를 등록할 수 있어요": ["no_match"],
    # 2026-08-25(같은 날 밤) 사용자 실사용 재현 보고 — register_intro(표준 레시피에
    # 없는 요리라 새로 등록할지 묻는 화면)의 마이크바 캡션('"네" 또는 "등록할래요"라고
    # 말해보세요', render_mic_bar() 호출부)과 그 아래 "네, 등록할래요"/"괜찮아요" 버튼
    # 행, 심지어 그 뒤에 register_ingredients의 "추가" 버튼까지 통째로 start로 샌 사례
    # 확인(등록 플로우를 실제로 몇 단계 진행한 뒤 "처음"으로 나온 경우). 이 캡션이
    # register_intro 본문에서 맨 앞쪽 위젯이라, 이 마커 하나의 꼬리 제거로 뒤따르는
    # 버튼 행+register_ingredients 잔여물까지 한 번에 같이 잡힌다.
    '"네" 또는 "등록할래요"라고 말해보세요': ["register_intro"],
    # 2026-08-26 사용자 실사용 재현 보고 — login 화면(아이디/비밀번호 입력 폼)에서
    # "처음으로 가기"로 나간 뒤 start에서 로그인 폼 전체(아이디/비밀번호 입력칸+
    # 로그인/회원가입 버튼)가 그대로 남는 잔상 확인. "아이디" text_input 라벨이
    # screen_login()의 login/signup 두 뷰 모두에서 공통으로 맨 앞에 오는 위젯이라
    # (my_recipes.py 확인), 이 마커 하나로 두 뷰 다 커버되고 꼬리 제거로 뒤따르는
    # 버튼들도 같이 잡힌다.
    "아이디": ["login"],
    # 2026-08-26 재현 추가 — "아이디" 마커로도 부족했다(실측!). 같은 login 잔상인데
    # 이번엔 "아이디" 입력칸은 안 남고 "비밀번호"부터 그 뒤(로그인/회원가입 버튼)만
    # 독립적으로 남는 경우가 확인됐다 — recipe_confirm의 배지+"다른 레시피 찾을래요"
    # 버튼이 따로 늦게 도착해 하나의 마커로 못 잡혔던 것과 같은 패턴(위 "다른 레시피
    # 찾을래요" 마커 주석 참고, 이 잔상 부류는 조각마다 비동기로 따로 도착해서 앞쪽
    # 마커 하나로는 못 잡을 때가 있다). "비밀번호"도 독립 마커로 추가.
    "비밀번호": ["login"],
    # 2026-08-25(같은 날 밤, 위와 같은 리포트 — 등록 플로우를 register_ingredients까지
    # 더 진행한 뒤 "처음") — register_intro 마커의 꼬리 제거로는 register_ingredients
    # 자체의 잔상(재료 칩은 이미 구조적 규칙 7로 잡히지만, 그 아래 텍스트 입력칸+
    # "추가"/"네, 맞아요" 버튼은 register_intro 마커의 꼬리 범위 밖 — 서로 다른 렌더링
    # 시점/컨테이너 자식이라 안 잡힘)까지는 못 잡는다. register_ingredients/
    # register_steps 각각 자기 화면 전용 텍스트 입력 라벨을 마커로 추가 — 두 화면 다
    # 그 입력칸이 본문에서 맨 마지막 위젯 그룹 시작이라, 꼬리 제거로 뒤따르는 버튼들도
    # 같이 잡힌다.
    "재료 추가(쉼표로 여러 개 가능)": ["register_ingredients"],
    "순서 추가": ["register_steps"],
    "짐작한 이름": ["register_dish_name"],
    # 2026-08-25 사용자 실사용 재현 보고 — cooking_step -> start(음성 "처음") 전환에서
    # 4번 규칙(fallback_buttons 버튼 3개, CSS key 기반)은 버튼만 지우고, 그 버튼들
    # 바로 위에 있는 마이크바 캡션("듣는 중"/"이전"·"다시"·"다음")과 fallback_buttons()
    # 자체의 안내문("음성이 잘 안 될 땐...")은 못 잡았다 — 같은 "꼬리 전체 제거" 방식으로
    # 보강. 이 마이크바 문구('"이전" · "다시" · "다음"')는 cooking_step 전용(다른 화면은
    # 다른 문구를 씀, screen_cooking_step()의 render_mic_bar() 호출부 확인).
    '"이전" · "다시" · "다음"': ["cooking_step"],
    # 2026-08-25 사용자 실사용 재현 보고 — 실제 음성으로 "닭도리탕" 조회 -> recipe_confirm
    # (레시피 소개 화면) -> "처음으로" -> start 전환에서, recipe_confirm의 재료 칩
    # (예: "닭 1마리", "당근 1/3개")과 "다른 레시피 찾을래요" 버튼까지 통째로 남는 것
    # 재현됨. screen_recipe_confirm()의 맨 첫 호출인 render_badge("조회수 1위 표준
    # 레시피 자동 선택 · 되묻지 않음 (FR-05)")를 마커로 써서, 그 뒤에 나오는
    # typewriter 메시지·재료 칩·마이크바·"다른 레시피 찾을래요" 버튼까지 한 번에
    # (꼬리 전체 제거로) 잡는다 — 마커가 화면 본문 맨 앞이라 뒤에 뭐가 오든 다 잡힘.
    # 2026-08-26 — /code-review 발견: 배지 문구 자체가 "조회수 1위 표준 레시피 자동
    # 선택 · 되묻지 않음 (FR-05)"에서 "조회수 1위 표준 레시피"로 짧아졌는데(cooking.py::
    # screen_recipe_confirm()의 render_badge() 호출부) 이 마커는 옛 문구 그대로 남아있어서
    # 실제 DOM엔 이 문자열이 다신 안 뜨는 죽은 마커였다 — 현재 배지 문구로 맞춘다.
    "조회수 1위 표준 레시피": ["recipe_confirm"],
    # 위 배지 마커 하나로는 부족했다(실측) — 배지+칩은 지워지는데 "다른 레시피
    # 찾을래요" 버튼만 따로 늦게 도착해서 배지가 이미 지워진 뒤라 "그 지점부터 꼬리
    # 전체 제거" 규칙의 앵커를 못 찾고 혼자 남는 사례 확인. 각자 독립적으로 잡히게
    # 버튼 자체도 별도 마커로 추가(register.py엔 같은 문구가 주석으로만 있고 실제
    # 버튼은 없음 — 안전하게 고유함, 2026-08-25 확인).
    "다른 레시피 찾을래요": ["recipe_confirm"],
    # 2026-08-25 사용자 실사용 재현 보고(전체 플로우 재검증 중) — 배지/버튼 마커로도
    # recipe_confirm 자신의 마이크바 캡션('"응" 또는 다른 요청을 말씀해주세요',
    # render_mic_bar() 호출부)이 여전히 새는 사례 확인 — 버튼과 같은 이유(비동기로
    # 따로 늦게 도착)로 추정, 독립 마커로 추가.
    '"응" 또는 다른 요청을 말씀해주세요': ["recipe_confirm"],
    # 위와 같은 이유로 예방적으로 추가 — render_typewriter_message()의 나머지 고정
    # 문구 두 줄(요리명은 매번 달라서 마커로 못 씀, 이 둘은 고정 문구라 가능).
    "조회수 1위 표준 레시피예요.": ["recipe_confirm"],
    "이걸로 시작할까요?": ["recipe_confirm"],
    # 2026-08-25 사용자 실사용 재현 보고(버그.png, st.iframe() 교체 이후에도 재현) —
    # 재료 칩 목록("재료 미리보기" 제목 + 칩들 + 마이크바 + 버튼)이 통째로 남는 사례
    # 계속 확인. "재료 미리보기"는 cooking.py::screen_recipe_confirm()에만 있는
    # 고유 문구(cooking_step은 "오늘의 재료"를 씀, register.py 재료 화면은 제목 없음).
    "재료 미리보기": ["recipe_confirm"],
    # 2026-08-25 사용자 실사용 전체 플로우 재현 보고 — 검색→확인→10단계 조리→완료→
    # 음성 "처음"까지 실제로 끝까지 가본 뒤 재현. "처음 화면으로" 문구는 cooking.py의
    # cooking_complete 버튼과 register.py의 register_dish_name/register_ingredients/
    # register_steps(뒤로가기 링크)·complete(버튼) 다섯 화면이 전부 같이 쓴다 — 그래서
    # 소유자를 리스트로 표현해야 한다(위 설명 참고).
    # 2026-08-26 재요청 이후 실사용 재현 보고(버그.png) — register.py::screen_no_match()에
    # "처음 화면으로" 뒤로가기 링크를 추가했는데(다른 화면과 통일하려던 요청) 이 owner
    # 리스트에 "no_match"를 안 넣었다. ruleStaleMarkers()가 그 링크(화면 첫 자식)를
    # "no_match 소속이 아닌 잔상"으로 오판해서 그 지점부터 화면 끝까지(=사실상 화면
    # 전체) 숨겨버렸다 — 음성 응답(TTS)은 정상 재생되는데 화면만 완전히 비어 보이는
    # 증상으로 실측 재현됨. no_match를 owner에 추가해서 자기 자신의 뒤로가기 링크를
    # 잔상으로 오판하지 않게 한다.
    "처음 화면으로": [
        "cooking_complete",
        "register_dish_name",
        "register_ingredients",
        "register_steps",
        "complete",
        "no_match",
    ],
}

# 2026-08-25 사용자 실사용 재현 보고(버그.png) — cooking_step에서 실제 대화를 나눈 뒤
# "처음"으로 start로 넘어가니, render_chat()이 그리는 대화 기록(render_chat()이 항상
# 출력하는 고정 wrapper `<div class="ce-transcript">`)까지 통째로 남아있었다. 대화
# 내용은 매번 달라서 텍스트 마커로 못 잡지만, 감싸는 클래스는 항상 같아서 그걸로
# 구조적으로 잡는다 — _STALE_CONTENT_MARKERS(텍스트 앵커 기반)와 별개의 규칙.
# render_chat()을 쓰는 화면 = cooking_step(cooking.py)·no_match(register.py)·
# recipe_confirm(cooking.py, 2026-08-26 추가 — render_typewriter_message() 대신
# render_chat()을 쓰도록 바뀜, cooking.py::screen_recipe_confirm() 참고). 이 목록에
# 추가를 빠뜨리면 keepLastOnly()가 "허용 안 된 화면"으로 보고 .ce-transcript를 전부
# 숨겨버린다 — 실제로 recipe_confirm에 막 render_chat()을 추가했을 때 "화면 전환은
# 되는데 챗 박스(조회 확인 문구)가 안 보인다"로 정확히 이 증상이 재현됐다(위 docstring
# 경고 "새 화면/새 위젯을 추가할 때 여기 쓰는 상수들도 같이 검토할 것"이 실제로 걸린
# 사례).
_CHAT_LOG_SCREENS = ("cooking_step", "no_match", "recipe_confirm")

# 2026-08-25 사용자 실사용 재현 보고(버그.png, st.iframe() 교체 이후에도 재현) —
# render_chips()가 그리는 재료 칩 목록(고정 wrapper `<div class="ce-chip-grid">`)도
# 같은 이유(내용이 매번 다른 요리의 재료라 텍스트 마커로 못 잡음)로 구조적 규칙이
# 필요하다. render_chips()를 쓰는 화면 = recipe_confirm·cooking_step(둘 다 cooking.py)·
# register_ingredients(register.py).
_CHIP_GRID_SCREENS = ("recipe_confirm", "cooking_step", "register_ingredients")

# 2026-08-25 — 로그인/회원가입 위젯(login_*/signup_* key)이 다른 화면으로 넘어간 뒤에도
# 남는 사례가 있어서(각 위젯이 개별 텍스트 마커로 잡혔었는데, "아이디"/"비밀번호" 같은
# 문구가 화면마다 다른 위치에 비동기로 나뉘어 도착해 위 마커 방식만으론 불안정했다),
# 이 화면들의 위젯을 공유하는 key 접두사로 구조적으로 잡는 규칙을 추가했다. login/signup
# 두 뷰(_login_view) 다 이 접두사를 쓴다(my_recipes.py::screen_login() 참고).
LOGIN_KEY_PREFIXES = ("login_", "signup_")

# ⚠️ 2026-08-26 재구성 — 이 아래 render_screen_cleanup()은 2026-08-25 새벽 세션에서 여러
# 시행착오를 거쳐 완성된 원본이 커밋 한 번 안 된 채로(git에 저장된 적 없음, 워킹 디렉토리
# 에서만 존재) 다른 세션의 편집 실수로 삭제됐다. git reflog·dangling object·VS Code Local
# History 전부 뒤졌지만 원본 소스 자체는 복구 못 했고, 위에 남아있던 데이터(각 상수)와
# chefear-screen-ghosting-investigation 메모리 기록(규칙별 원인/수정 내역이 상세히 남아있음)
# 을 근거로 기능적으로 재구성한 버전이다 — 원본과 100% 동일하다는 보장은 없으니, 배포 전
# 반드시 실제 브라우저로 화면 전환 잔상이 다시 깨끗한지 재검증할 것.
#
# 아래 JS는 st.html(unsafe_allow_javascript=True)로 메인 페이지 DOM에 직접 삽입된다
# (iframe이 아님 — window.parent가 아니라 document/window를 바로 쓴다, 2026-08-25에
# st.iframe()/components.html()에서 이걸로 교체한 이유는 전달 신뢰도 문제였다).
#
# ⚠️ 아래 문자열 안(코드·주석 전부)에는 "꺾쇠+영문자" 리터럴(예: script 태그·audio 태그·
# div 태그를 <> 있는 그대로 적는 것)을 절대 쓰지 말 것 — Streamlit의 살균 단계가 그 패턴을
# 실제 HTML 태그 시작으로 오인해서 이 지점부터 스크립트를 통째로 잘라버리는 게 실측
# 확인됐다(2026-08-25). 꼭 필요하면 String.fromCharCode(60)으로 런타임에 조립해서 쓴다.
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

  // 2026-08-26 재요청 — "RTCPeerConnection을 더 못 만든다"류 브라우저 수준 예외(파이썬
  // try/except가 원천적으로 못 잡는 영역 — streamlit_webrtc 프론트엔드 내부에서 던지는
  // JS 예외라 서버로 넘어오지도 않음, 오래 켜둔 탭에서 마이크 세대 재연결이 쌓이면
  // 브라우저의 PeerConnection 개수 상한에 부딪혀 발생)를 사용자에게 원본 에러 문구
  // 그대로 노출하는 대신, 친절한 안내로 갈아 보여준다. window.onerror/
  // unhandledrejection 둘 다 잡아서 "예외적인 에러 전부"를 넓게 덮는다(요청 원문) —
  // 특정 에러 문자열로 좁히지 않는다(다른 종류의 예상 못한 JS 예외도 같은 안내가
  // 사용자 입장에선 원본 스택트레이스보다 낫다는 판단). innerHTML 대신 createElement로
  // 조립한다(위 경고의 "꺾쇠+영문자 리터럴 금지"를 이 블록도 그대로 지키기 위해 — 태그
  // 문자열 자체를 아예 안 씀).
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
    window.addEventListener("error", showRetryToast);
    window.addEventListener("unhandledrejection", showRetryToast);
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

  // 규칙 5(구 8번, 로그인/회원가입) — login_*/signup_* key 위젯은 login 화면 밖으로
  // 새면 숨긴다(_STALE_CONTENT_MARKERS 텍스트 마커보다 안정적인 구조적 규칙).
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
      var matched = false;
      for (var p = 0; p < prefixes.length; p++) {
        if (rest.indexOf(prefixes[p]) === 0) {
          matched = true;
          break;
        }
      }
      if (!matched) continue;
      if (CURRENT === "login") unhide(el);
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

  // 규칙 7/8 — render_chat()/render_chips()의 고정 wrapper(.ce-transcript/.ce-chip-grid).
  // 내용이 매번 달라 텍스트 마커로 못 잡는 대신, 항상 같은 클래스로 구조적으로 잡는다.
  function ruleChatAndChips() {
    keepLastOnly(".ce-transcript", DATA.chatLogScreens);
    keepLastOnly(".ce-chip-grid", DATA.chipGridScreens);
  }

  function sweep() {
    ruleScreenContainers();
    ruleAudioFrames();
    ruleTextFallback();
    ruleFallbackButtons();
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

    app.py::main()이 SCREENS[screen]() 호출 직후(st.container(key=f"screen_{screen}")가
    닫힌 뒤) 매 rerun마다 부른다. 근본 원인은 Streamlit(1.61.1)/streamlit-webrtc 조합에서
    화면이 바뀔 때 이전 실행의 일부 엘리먼트가 안 지워지는 stale-widget 부류의 문제로
    추정되며(관련: streamlit/streamlit#14404, 아직 미해결) 화이트리스트 방식으로 하나씩
    막는 whack-a-mole 성격이 있다 — 새 화면/새 위젯을 추가할 때 여기 쓰는 상수들
    (_AUDIO_FREE_SCREENS/_NO_TEXT_FALLBACK_SCREENS/_STALE_CONTENT_MARKERS/
    _CHAT_LOG_SCREENS/_CHIP_GRID_SCREENS/LOGIN_KEY_PREFIXES)도 같이 검토할 것.

    마이크(webrtc_streamer())는 완전히 격리된 별도 origin-same-but-separate iframe에
    살아서 이 스크립트가 절대 못 건드린다(의도된 것 — 잔상은 지우되 상시 마이크 연결은
    안 끊는 게 이 함수의 핵심 제약, 위 파일 docstring 경고 참고).
    """
    payload = {
        "current": current_screen,
        "audioFreeScreens": list(_AUDIO_FREE_SCREENS),
        "noTextFallbackScreens": list(_NO_TEXT_FALLBACK_SCREENS),
        "chatLogScreens": list(_CHAT_LOG_SCREENS),
        "chipGridScreens": list(_CHIP_GRID_SCREENS),
        "loginKeyPrefixes": list(LOGIN_KEY_PREFIXES),
        "staleMarkers": _STALE_CONTENT_MARKERS,
    }
    html = _CE_SWEEP_JS.replace("__CE_SWEEP_DATA__", json.dumps(payload, ensure_ascii=False))
    st.html(html, unsafe_allow_javascript=True)
