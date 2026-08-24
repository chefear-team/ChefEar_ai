# ui/ — 화면 디자인 프로토타입

`docs/ChefEar_PRD_SDD_v0.8.md` 3.3(화면 UI 구성)과 5장 시나리오 A~D, 그리고 전달받은
목업 이미지(된장찌개 조리 진행 화면)를 기준으로 만든 화면 프로토타입이다. 같은 화면 흐름을
**HTML**과 **Streamlit(.py)** 두 형식으로 구현했다.

`src/ui/`(팀 문서상 정식 위치, Streamlit 컴포넌트)와는 다르다 — 이 폴더는 `orchestration.pipeline`·
`stt/infer.py`·`tts/infer.py`가 아직 미완성이라 실제 백엔드에 연결할 수 없는 상태에서, 화면
디자인과 흐름만 먼저 눈으로 확인·시연할 수 있도록 만든 별도 프로토타입이다(가짜 데이터만 사용,
`ui/mock_data.py`). 나중에 세 조각이 갖춰지면 여기서 잡은 화면 구조를 `src/ui/`로 옮기면 된다.

## 화면 목록 (11개)

| 순서 | 화면 | 대응 요구사항 |
| --- | --- | --- |
| 01 | 시작 (자유발화 유도) | FR-01 |
| 02 | 레시피 확인 (표준 레시피 자동 채택) | FR-05 |
| 03 | 조리 진행 (메인 화면, 목업 이미지 기준) | FR-02, FR-03, 3.3 |
| 04 | 재료 대체 제안 확인 | FR-04 ①, 시나리오 B |
| 05 | 매칭 실패 정직 안내 | FR-04 ③, 시나리오 C |
| 06 | 신규 등록 제안 | FR-06, 시나리오 D |
| 07 | 신규 등록 1/3 — 요리명 | FR-06 |
| 08 | 신규 등록 2/3 — 재료 + 확인 체크포인트 | FR-06 |
| 09 | 신규 등록 3/3 — 순서 + 최종 확인 체크포인트 | FR-06 |
| 10 | 완료 (원본 보존 + user_custom 저장) | FR-08 |
| 11 | 음성 인식/의도분류 실패 Fallback | FR-16, AC-02/AC-09 |

## HTML 버전 (`ui/html/`)

정적 클릭 프로토타입. `ui/html/01_start.html`을 브라우저로 열거나, 전체 지도가 필요하면
`ui/html/flowmap.html`을 열면 된다. 서버·빌드 없이 파일을 더블클릭하면 바로 보인다.
공통 스타일은 `ui/html/assets/style.css` 하나에 모아뒀다.

**한계**: 화면 사이 이동은 `<a href>` 링크일 뿐이라 상태를 기억하지 않는다. 예를 들어 조리
화면(03)의 [이전]/[다시] 버튼은 실제로 이전 단계로 가는 게 아니라 같은 화면을 다시 보여준다
(정적 파일이라 단계별 실제 상태 전이는 Streamlit 버전에서만 동작한다).

## Streamlit 버전 (`ui/`)

```
streamlit run ui/app.py
```

HTML과 달리 **실제로 상태가 바뀐다**:

- 조리 화면의 [이전]/[다시]/[다음]이 `st.session_state.step_number`를 PRD 7.1.1 규칙대로
  진짜로 바꾼다(1단계에서 [이전]을 누르면 AC-08대로 "이전 단계 없음" 안내만 뜨고 그대로 유지).
- "감자 대신 양파 넣어도 돼?" 버튼을 누르면 재료 칩이 실제로 바뀌고 "(대체)" 표시가 붙는다.
- "바지락 넣어도 돼?" → 확인 화면에서 "네"를 누르면 `st.session_state.recipe` 자체가
  바지락된장찌개로 교체된다(FR-04 ①, 6.4).
- 신규 등록 화면은 재료·순서를 실제로 추가/삭제할 수 있는 입력창이다.
- 시작 화면의 자유 입력창은 요리명 문자열이 포함되는지만 보는 아주 단순한 매칭이다 —
  **실제 서비스의 `classify_intent()`(sentence-transformers 임베딩 유사도, FR-01)를
  대체하는 게 아니라 화면 흐름 시연용 자리표시자**다.

