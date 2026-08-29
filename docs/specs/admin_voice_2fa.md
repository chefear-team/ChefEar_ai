# Spec: 관리자 페이지 2FA — `.env` 토큰(1차) + ECAPA-TDNN 화자검증(2차, 랜덤 챌린지)

> **부모 스펙**: `docs/specs/admin_recipe_approval.md` (Phase 1 — 승인/삭제 워크플로우 + `.env` 토큰 게이트). 이 스펙은 그 문서 138~144줄 "Phase 2 설계 메모"를 실제 구현 범위로 확정한 것이다. Phase 1의 승인/삭제 화면(`src/ui/screens/admin.py::render_admin()`)·조회 분기는 그대로 두고, **접근 게이트만** 토큰 단독 → 토큰+음성 2FA로 바꾼다.
>
> **결정 배경 (2026-08-28 대화)**: 음성 인증 단독은 녹음 재생 공격에 약하고, 서버가 Cloudflare Tunnel로 공개돼 있어 인증 화면 자체가 전 세계 노출되면 GPU DoS 여지가 있다. 그래서 `?admin_key=` 토큰을 1차 관문으로 유지(화면 노출 자체를 막음) + 음성을 2차로 추가하는 2FA로 확정. 재생 공격은 매 시도 랜덤 챌린지 숫자를 읽게 해서 막는다.

## Why

- **페르소나**: 프로젝트 운영자 2~4명 (레시피 승인/삭제 권한을 가진 사람들)
- **상황**:
  - Phase 1은 `.env`의 `ADMIN_ACCESS_TOKEN` 하나를 운영자 전원이 공유한다 (`?admin_key=<값>` URL 북마크).
  - 로컬 streamlit(WSL :8501)이 Cloudflare Tunnel로 `chefear.store`에 붙어 전 세계에 공개돼 있다. `/admin`도 공개 경로다.
- **문제**:
  1. URL에 들어간 토큰은 브라우저 히스토리·서버/Cloudflare 로그·referrer 헤더·북마크 공유·어깨너머로 유출되기 쉽다. 한 번 새면 수동으로 `.env`를 바꾸고 전원에게 재공유하기 전까지 계속 뚫린다.
  2. 공유 토큰이라 **누가** 승인/삭제했는지 추적이 안 된다.
  3. 운영자 한 명만 접근 차단(예: 퇴사)하는 게 불가능하다 — 토큰을 바꾸면 전원이 영향받는다.
- **측정 지표**: 정량 지표 없음 — 아래 AC 통과로 판단 (Phase 1과 동일한 태도).

## Goal

- **해결 목표**: 토큰(1차) + 화자검증(2차) 2FA. 토큰이 유출돼도 등록된 운영자 목소리 없이는 진입 불가. 진입한 운영자의 이름을 세션·로그에 남긴다. 운영자 추가/제거는 성문(voiceprint) 행 추가/삭제로 처리한다.
- **성공 기준 (숫자)**:
  - 등록된 운영자 본인이 조용한 환경에서 챌린지를 읽으면 통과율 **≥ 95%** (한 접속당 재시도 2회 이내).
  - 수집한 임포스터 샘플(미등록 화자가 챌린지를 정확히 읽은 녹음) 기준 통과율(FAR) **0%**.
  - 사전 녹음 재생 공격(등록 운영자 목소리 + 과거 챌린지 녹음) 통과율 **0%**.
  - STT가 챌린지 숫자를 하나라도 틀리게 인식하면 통과 안 됨 (숫자 **완전 일치** 필수).
  - 녹음 제출 후 판정까지 걸리는 시간: GPU warm 기준 **p50 ≤ 3초, p95 ≤ 6초**.
