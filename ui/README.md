# ui/ — 공용 스타일과 VAD 세그먼터

저장소 루트의 `ui/`는 실서비스(`src/app.py`)가 `sys.path`에 얹어 직접 import하는 두 모듈과 이미지 자산을 담는다. `src/ui/`(화면 컴포넌트)와는 이름만 같고 다른 경로다.

| 파일 | 역할 |
|---|---|
| `theme.py` | CSS 주입(`inject_css`), 브랜드 로고·배경, 배지·카드·재료 칩·대화 로그·마이크 상태 표시, 로딩 오버레이, 오디오 자동 재생 컴포넌트, 화면 전환 잔상 청소(`render_screen_cleanup`), 접근 차단 화면 |
| `mic_vad.py` | `MicVadSegmenter` — silero-vad로 WebRTC 오디오 프레임을 "발화 시작 ~ 600ms 무음" 단위로 잘라 STT에 넘긴다 |
| `images/` | 로고·배경 이미지 |

초기 화면 프로토타입(HTML 목업, 버튼 기반 Streamlit 화면, mock 데이터)은 실서비스와 무관해져 2026-09-10 정리 때 삭제했다. 필요하면 git 이력(2026-08-13 ~ 08-28)에서 볼 수 있다.

`theme.py`의 오디오 자동 재생은 `st.html`로 `<audio autoplay>`를 주입하는데, 같은 내용이면 Streamlit이 재실행하지 않으므로 파일 경로에 매번 다른 프래그먼트를 붙여 강제로 다시 그린다.