사이드바의 "화면 바로가기"는 개발 중 화면 하나만 바로 확인하고 싶을 때 쓰는 디버그용이며,
실제 서비스 UI에는 없을 항목이다.

## 파일 구조

```
ui/
  app.py                    # Streamlit 진입점(라우터)
  nav.py                    # 화면 전환 헬퍼
  theme.py                  # 공통 CSS + 배지/칩/대화로그 렌더 헬퍼
  mock_data.py               # 가짜 레시피 데이터(된장찌개/바지락된장찌개/해물된장찌개/문어초무침)
  streamlit_screens/         # 화면별 render() 모듈 11개
  html/
    01_start.html ~ 11_unclassified.html
    flowmap.html            # 전체 화면 지도(포트폴리오용 인덱스)
    assets/style.css        # 공통 디자인 토큰 + 스타일
```

## 데이터 근거

`ui/mock_data.py`의 된장찌개/바지락된장찌개/해물된장찌개는 `orchestration/mock_client.py`의
시드 데이터와 같은 요리를 재사용했다(문서 5장 시나리오 A/B, 6.4의 "새우+바지락→해물된장찌개"
사례를 그대로 재현하기 위함). 다만 화면에 필요한 재료 분량·소요 시간(분)은 이 프로토타입에서만
쓰는 표시용 정보로 새로 채워넣었다 — `recipes`/`recipe_steps` 실제 스키마(db/schema.sql)에는
없는 필드다.

## 부대찌개 — 실제 TTS 음성이 붙은 데모 레시피 (2026-08-19)

시작 화면 힌트칩 "실제 TTS 음성 데모 — 부대찌개 어떻게 만들어?"로 들어가면, 다른 레시피와
달리 조리 단계마다 **진짜 합성된 wav**가 재생된다(`src/tts/infer.py`로 미리 합성해둔 파일,
실시간 호출 아님 — orchestration.pipeline이 아직 미완성이라 그건 여전히 불가능).

- `ui/mock_data.py`의 `"budaejjigae"` 레시피 각 step에 `"audio": "0N.wav"` 필드가 있고,
  `ui/streamlit_screens/cooking_step.py`가 이 필드를 보고 `ui/assets/audio/budaejjigae/`에서
  파일을 찾아 재생한다. 오디오가 없는 나머지 레시피(된장찌개 등)는 이 위젯 자체가 안 뜬다
  (`current.get("audio")`가 없으면 스킵).
- 재생바 자체는 `theme.render_audio_player()`가 그린다 — 브라우저 기본 `st.audio()`
  컨트롤(탐색바 그대로 노출, 앱 디자인과 안 어울림) 대신, `.ce-player`와 똑같이 생긴
  HTML/CSS/JS를 `st.iframe()`(구 `components.v1.html()`, 1.59.2부터 대체 API)으로 직접
  그리고 클릭하면 JS로 `<audio>`를 재생/정지한다(wav를 base64 data URI로 iframe 안에
  통째로 넣음). iframe이 부모 문서 CSS 변수(`:root`)를 못 물려받아서 `.ce-player`/
  `.ce-play-btn`/`.ce-wave` 색상값을 `render_audio_player()` 안에 다시 하드코딩해뒀다 —
  `theme.py`의 `:root` 색상이 바뀌면 여기도 같이 바꿔야 함.
- **카드 안에 진짜로 nesting됨** — 처음엔 장식용 재생바(카드 안, 정지 파형)는 그대로 두고
  진짜 재생바를 카드 "밖"(아래)에 별도로 얹었었는데, 그러면 재생바가 2개로 겹쳐 보이는
  문제가 있었다(사용자가 실제로 확인). 순수 HTML(`<div class="ce-card">`)로는 `st.iframe()`
  같은 별도 Streamlit 엘리먼트를 카드 안에 못 넣어서(한 st.markdown 호출 안에 넣어야
  하는 제약, 아래 `render_step_card()` 참고), 대신 `st.container(key="cs_step_card")`를
  진짜 카드로 쓰도록 구조를 바꿨다 — 그 컨테이너의 실제 DOM 래퍼
  (`[data-testid="stVerticalBlock"][class*="st-key-cs_step_card"]`)에 `.ce-card` 스타일을
  입히고, 그 컨테이너의 자식으로 제목(markdown)과 재생바(markdown 또는 iframe)를 순서대로
  넣으면 진짜 흰 박스 안에 nesting된다. 오디오 없는 레시피는 여전히 장식용 정지 파형만
  같은 카드 안에 보여준다.