- **Out of Scope**:
  - Cloudflare Access / Google OAuth 기반 관리자 인증 — 별도 논의(부모 스펙 Out of Scope와 동일).
  - 운영자별 권한 차등 — 전원 동일(승인/삭제 다 가능).
  - 음성 합성(TTS)·딥페이크 실시간 공격 탐지 — 랜덤 챌린지는 "미리 녹음한 것 재생"만 막는다. 화면 숫자를 실시간으로 보고 즉석에서 등록 운영자 목소리를 합성/변조해 읽는 공격은 이 스펙 범위 밖(안티스푸핑 모델은 별도).
  - 관리자 세션 만료 / 자동 로그아웃 정책 — 탭 닫으면 끝(`st.session_state` 소멸), 그 이상은 별도 스펙.
  - enrollment 셀프서비스(이미 인증된 운영자가 관리자 화면에서 새 운영자 등록) — v1은 `?enroll_key=` 전용. 나중에 추가 가능한 구조로만 둠.
  - 성문 회전 주기 강제 / 재등록 알림.

## What

> **주의 (2026-08-28, 소스 기준 갱신)**: 아래 Happy Path·Edge Case·AC의 "랜덤 6자리 숫자" 예시는 최초 설계 시점 기준이다. 실제 구현은 아래 "구현하며 확정된 것" #1에 따라 **랜덤 한글 단어 3개**(STT 결과에 3개 중 2개 이상 부분일치하면 통과)로 바뀌었다 — 판정 로직(일치 확인 → 화자 검증 순서, 실패 처리, IP 잠금)은 예시의 숫자를 한글 단어로 바꿔 읽으면 동일하다. `tests/test_speaker_verify.py`가 실제 구현 기준 테스트다.

### Happy Path — 운영자 접근 (2FA)

1. 운영자가 `https://chefear.store/admin?admin_key=<ADMIN_ACCESS_TOKEN 값>`으로 접속한다.
2. 토큰이 일치하면 관리자 Page로 진입하되, **아직 승인/삭제 목록은 안 보인다.** 대신 **음성 챌린지 화면**이 뜬다:
   - 매 시도 새로 생성된 랜덤 6자리 숫자(예: `374915`)를 크게 표시
   - "이 숫자를 또박또박 읽어주세요" 안내
   - `st.audio_input()` 녹음 위젯
3. 운영자가 숫자를 읽어 녹음 → 제출.
4. 서버 판정 (`_GPU_LOCK` 하에 직렬화):
   - **(a) 챌린지 일치**: `stt_transcribe(wav)` → 숫자만 추출 → 화면 챌린지와 문자 그대로 완전 일치 확인.
   - **(b) 화자 일치**: `speaker_verify.embed(wav)` → `admin_voiceprints`의 모든 등록 임베딩과 코사인 유사도 → 최댓값 ≥ `ADMIN_VOICE_THRESHOLD` 확인.
   - (a)·(b) 둘 다 통과 → `st.session_state["_admin_verified"] = <매칭된 이름>` 세팅 후 `st.rerun()`.
5. 재실행 시 세션 플래그가 있으므로 Phase 1의 승인 대기 목록(`render_admin()`)이 그대로 렌더된다. 상단에 `관리자: {이름}` 표시.
6. "등록"(승인)/"삭제" 클릭 시 서버 콘솔 로그에 `[admin] {이름}: approve <recipe_id>` / `delete <recipe_id>` 를 남긴다.

### Happy Path — 운영자 등록 (enrollment)

1. 프로젝트 오너가 `https://chefear.store/enroll?enroll_key=<ADMIN_ENROLL_TOKEN 값>`으로 접속한다(별도 시크릿, 별도 `url_path`).
2. 이름 텍스트 입력 + `st.audio_input()`로 짧은 발화 **3회** 녹음(아무 문장, 각 3~5초 권장 — 화면에 안내).
3. "등록" 클릭 → 각 샘플의 임베딩을 추출·평균·L2정규화 → `admin_voiceprints`에 `{name, embedding, sample_count}` UPSERT(같은 이름이면 덮어씀 = 재등록).
4. "등록됨: {이름}" 확인 표시.

