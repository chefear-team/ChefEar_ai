# Spec: TTS 음성 생성 중 전체 화면 오버레이 로딩 (블러 배경 + 냄비 마스코트)

> **❌ 2026-08-23 철회(Withdrawn)**: 이 Spec은 끝내 구현되지 않았다. 같은 날 오전에
> GIF(`ui/assets/images/tts_loading.gif`)를 SVG+CSS 냄비 마스코트로 교체했지만
> (아래 갱신 이력), 오후에 사용자가 실사용해보니 그 로딩 표시조차 "의미없다 - 렉만
> 더 걸리는 느낌"이라고 판단해서 로딩 인디케이터 자체를 완전히 없앴다
> (`src/ui/voice_io.py::speak()` — 0.2초 폴링 루프를 걷어내고 그냥 블로킹으로 조용히
> 기다리는 방식으로 되돌림, `render_tts_loading()`/`_TTS_LOADING_MASCOT_SVG`도
> `ui/theme.py`에서 삭제). 그래서 이 문서가 다루는 "전체 화면 블러 오버레이" 자체가
> 전제(보여줄 로딩 인디케이터가 있다)를 잃었다 — 로딩 UI를 다시 만들고 싶어지면
> 이 문서를 새로 쓰는 게 낫다(아래 내용은 참고용으로만 남겨둠).
>
> <details><summary>철회 전 갱신 이력(2026-08-23 오전)</summary>
>
> 팀이 준비했던 GIF를 걷어내고 `render_tts_loading()`을 SVG+CSS 냄비 마스코트로
> 교체했었다 — 아래 "GIF 제작 프롬프트"·GIF 관련 폴백(EC-05/AC-04)은 그래서 더 이상
> 유효하지 않다는 갱신이었다. 지금은 그 마스코트 자체도 없다(위 철회 사유 참고).
> </details>

## Why

