# docs/specs/ — 기능 스펙 목록과 최종 상태

스펙은 작성 시점의 결정을 기록한 문서라 본문은 그대로 두고, 여기서 2026-09-10 기준 상태만 정리한다. 형식은 `_example.md`(Why/Goal/What/How/AC).

| 스펙 | 작성일 | 최종 상태 |
|---|---|---|
| `app_e2e.md` | 08-19 | **구현됨** — `src/app.py` 종단 통합(마이크→STT→오케스트레이션→TTS) |
| `stt_deploy.md` | 08-19 | **구현됨** — `stt_transcribe()` + CTranslate2 변환. 배포 대상은 HF Spaces CPU → GPU 서버로 바뀜 |
| `llm_dish_name_extract.md` | 08-21 | **구현됨** — 로컬 LLM(EXAONE) 요리명 추정·등록 의도 판단 |
| `tts_loading_overlay.md` | 08-22 | **구현됨** — TTS 합성 중 전체 화면 오버레이 |
| `dish_not_found_voice_notice.md` | 08-25 | **구현됨** — `no_match` 화면 제거, 음성 안내 1회로 대체 |
| `remove_ingredient_substitution.md` | 08-27 | **적용됨** — 재료 대체 기능·코드·의도 카테고리 제거 |
| `remove_user_accounts.md` | 08-27 | **대체됨** — 계정 제거 결정은 09-01 `user_accounts_google_login.md`로 뒤집힘 |
| `admin_recipe_approval.md` | 08-27 | **레거시 전용** — 승인 워크플로우 코드는 남아 있으나 09-02 이후 신규 등록은 승인 대기에 들어오지 않음 |
| `admin_voice_2fa.md` | 08-28 | **구현됨** — 관리자 페이지 토큰 + ECAPA-TDNN 화자검증. 레거시 행 처리용 |
| `user_accounts_google_login.md` | 09-01 | **구현됨** — 로컬 가입 + 구글 OAuth |
| `my_recipes.md` | 09-01 (사후 작성) | **구현됨** — 마이레시피 목록/수정/삭제 |
| `private_recipe_visibility.md` | 09-02 (사후 작성) | **구현됨** — 등록은 로그인 필수, 등록 레시피는 본인에게만 노출 |
| `edit_recipe_term_tag.md` | 10-09 | **구현됨** — 마이레시피 수정 시 `[TERM:...]` 태그가 별도 단계로 분리되는 버그 수정 |

`my_recipes.md`와 `private_recipe_visibility.md`는 구현 당시 스펙 없이 커밋됐고, 코드·문서가 참조하는 파일이 비어 있어 2026-09-10에 커밋 이력을 바탕으로 사후 작성했다.