### Edge Cases

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | `?admin_key=` 없음/틀림 | 관리자 `st.Page`를 `st.navigation`에 아예 안 넣는다 → `/admin` 가도 메인 화면만. 조용히 무시(부모 스펙 EC-01과 동일 — 게이트 존재 신호 안 줌). |
| EC-02 | 토큰 맞음 + 음성 검증 실패 (임포스터 / 잡음 / 마이크 불량 / 챌린지 오독) | "인증에 실패했어요. 다시 시도해 주세요." + **새 챌린지 숫자 재생성**. 실패 사유(숫자 불일치 vs 화자 불일치)는 화면에 노출 안 함(공격자에게 힌트 금지) — 콘솔엔 실제 사유 로그. |
| EC-03 | STT가 숫자를 못 알아듣거나 자릿수가 안 맞음 | EC-02와 동일 처리(사용자 입장에선 구분 불필요). |
| EC-04 | `admin_voiceprints` 비어있음 (아직 아무도 등록 안 함) | 비교 대상이 없으므로 화자 검증은 **항상 실패** → 아무도 못 들어간다. enrollment를 먼저 해야 한다(fail-closed). |
| EC-05 | `.env` `ADMIN_ACCESS_TOKEN` 비어있음 | 부모 스펙 EC-02와 동일 — `_admin_gate_ok()`가 `False` → 관리자 페이지 완전 차단(fail-closed). |
| EC-06 | `.env` `ADMIN_ENROLL_TOKEN` 비어있음 | enrollment Page를 `st.navigation`에 안 넣는다 → `/enroll` 차단(fail-closed). 오너가 값을 설정해야 등록 가능. |
| EC-07 | 재생 공격 — 등록 운영자가 과거에 `111222`를 읽는 걸 녹음해두고, 현재 챌린지 `999888`에 그 녹음을 제출 | STT 결과 `111222` ≠ `999888` → (a) 불일치 → 진입 실패. (매 시도 챌린지가 바뀌고, 쓰인 챌린지는 즉시 폐기.) |
| EC-08 | 음성 검증 5회 연속(60초 창) 실패 | 그 **IP**를 60초 잠금. 그동안 챌린지 화면 대신 "약 N초 후 다시" 안내. 카운터/잠금은 `admin_auth.py` 모듈 메모리에 **IP 기준**으로 둔다(세션 기반은 새로고침 한 번으로 리셋돼 무의미 — 2026-08-28 지적). IP는 최근 60초 안에 실패가 있거나 잠금 중일 때만 보유하고, 지나면 항목 삭제(개인정보 최소 보유). 인증 성공 시에도 즉시 삭제. IP는 Cloudflare `CF-Connecting-IP` 헤더. |
| EC-09 | GPU 경합 (다른 사용자의 STT/TTS/로컬LLM 동시 실행) | `_GPU_LOCK` 공유로 직렬화. 검증이 몇 초 걸려도 관리자 페이지는 **상시 마이크(webrtc)를 안 쓰므로** Queue overflow 등 부작용 없음(부모 스펙 EC-06). |
| EC-10 | 세션 중 브라우저 새로고침 | `st.session_state` 소멸 → 다시 챌린지 화면부터. (탭을 유지하면 세션 살아있어 재인증 불필요.) |
| EC-11 | speechbrain 모델 로드/다운로드 실패 (네트워크, 디스크, GPU OOM) | 검증을 실패로 처리(fail-closed) + 콘솔 에러 로그. 관리자 페이지 진입 불가(EC-05와 같은 정신 — 인증 인프라가 죽으면 열지 않는다). |

## 확정됨

- **게이트 구조**: 토큰(1차, 화면 노출 자체를 막음) + 화자검증(2차). 둘 다 통과해야 진입. 토큰 단독 진입 불가, 음성 단독 진입 불가.
- **재생 공격 방어**: 매 시도 랜덤 6자리 숫자 챌린지를 읽게 하고, STT로 자릿수·값 완전 일치를 확인한다. 쓰인 챌린지는 즉시 폐기(재사용 불가).
- **화자 모델**: `speechbrain/spkrec-ecapa-voxceleb` (ECAPA-TDNN, 192-dim). 로컬 GPU 로드, `_GPU_LOCK` 공유. 부모 스펙 Phase 2 메모대로.
- **다중 운영자**: 토큰은 공유(전원 같은 URL), 신원은 성문으로 구분. 검증은 등록된 전 임베딩과 코사인 최댓값 vs threshold(`intent_classifier.py`의 `best_per_intent`와 같은 구조).
- **검증 실패 시 반응**: 조용히 "다시 시도" + 새 챌린지. 실패 사유 비공개(부모 스펙 "화자검증 실패 시 조용히 무시" 정신 유지, 단 재시도는 허용).
- **enrollment 방식**: `?enroll_key=<ADMIN_ENROLL_TOKEN>` 별도 화면, 이름 + `st.audio_input()` 3회. 같은 이름 UPSERT = 재등록.