- **페르소나**: 요리 중이라 화면을 계속 쳐다보기 어렵고, 손이 자유롭지 않아 음성 위주로 ChefEar를 쓰는 사용자
- **상황**: 사용자가 발화하면 응답 음성(TTS)을 합성하는 3~20초 동안(`docs/decisions.md` #2 실측) 앱이 뭔가 하고 있다는 걸 명확히 보여줘야 한다
- **문제**:
  1. 현재(2026-08-23) 구현은 로딩 표시(냄비 마스코트+진행률 텍스트)가 화면 흐름 중간에, 호출된 위치 그대로 삽입되는 형태라 화면마다 위치가 들쭉날쭉하고 눈에 잘 안 띔
  2. 로딩 중에도 뒤 화면 요소(재료 칩, 채팅 로그 등)가 그대로 다 보여서 "지금은 조작하면 안 되는 상태"라는 게 시각적으로 구분이 안 됨
- **측정 지표**: 정량 지표 없음(주관적 UX 개선) — 완료 기준은 AC 통과 여부로 판단

## Goal

- **해결 목표**: TTS 합성이 진행되는 동안 화면 전체가 반투명 블러 처리되고, 그 위에 중앙 정렬된 냄비 마스코트 애니메이션 + 진행률이 오버레이로 뜬다. 합성이 끝나면 블러가 즉시 사라지고 원래 화면이 다시 정상적으로 보인다.
- **성공 기준**:
  - 합성 시작 시점에 화면 전체(뷰포트 기준)가 블러 처리됨과 동시에 오버레이가 나타난다(지연 없이)
  - 오버레이가 떠 있는 동안 뒤 콘텐츠는 흐리게만 보이고 클릭/조작은 안 먹혀야 한다(블러 자체가 시각적 차단 역할, 실제 상호작용 차단은 Streamlit 특성상 별도 처리 불필요 — 아래 How 참고)
  - 합성 완료 후 300ms 이내에 블러/오버레이가 사라진다
- **Out of Scope**:
  - **실시간 취소 버튼** — Streamlit은 파이썬 스크립트 하나가 끝나야 다음 상호작용(버튼 클릭 등)을 처리할 수 있는 구조라, 지금처럼 진행률 갱신을 위해 블로킹 루프를 쓰는 한 버튼 클릭을 못 받는다. 이걸 되게 하려면 `st.fragment`로 `speak()` 호출 패턴 자체(수십 곳의 "합성 → 화면 전환" 흐름)를 다시 짜야 해서 별도 Spec으로 분리한다(`docs/specs/tts_cancel_button.md`, 아직 없음 — 필요해지면 새로 작성)
  - **진짜 토큰 단위 진행률** — `qwen_tts` 라이브러리가 진행률 콜백을 지원하지 않아(2026-08-22 실측 확인, `Qwen3TTSModel.generate_voice_clone()`의 내부 `talker_kwargs`가 고정 화이트리스트라 `streamer` 인자를 안 받음) 여전히 경과시간/예상시간 기반 추정치를 쓴다
  - 마스코트 애니메이션 자체의 내용(캐릭터 디자인, 색감 등) — 이미 `ui/theme.py`의 `_TTS_LOADING_MASCOT_SVG`/`render_tts_loading()`으로 확정돼 있어 이 Spec 범위 밖

## What

**Happy Path**

1. 사용자가 발화 → 의도 처리 → 응답 문구가 정해짐 → `speak()` 호출
2. 캐싱된 오디오가 없으면(최초 합성) → 화면 전체 블러 + 중앙 오버레이(냄비 마스코트 + 진행률 바) 표시
3. 합성이 진행되며 진행률 바가 0%→95%까지 올라감(경과/예상 시간 기반 추정)
4. 백그라운드 합성 완료 → 오버레이/블러 즉시 제거 → 오디오 재생(또는 다음 화면으로 전환)

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 이미 캐싱된 오디오(재방문 등) | 오버레이 자체를 안 띄움 — 합성 자체가 필요 없으므로 |
| EC-02 | 합성 중 예외 발생(GPU 메모리 부족 등) | 오버레이 제거 + 기존처럼 `st.warning()`으로 텍스트 안내(EC-05 원칙 유지, 화면 텍스트는 항상 남음) |
| EC-03 | `hidden=True` 호출(어차피 바로 `goto()`로 화면 전환되는 경우) | 오버레이가 잠깐 떴다가 전환되는 게 정상 — 오히려 "지금 다음 걸 준비 중"이라는 느낌을 더 잘 줌 |
| EC-04 | `show_loading=False` 호출(2026-08-22 추가, 레시피 조회 확인 메시지 등) | 오버레이 자체를 안 띄움(현재 로직 유지) |

## How

### 1. 로딩 인디케이터: 기존 `render_tts_loading()` 그대로 재사용

GIF를 새로 만들 필요가 없다 — `ui/theme.py`의 `_TTS_LOADING_MASCOT_SVG`가 이미
GIF 제작 프롬프트가 요구했던 조건(투명 배경, 진행률 미포함, 오렌지 몸통 #ee7b36 +
노란 뚜껑 브랜드 냄비 캐릭터, bounce + 김 애니메이션, 1.5~2초 주기 반복)을 SVG+CSS로
충족한다. 파일 배포가 없어서 용량 제약도 해당 없음. 이 오버레이 Spec을 구현할 때는
`render_tts_loading(f"음성 만드는 중... {percent}%")`를 아래 오버레이 컨테이너 안에서
그대로 호출하면 된다(별도 GIF 경로 참조 불필요).

### 2. 오버레이 + 블러 CSS 설계

기존 프로젝트가 `st.container(key=...)`에 CSS 클래스를 거는 패턴을 이미 씀
(`ui/theme.py`의 `[class*="st-key-cs_mic_bar"]`, `[class*="st-key-my_recipes_list"]` 등과 동일 방식):

```css
[class*="st-key-tts_loading_overlay"] {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  background: rgba(247, 241, 230, 0.55);   /* --bg 톤 반투명 틴트 */
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}
```

Streamlit 쪽 사용:

```python
with st.container(key="tts_loading_overlay"):
    render_tts_loading(f"음성 만드는 중... {percent}%")
```

`position: fixed; inset: 0`이 뷰포트 전체를 덮으므로, 이 컨테이너보다 DOM상
뒤에 그려진 모든 콘텐츠(재료 칩, 채팅 로그 등)가 `backdrop-filter: blur()`로
흐리게 보인다 — 별도 JS 없이 순수 CSS로 끝남.

### 3. 취소 버튼이 "필요 없는" 이번 범위에서는 기존 블로킹 루프 그대로 재사용 가능

이번 Spec은 취소 버튼이 Out of Scope라, `src/ui/voice_io.py::speak()`의 기존
`while not job["done"]: ... time.sleep(0.2)` 폴링 구조를 그대로 두고, 매
반복마다 다시 그리는 대상만 `render_tts_loading()`(인라인) → 위 오버레이
컨테이너로 바꾸면 된다. 새 스레딩/락 설계가 필요 없음 — 순수 렌더링 위치/CSS
변경.

## AC (Given-When-Then)

**AC-01 · 합성 시작 시 오버레이 표시**
- GIVEN: 캐싱 안 된 메시지로 `speak(message, show_loading=True)` 호출됨
- WHEN: 합성이 시작됨(백그라운드 스레드 시작 직후)
- THEN: 화면 전체가 블러 처리되고 중앙에 냄비 마스코트 + 진행률 바가 뜬다

**AC-02 · 합성 완료 시 오버레이 제거**
- GIVEN: 오버레이가 떠 있는 상태
- WHEN: 백그라운드 합성이 완료됨(`job["done"] == True`)
- THEN: 블러/오버레이가 즉시 사라지고 원래 화면(재료 칩 등)이 다시 선명하게 보인다

**AC-03 · show_loading=False면 오버레이 자체가 안 뜸**
- GIVEN: `speak(message, show_loading=False)` 호출(예: 레시피 조회 확인 메시지)
- WHEN: 합성이 진행 중
- THEN: 오버레이/블러가 전혀 나타나지 않는다(기존 동작 유지)

