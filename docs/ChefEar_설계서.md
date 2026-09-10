# 셰프이어(ChefEar) — 배포용 시스템 설계서

작성자: 김승욱 · 기준일: 2026-09-10 (최종본, 배포 중인 소스 기준)

기능 요구사항·데이터 모델·인터페이스의 상세 근거는 `docs/ChefEar_PRD_SDD_v0.9.md`가 1차 문서이고, 이 문서는 배포·운영 관점 요약이다.

## 1. 한 줄 정의

화면을 보지 않고 음성만으로 요리 레시피를 한 단계씩 안내받는 에이전트. STT(Whisper)·TTS(Qwen3-TTS)를 요리 도메인으로 파인튜닝해 GPU 서버에서 상시 배포 중이다. 로그인 사용자는 새 레시피를 등록해 본인 전용으로 쓸 수 있다.

## 2. 전체 아키텍처

```
[브라우저: 상시 마이크 WebRTC] ── Cloudflare Tunnel(chefear.store) ──▶ [Streamlit 메인 프로세스]
        │ 오디오 스트림                                                   │ 마이크 드레인 · 화면
        ▼                                                                 ▼
[silero-vad] 발화 구간 분리 ─────────────────────────────▶ [GPU 워커 풀 (프로세스 3개, spawn)]
                                                              ├─ STT: faster-whisper (CT2 int8)
                                                              ├─ 임베딩: ko-sroberta (의도분류)
                                                              ├─ 로컬 LLM: EXAONE-3.5-2.4B (요리명·등록의도)
                                                              └─ TTS: Qwen3-TTS 1.7B (voice-clone)
                                                                       │
   [Supabase: recipes / recipe_steps / users] ◀── 조회·등록·계정 ──────┘
                                                                       │
                                     오디오 자동재생 + 화면(단계·재료·대화) 갱신 ◀┘

[관리자 /admin] ── 토큰(1차) + ECAPA-TDNN 화자검증(2차, CPU) ──▶ 레거시 승인 대기 행 처리
```

발화 하나의 처리 순서: VAD → STT → 단위 정규화·문맥 숫자 보정·환각 방어 → (조리 중이 아니면) 로컬 LLM 요리명 추정 → 임베딩 의도분류 → 조회/진행/등록 라우팅 → `[TERM]` 태그 해석 → TTS → 재생.

## 3. 화면/페이지

**일반 사용자**: `login`/`signup` → `start` → `recipe_confirm` → `cooking_step`(반복) → `cooking_complete`. 등록: `register_dish_name` → `register_ingredients` → `register_steps` → `complete`. 계정: `my_recipes` → `edit_recipe`. 기타: `unclassified`.

**관리자 전용**(별도 Streamlit 페이지): `/admin`(레거시 승인 대기 목록·승인·삭제), `/enroll`(관리자 목소리 등록).