## 구현하며 확정된 것 (2026-08-28)

1. **챌린지 형식 → 랜덤 한글 단어 3개.** 배포 STT가 고립된 숫자를 잘 못 잡는 게 실측 확인돼(사용자 테스트: "일,이,3,4,오,6,7,팔,구" 뒤섞임) 숫자 폐기. `ui/screens/admin_auth.py`의 큐레이션 명사 풀(~40개, 2~3음절)에서 3개를 뽑아 표시, STT 결과에 **3개 중 2개 이상**이 부분문자열로 들어있으면 통과(STT 1개 실수 허용). 조합 40*39*38 ≈ 5.9만.
2. **`_GPU_LOCK` — 이동 불필요.** ECAPA를 **CPU에서** 돌리기로 해서(팀 GPU VRAM 여유 ~1GB뿐) `speaker_verify`는 GPU 락이 필요 없다. 챌린지 STT만 GPU를 쓰고, 그건 `ui/screens/admin_auth.py`(ui 계층)가 `from ui.voice_io import _GPU_LOCK`으로 정상적으로 가져다 쓴다 — 리팩터링 없음.
3. **감사 로그 → 콘솔 `print`.** `[admin] {이름}: ...`. audit 테이블은 필요해지면 추가.
4. **모델 배포 → `models/spkrec-ecapa-voxceleb/` 로컬 폴더.** `.gitignore`에 걸려 있어(다른 대용량 모델과 동일) 커밋 안 함 — 배포 환경마다 그 폴더에 파일 5개(`hyperparams.yaml`, `embedding_model.ckpt` ~83MB, `mean_var_norm_emb.ckpt`, `classifier.ckpt`, `label_encoder.txt`)를 두거나, 폴더가 비면 `load_speaker_model()`이 HF에서 받아 그 폴더에 캐싱한다. `ADMIN_SPEAKER_DIR`로 위치 변경 가능. 첫 로드 ~30초 → `admin_auth._warm_models_once()`가 챌린지 화면 진입 시 백그라운드로 STT·화자모델을 미리 로드한다(사용자가 녹음하는 동안 준비 완료).
5. **등록 샘플 → 3회** (`admin_enroll._N_SAMPLES`). 통과율 낮으면 5로.
6. **threshold → `ADMIN_VOICE_THRESHOLD` 기본 0.55.** 관리자 실등록 후 임포스터 샘플로 EER 재측정해 조정 필요(스모크: 동일화자 held-out 코사인 0.55~0.74, 짧은 클립일수록 편차 큼).
7. **성문 저장 → `data/admin_voiceprints.json` 단일 파일** (`{이름: {embedding, sample_count, updated_at}}`). 스펙 How #1의 Supabase 테이블 대신 파일 채택 — 저장소 폴더가 네트워크 공유라 파일도 기기 간 공유되고, Supabase DDL을 사람이 대시보드에서 실행하는 단계를 없앤다. `.gitignore`로 커밋 차단(생체정보). `verify`/`enroll` 인터페이스는 그대로라 나중에 Supabase로 교체 가능.
8. **모델 로더 — speechbrain 1.0.2 + torchaudio 심.** 배포 venv가 torchaudio 2.11이라 speechbrain이 import 시점에 부르는 `torchaudio.list_audio_backends()`(2.9+ 제거됨)가 없어서, `speaker_verify.load_speaker_model()`이 speechbrain import 전에 그 함수를 심는다(soundfile 백엔드만 쓰므로 무해).

