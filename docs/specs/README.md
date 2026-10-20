# docs/specs/ — 기능 스펙 목록과 최종 상태

> 2026-10-20 리뉴얼(`renewal_serverless.md`)로 Streamlit 앱이 웹 + API + Modal 구조로 바뀌었다. 아래 중 Streamlit 화면·관리자·로컬 계정에 관한 스펙은 **리뉴얼 전(2026-09-10) 기준 기록**이며, 상태 열에 리뉴얼 이후의 처리를 덧붙였다.

스펙은 작성 시점의 결정을 기록한 문서라 본문은 그대로 두고, 여기서 2026-09-10 기준 상태만 정리한다. 형식은 `_example.md`(Why/Goal/What/How/AC).

| 스펙 | 작성일 | 최종 상태 |
|---|---|---|
| `app_e2e.md` | 08-19 | **대체됨(리뉴얼)** — 종단 통합은 `server/` + `inference/` + `web/`로 다시 구성 |
| `stt_deploy.md` | 08-19 | **구현됨** — `stt_transcribe()` + CTranslate2 변환. 배포 대상은 HF Spaces CPU → GPU 서버로 바뀜 |
| `llm_dish_name_extract.md` | 08-21 | **서비스에서 제거(리뉴얼)** — 요리명 매칭 + 임베딩 분류로 대체, 코드(`src/llm`)는 남김. 정확도 A/B 미측정 |
| `tts_loading_overlay.md` | 08-22 | **제거됨** — 마스코트 오버레이 철회 후 현재 화면에는 흐림·배너 안내 |
| `dish_not_found_voice_notice.md` | 08-25 | **구현됨** — `no_match` 화면 제거, 음성 안내 1회로 대체 |
| `remove_ingredient_substitution.md` | 08-27 | **적용됨** — 재료 대체 기능·코드·의도 카테고리 제거 |
| `remove_user_accounts.md` | 08-27 | **대체됨** — 계정 제거 결정은 09-01 `user_accounts_google_login.md`로 뒤집힘 |
| `admin_recipe_approval.md` | 08-27 | **제거됨(리뉴얼)** — 관리자 페이지 삭제 |
| `admin_voice_2fa.md` | 08-28 | **제거됨(리뉴얼)** — 관리자 페이지·화자검증 삭제 |
| `user_accounts_google_login.md` | 09-01 | **대체됨(리뉴얼)** — Supabase Auth(구글·이메일), 서비스 전체 로그인 전용 |
| `my_recipes.md` | 09-01 (사후 작성) | **구현됨** — 리뉴얼에서 REST(`/api/my-recipes`)와 웹 화면으로 이식 |
| `private_recipe_visibility.md` | 09-02 (사후 작성) | **구현됨** — 리뉴얼에서도 유지(본인 소유만 접근, IDOR 방지) |
| `renewal_serverless.md` | 10-20 | **구현됨(일부 미측정)** — 서버리스 웹앱 리뉴얼. AC 표에 미측정 항목 명시 |
| `edit_recipe_term_tag.md` | 10-09 | **구현됨** — 마이레시피 수정 시 `[TERM:...]` 태그가 별도 단계로 분리되는 버그 수정 |

`my_recipes.md`와 `private_recipe_visibility.md`는 구현 당시 스펙 없이 커밋됐고, 코드·문서가 참조하는 파일이 비어 있어 2026-09-10에 커밋 이력을 바탕으로 사후 작성했다.