화면 전환 잔상(streamlit/streamlit#8360)은 화면 본문을 재사용 `st.empty()` 슬롯 하나에 그려 자식 엘리먼트 수를 고정하는 방식으로 대응한다. 마이크 컴포넌트는 화면 컨테이너 밖에서 세션당 한 번만 마운트한다.

## 4. 접근 제어

| 대상 | 방식 |
| --- | --- |
| 서비스 진입 | 랜딩페이지(Vercel)를 거친 `?key=<ACCESS_GATE_TOKEN>` URL만 허용(비우면 게이트 꺼짐) |
| 일반 사용자 | 로컬 가입(`sha256(username)`) 또는 구글 OAuth(`sha256(google_sub)`), Streamlit `st.login()` |
| 등록·마이레시피 | 로그인 필수. 등록 레시피는 `owner_id` 필터로 본인에게만 노출, 타인 `recipe_id` 수정·삭제 거부 |
| 관리자 | 1차 `?admin_key=<ADMIN_ACCESS_TOKEN>` → 2차 랜덤 한글 단어 3개 낭독, STT 단어 일치(2/3) + ECAPA-TDNN 코사인 유사도 ≥ 0.55. IP당 5회 실패 시 60초 잠금 |

관리자 성문은 `data/admin_voiceprints.json`(로컬 파일, 커밋 금지).

## 5. 데이터 모델

`recipes`(요리 1건당 1행): `dish_name`/`ingredients`/`source`(api_standard|user_custom)/`view_count`/`servings`/`owner_id`/`approved`/`created_at`. `recipe_steps`(단계별): `recipe_id`/`step_number`/`step_text`(`[TERM:용어]` 태그 포함)/`source`(api_standard|user_custom|rule_generated). `users`: `user_id_hash`(PK)/`user_id`/`auth_provider`/`google_sub`/`password_hash`/`session_token_hash`.

표준 데이터는 한국 가정식 500개(조리 단계 2,950건, 용어 태그 926개), 적재 시 `approved='Y'`. 신규 등록은 `owner_id` 필수, `approved='Y'`로 즉시 저장되며 본인에게만 조회된다. `approved='N'`은 09-02 이전 레거시 행에만 남아 있다.

## 6. 배포 환경

| 항목 | 내용 |
| --- | --- |
| 서버 | RunPod GPU Pod, A40 48GB (2026-08-31 이관. 이전: 팀 RTX 5070 12GB 데스크탑) |
| 이미지 | 멀티스테이지 Dockerfile — CUDA 12.4 runtime, Python 3.13 소스 빌드, torch 2.6.0 cu124, flash-attn 사전빌드 휠. GitHub Actions → GHCR |
| 기동 | `docker/entrypoint.sh`가 구글 OAuth `secrets.toml` 생성 → cloudflared → Streamlit. 부팅 시 워커 풀 셀프 워밍업 |
| 도메인 | Cloudflare Tunnel → `chefear.store`. 랜딩 `chefear-landingpage.vercel.app` |
| 마이크 | Cloudflare Realtime TURN 우선, 없으면 자체 TURN 또는 구글 STUN |
| 운영 | 평소 Pod Stop으로 과금 중지, 시연 전 Start. 절차는 `docs/runpod_deploy.md` |

GPU 워커 풀: 기본 3 프로세스(`GPU_WORKER_COUNT`), 워커당 VRAM 약 10.4GB. 워커가 죽으면 풀을 자동 재생성한다.

## 7. 딥러닝 파인튜닝 요약

| 모델 | 방식 | 결과 |
| --- | --- | --- |
| STT whisper-large-v3-turbo | QLoRA 4-bit, r=16/alpha=64, MIX750(리플레이 500 + 숫자보강 250) | 신규500 WER 33.20% → 10.72%, 숫자·단위 90.57%. 배포 int8 재측정 Fixed100 WER 11.83% |
| TTS Qwen3-TTS-1.7B | KSS LoRA, epoch-13 채택(epoch-24 회귀) | 재인식 CER 5문장 0.00, 블라인드 MOS 4.67(1위) |

상세 수치와 재현 방법은 `README.md` 5장, `results/`.

## 8. 설계 이력

| 결정 | 일자 | 근거 |
| --- | --- | --- |
| 재료 대체 제거 | 08-27 | `docs/specs/remove_ingredient_substitution.md` |
| 계정 제거 → 관리자 승인 모델 | 08-27 | `docs/specs/remove_user_accounts.md`, `admin_recipe_approval.md` |
| GPU 데스크탑 → RunPod A40 | 08-31 | `docs/runpod_deploy.md` |
| 스레드 락 → 프로세스 워커 풀 | 09-01 | `src/orchestration/gpu_worker_pool.py` |
| 60,282건 → 500건 큐레이션 | 09-01 | `docs/decisions.md` |
| 계정 재도입(로컬+구글) + 마이레시피 | 09-01 | `docs/specs/user_accounts_google_login.md`, `my_recipes.md` |
| 등록 로그인 필수 + 본인 전용 노출 | 09-02 | `docs/specs/private_recipe_visibility.md` |