## How

### 1. DB — `db/schema.sql` 추가

```sql
-- admin_voiceprints (docs/specs/admin_voice_2fa.md): 관리자 페이지 2FA의 화자검증용 성문.
-- name        : 운영자 식별용 이름(승인/삭제 로그·화면 상단 표시에 사용). unique.
-- embedding   : ECAPA-TDNN(speechbrain/spkrec-ecapa-voxceleb) 192-dim L2정규화 임베딩.
--               등록 샘플 3~5개의 평균을 float 배열(JSON)로 저장. pgvector 안 씀
--               (운영자 수가 적어 파이썬에서 코사인 계산 — intent_classifier.py 패턴).
-- 같은 name 재등록 시 UPSERT(행이 안 늘어남).
create table if not exists admin_voiceprints (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    embedding jsonb not null,
    sample_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
```

### 2. 새 모듈 — `src/orchestration/speaker_verify.py`

```python
_MODEL_ID = "speechbrain/spkrec-ecapa-voxceleb"
_LOAD_LOCK = threading.Lock()          # stt/infer.py·llm/infer.py의 이중확인 잠금과 동일 패턴
_THRESHOLD = float(os.environ.get("ADMIN_VOICE_THRESHOLD", "0.55"))

def load_speaker_model():
    """세션당 1회 ECAPA-TDNN 로드(_LOAD_LOCK 이중확인). GPU 이동은 여기서, _GPU_LOCK은 호출부."""

def embed(audio, sample_rate=None) -> "np.ndarray":
    """파일 경로 또는 numpy 파형 → 16kHz 모노로 정렬 후 192-dim L2정규화 임베딩.
    GPU 추론이므로 호출부가 _GPU_LOCK으로 감싼다(speak()/stt_transcribe()와 같은 규칙)."""

def verify(audio, *, client=None) -> tuple[bool, "str | None", float]:
    """embed 후 admin_voiceprints 전 행과 코사인 유사도.
    반환 (max_sim >= _THRESHOLD, 매칭된 name 또는 None, max_sim).
    등록 행이 하나도 없으면 (False, None, 0.0) — EC-04(fail-closed)."""

def enroll(name: str, audios: list, *, client=None) -> None:
    """각 audio의 embed 결과를 평균·L2정규화 → admin_voiceprints UPSERT(name 기준,
    embedding=평균, sample_count=len(audios), updated_at=now())."""
```

- 모델 로드·추론 실패는 예외를 그대로 올린다 → 호출부(`render_admin()`)가 잡아 "검증 실패"로 처리(EC-11).
- `_GPU_LOCK`은 미정 #2 정리 후 `orchestration` 계층 공용 객체를 import.

### 3. 챌린지 생성·검증 — `src/ui/screens/admin_auth.py` (신규, `admin.py`에서 분리)

```python
import secrets, re

_MAX_ATTEMPTS = 5
_COOLDOWN_S = 60

def _new_challenge() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(6))

def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)

def render_voice_challenge() -> None:
    """미검증 상태에서 부르는 화면. 통과하면 st.session_state['_admin_verified']=name 세팅 후 st.rerun().
       - st.session_state 로 관리: _admin_challenge(현재 숫자), _admin_attempts, _admin_cooldown_until
       - 쿨다운 중이면 안내만
       - st.audio_input() 제출 시:
           wav 저장 -> with _GPU_LOCK:
               t = stt_transcribe(wav)
               if _digits(t) != challenge:            # (a)
                   fail(); return
               ok, name, score = speaker_verify.verify(wav)   # (b)
               if not ok: fail(); return
           st.session_state['_admin_verified'] = name; st.rerun()
       - fail(): attempts += 1, challenge 재생성, attempts>=_MAX_ATTEMPTS면 cooldown 설정,
                 콘솔에 실제 사유 로그, 화면엔 일반 문구만
```

### 4. 게이트 배선 — `src/app.py`

`_admin_gate_ok()`(1차 토큰)는 **그대로**. 2차는 화면 안에서:

```python
def _run_admin_page() -> None:
    from ui.screens.admin import render_admin
    from ui.screens.admin_auth import render_voice_challenge
    inject_css()
    if not st.session_state.get("_admin_verified"):
        render_voice_challenge()
        return
    render_admin()          # 기존 Phase 1 화면 그대로 (상단에 관리자 이름만 추가)
```

enrollment Page 추가(`if __name__ == "__main__"` 블록, admin Page 옆):

```python
def _enroll_gate_ok() -> bool:
    expected = os.environ.get("ADMIN_ENROLL_TOKEN", "").strip()
    if not expected:
        return False
    return st.query_params.get("enroll_key") == expected

...
if _enroll_gate_ok():
    _pages.append(st.Page(lambda: _run_with_error_notice("enroll", _run_enroll_page),
                          title="관리자 등록", url_path="enroll"))
```

### 5. enrollment 화면 — `src/ui/screens/admin_enroll.py` (신규)

- `st.text_input("이름")` + `st.audio_input()` 3개(또는 "녹음 추가" 반복) + "등록" 버튼.
- "등록" → `with _GPU_LOCK: speaker_verify.enroll(name, wavs)` → 성공 표시.
- 이름 미입력/샘플 3개 미만이면 버튼 비활성.

### 6. 의존성 — `requirements-main.txt`