- **파형이 실제 오디오 진폭을 반영함** — 기존엔 모든 문장에 똑같은 고정 막대 높이
  (`_WAVE_HEIGHTS`, 장식용)를 재사용했는데, `theme._compute_wave_bars()`가 wav를
  `soundfile`로 읽어 20개 구간으로 나눠 구간별 RMS 진폭을 막대 높이(4~28px)로 바꾼다 —
  조용한 구간은 낮게, 강세 있는 구간은 높게 나온다(문장마다 모양이 다름, 실측 확인함).
  재생 중엔 `timeupdate` 이벤트로 현재 재생 위치만큼 막대를 진하게(`opacity`) 칠해서
  진행 표시도 겸한다. 막대는 고정폭(3px)이 아니라 `flex:1`로 서로 균등하게 늘어나서
  재생바 끝까지 꽉 채운다(`.ce-wave`/iframe 안 `.wave` 둘 다 적용 — 오디오 없는
  레시피의 장식용 파형도 동일하게 고쳤다, 2026-08-19).
- **"다음"/"이전" 클릭 시 자동 재생** — `<audio autoplay>` + JS `audio.play()`(정책상
  막히면 조용히 무시하고 대기 상태로 남음)로, 이 위젯이 새로 렌더링될 때마다(=다음/이전/
  다시 어떤 경로로 오든) 자동 재생을 시도한다. 브라우저 자동재생 정책은 iframe 단위로도
  걸리기 때문에 100% 보장은 아니고, 이 환경엔 브라우저가 없어 실제로 자동재생이 되는지는
  직접 확인 못 했다 — 눌러보실 때 같이 확인 부탁드립니다.
- 오디오 파일(`ui/assets/audio/`)은 개인 `.git/info/exclude`에 있어 로컬 전용이다 — 다른
  팀원이 pull해서 실행하면 이 레시피만 "⚠️ 음성 파일 없음" 캡션이 뜬다(코드는 안 깨짐,
  `cooking_step.py`가 `Path.exists()`로 방어함). 팀과 공유하려면 파일을 커밋해야 함.
- `streamlit.testing.v1.AppTest`로 전체 흐름(힌트칩 클릭 → 레시피확인 → "응, 시작할게요" →
  7단계 전부 "다음"으로 진행 → 완료 화면) 실행, 매 단계 오디오 위젯 1개씩 정상 렌더링·예외
  없음 확인. 오디오 없는 레시피(된장찌개)도 별도로 회귀 없음 확인.

## 버그: 투명 오버레이 버튼 클릭 영역이 실제 화면보다 훨씬 작았음 (2026-08-19)

시작 화면 마이크 아이콘을 눌러도 아무 반응이 없다는 리포트를 받고, 이 환경에 있던
Playwright(`pip install playwright`, 크로미움 바이너리도 이미 설치돼 있었음)로 실제
`streamlit run ui/app.py`를 띄워 진짜 클릭 좌표를 찍어봐서 원인 2개를 확정하고 고쳤다.