```
speechbrain==<확정 버전>      # torch/torchaudio(2.5.1)는 이미 있음. ECAPA-TDNN 화자검증용.
```
- `requirements.txt`(HF Spaces 배포용 최소)에는 **안 넣는다** — 관리자 2FA는 팀 GPU 데스크탑 배포에만 필요하고, HF Spaces엔 관리자 페이지를 노출하지 않는다.
- speechbrain 최초 import 시 HF에서 체크포인트 다운로드(미정 #4).

### 7. `.env.example` 추가

```
# ── 관리자 페이지 2FA (docs/specs/admin_voice_2fa.md) ──────────────────────
# ADMIN_ACCESS_TOKEN 은 1차 관문(그대로). 아래는 2차(화자검증).
# ADMIN_ENROLL_TOKEN=            # 운영자 목소리 최초 등록 화면(?enroll_key=) 접근 토큰.
#                               #   비우면 등록 화면 자체가 안 열린다(fail-closed).
# ADMIN_VOICE_THRESHOLD=0.55     # ECAPA-TDNN 코사인 유사도 통과 기준. 운영자 등록 후
#                               #   임포스터 샘플로 EER 재측정해 조정할 것.
#                               #   높일수록 오수락↓ 오거부↑(관리자 보안이라 보수적으로).
```

### 8. 테스트 — `tests/test_speaker_verify.py`

- `verify()`가 `admin_voiceprints` 빈 상태에서 `(False, None, 0.0)` (EC-04).
- 같은 화자 두 샘플의 코사인 > 다른 화자 (골든 wav: `tests/test-audio/` 재사용 또는 소량 추가).
- `enroll()`이 같은 이름 두 번 호출 시 행이 안 늘고 embedding만 갱신 (fake supabase).
- `_digits()` 정규화: `"삼칠사구일오 입니다"` 류 STT 출력에서 숫자만 추출 / 자릿수 불일치 검출 (STT는 목킹).
- `_admin_gate_ok()` 토큰 일치/불일치 (기존).
- 2FA 흐름: `_admin_verified` 없으면 챌린지 화면 함수가 불리고, 있으면 `render_admin()`이 불린다 (얕은 목킹).

## AC (Given-When-Then)

**AC-01 · 토큰만으로는 목록이 안 보인다**
- GIVEN: 올바른 `?admin_key=`, `st.session_state["_admin_verified"]` 없음
- WHEN: `/admin` 접속
- THEN: 승인 대기 목록이 안 보이고, 랜덤 6자리 숫자 + `st.audio_input()` 챌린지 화면이 뜬다

**AC-02 · 등록 운영자 + 정확한 챌린지 → 통과**
- GIVEN: `admin_voiceprints`에 "김철수" 등록됨, 화면 챌린지 `374915`
- WHEN: 김철수가 조용한 환경에서 "374915"를 읽어 녹음 제출
- THEN: STT 숫자 일치 && 화자 유사도 ≥ threshold → 승인 대기 목록이 렌더되고 상단에 "관리자: 김철수" 표시

**AC-03 · 임포스터 차단**
- GIVEN: 올바른 토큰, 화면 챌린지 `482013`, "박영희"는 미등록
- WHEN: 박영희가 "482013"을 정확히 읽어 제출
- THEN: 화자 유사도 < threshold → 진입 실패, 새 챌린지 재생성, 화면에 실패 사유 안 나옴

**AC-04 · 재생 공격 차단 (과거 녹음)**
- GIVEN: 공격자가 과거에 김철수가 `111222` 읽는 걸 녹음. 현재 화면 챌린지 `999888`
- WHEN: 그 과거 녹음을 제출
- THEN: STT `111222` ≠ `999888` → 진입 실패

**AC-05 · 숫자 오인식도 차단**
- GIVEN: 등록 운영자 김철수, 챌린지 `600100`
- WHEN: 김철수가 읽었지만 STT가 `601100`으로 인식
- THEN: 숫자 불일치 → 진입 실패 (화자는 맞아도 통과 못 함)

**AC-06 · 성문 미등록 시 완전 차단**
- GIVEN: `admin_voiceprints` 비어있음, 올바른 토큰
- WHEN: 누가 챌린지를 정확히 읽어 제출
- THEN: 비교 대상 없음 → 항상 실패, 아무도 못 들어간다

**AC-07 · 토큰 미설정 시 완전 차단 (1차)**
- GIVEN: `.env` `ADMIN_ACCESS_TOKEN` 비어있음
- WHEN: 아무 `?admin_key=` 값으로 `/admin` 접근
- THEN: 관리자 Page 자체가 없어 메인 화면만 보인다 (챌린지 화면도 안 뜸)

**AC-08 · enrollment 정상 등록**
- GIVEN: 올바른 `?enroll_key=`
- WHEN: 이름 "김철수" + 음성 3개 녹음 제출
- THEN: `admin_voiceprints`에 name="김철수" 행 1개(embedding 192개, sample_count=3). 같은 이름으로 다시 등록하면 행이 안 늘고 embedding·updated_at만 갱신

**AC-09 · enroll 토큰 없으면 등록 불가**
- GIVEN: `.env` `ADMIN_ENROLL_TOKEN` 설정됨
- WHEN: `?enroll_key=` 없이/틀리게 `/enroll` 접근
- THEN: enrollment 화면이 안 보인다

**AC-10 · 시도 횟수 제한 (IP 기준, 새로고침으로 우회 불가)**
- GIVEN: 한 IP에서 음성 검증 5회 연속 실패
- WHEN: 같은 IP에서 다시 시도 (새 세션/새로고침 포함)
- THEN: 60초 쿨다운 안내가 뜨고 그동안 챌린지가 안 뜬다. 60초 지나면 자동 해제되고 그 IP 기록은 삭제된다. 인증 성공 시에도 IP 기록 즉시 삭제.

**AC-11 · 음성 트리거는 이동만**
- GIVEN: 메인 앱에서 "관리자 페이지 접근할게요" 발화 (dispatch._is_admin_trigger)
- WHEN: STT가 잡음
- THEN: 같은 탭 URL이 `/admin`으로 바뀌고 챌린지 화면이 뜬다 — 아무 권한도 안 줌(실제 진입은 챌린지 통과 필요). 트리거 문구 자체는 노출/복제돼도 무방.

**AC-11 · 인증 후 승인 동작 + 로그**
- GIVEN: 김철수가 2FA 통과 상태
- WHEN: 어떤 레시피의 "등록" 버튼을 누름
- THEN: 부모 스펙 AC-02대로 그 레시피가 조회 가능해지고, 서버 콘솔에 `[admin] 김철수: approve <recipe_id>` 로그가 남는다