1. **투명 버튼(`.stButton`)이 부모 높이를 못 물려받음** — `ce_big_mic`/`hint_chip`/
   `ce_back_link` 셋 다 "장식용 markdown 위에 투명 `st.button`을 `position:absolute;
   inset:0`로 덮는" 같은 패턴을 쓰는데, `button { height:100% }`가 실제로는 그 button의
   직계 부모인 `div.stButton` 기준으로 계산된다. `div.stButton` 자체엔 height가 없어서
   (기본값 auto) 퍼센트가 안 먹히고, 결과적으로 버튼이 내용물 높이(~40px)로만 렌더링됐다
   — 마이크 아이콘은 카드 전체가 151px인데 클릭 가능한 영역은 위쪽 40px뿐이었다(Playwright로
   실측: `real <button> box: height: 40` vs `outer container box: height: 151.6`). 세
   군데 다 `div.stButton { height: 100%; }`를 추가해서 퍼센트 체인을 이어줬다.
2. **Streamlit 기본 헤더가 투명한 채로 여전히 클릭을 가로챔** — `[data-testid="stHeader"]
   { background: transparent; }`로 안 보이게만 했지 `pointer-events`는 그대로 `auto`라,
   화면 맨 위(y=0~약46px) 영역 클릭은 실제로 그 투명 헤더가 먼저 받아버렸다
   (`document.elementFromPoint(80,40)`로 실측: 헤더가 반환됨). recipe_confirm의
   "처음으로" 링크가 `order:-1`로 맨 위까지 끌어올려져 있어서 정확히 이 사각지대에 걸림.
   헤더 전체를 `pointer-events:none`으로 클릭 통과시키고, 남겨두기로 한 사이드바 열기
   버튼(`[data-testid="stExpandSidebarButton"]`)만 `pointer-events:auto`로 되돌렸다.
3. 두 수정 다 실제 브라우저 클릭(강제 클릭 아닌 `page.mouse.click()`)으로 재검증 완료:
   마이크 아이콘 클릭 → `st.audio_input` 등장, "처음으로" 클릭 → 시작 화면 복귀, 전부 확인.
   `AppTest`만으로는 못 잡는 버그였다 — AppTest는 실제 픽셀 좌표로 클릭하는 게 아니라
   위젯을 프로그램적으로 트리거하기 때문에 이런 "보이는 영역과 실제 클릭 영역이 다른"
   문제는 안 걸린다(이번 세션 전까지 계속 AppTest만 믿고 "정상"이라고 판단했던 게 바로 이
   맹점 때문).
- **미해결로 남긴 것**: 사이드바 열기 버튼 자체가 `[data-testid="stToolbar"] { visibility:
  hidden; }`(기존 규칙)에 걸려 있어서, `pointer-events:auto`를 줘도 `visibility:hidden`인
  조상 때문에 여전히 안 눌린다(실측 확인, `is_visible()` False). 코드 주석은 "화살표는
  남겨둔다"고 돼 있지만 실제로는 처음부터 안 눌렸던 것으로 보임 — 이번 요청 범위 밖이라
  건드리지 않았고, 필요하면 별도로 고쳐야 함.

## 검증 상태

- HTML 11개 + flowmap: 내부 링크 전수 점검(끊긴 링크 없음), 태그 짝 검사 통과.
- Streamlit 11개 화면: `streamlit.testing.v1.AppTest`로 시작→레시피확인→조리진행(다음/다시/이전
  경계값 포함)→재료 1:1 대체→레시피 전체 교체→매칭실패→인식실패 fallback→신규등록 전체 4단계까지
  총 18단계 전이를 헤드리스로 실행, 예외 없음을 확인. 2026-08-19: 이 환경에 `streamlit`
  1.59.2가 실제로 설치돼 있어(이전 기록과 달리 PATH에 있음을 확인) 부대찌개 오디오 플로우도
  같은 방식으로 직접 실행 검증함(위 섹션 참고). **같은 날, Playwright(크로미움)도 이 환경에
  이미 설치돼 있는 걸 확인** — 진짜 브라우저 클릭이 필요한 버그(위 버그 수정 섹션)는 이걸로
  검증했다. AppTest로 안 잡히는 "클릭 영역 vs 시각적 영역 불일치" 같은 버그는 앞으로도
  Playwright로 확인하는 게 안전함.
- 알려진 제약: 완료 화면 → 처음으로 전이에서 `AppTest` 자체의 위젯 트리 누적 방식 때문에
  테스트 하네스 수준의 `KeyError`가 발생한다(실제 브라우저 세션에선 재현 안 될 것으로 보임,
  다만 아직 이 마지막 한 단계만은 Playwright로 직접 확인 안 함).
