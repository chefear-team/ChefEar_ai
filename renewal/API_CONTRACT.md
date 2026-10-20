# ChefEar 리뉴얼 — API 계약

웹(`web/`), API 서버(`server/`), 추론 서버(`inference/`)가 공유하는 약속. 바꾸면 세 곳을 같이 고친다.

## 1. 구성

| 층 | 위치 | 배포 |
|---|---|---|
| 웹 | `web/` (Vite + React + TS, 정적 빌드) | Vercel |
| API | `server/chefear_api` (FastAPI) | Modal(CPU, ASGI) — 로컬은 uvicorn |
| 추론 | `inference/modal_app.py` | Modal: STT(실시간), TTS(실시간 예외), 등록 음성 생성(배치) |
| 데이터 | Supabase Postgres + Storage + Auth | Supabase Free |

## 2. 인증

- 웹은 supabase-js로 로그인한다(구글, 이메일). API 호출 시 `Authorization: Bearer <access_token>`.
- API는 `GET {SUPABASE_URL}/auth/v1/user`로 토큰을 확인하고 `user.id`를 `owner_id`로 쓴다(5분 캐시).
- **서비스 전체가 로그인 전용이다.** 토큰이 없거나 틀리면 `/api/health`, `/api/warmup`을 뺀 모든 엔드포인트가 `401 {"detail": "login_required"}`로 거절한다(GPU 비용 보호). `warmup`은 비로그인이면 GPU를 깨우지 않고 `{"stt": "login_required"}`를 돌려준다.
- `x-dev-user` 헤더는 `ALLOW_DEV_USER=1`일 때만 로그인으로 취급한다(로컬 테스트용, 운영에서는 끈다).

## 3. 공통 응답 `State`

```json
{
  "session_id": "uuid",
  "screen": "start | recipe_confirm | cooking_step | cooking_complete | unclassified | register_dish_name | register_ingredients | register_steps | complete | login_required | my_recipes | edit_recipe",
  "logged_in": true,
  "transcript": "STT 결과(발화 요청일 때만, 없으면 null)",
  "speech": {"text": "읽을 문장", "audio_url": "https://... 또는 null"},
  "notice": "화면에만 띄울 짧은 안내(음성 없음) 또는 null",
  "chat": [{"role": "user|ai", "text": "..."}],
  "recipe": {
    "recipe_id": "uuid", "dish_name": "된장찌개",
    "ingredients": ["두부", "감자"],
    "steps": [{"step_number": 1, "text": "화면용 문장"}],
    "step_number": 1, "total": 6
  },
  "registration": {"dish_name": "문어초무침", "ingredients": ["문어"], "instructions": ["..."], "guess": "추측한 요리명 또는 null"}
}
```

- `speech`가 null이면 말하지 않는다. `audio_url`이 null이면 웹은 `POST /api/tts`로 실시간 음성을 받거나, 실패하면 글자만 보여 준다.
- `recipe`, `registration`은 해당 화면이 아니면 null.

## 4. 엔드포인트

| 메서드 | 경로 | 본문 | 응답 |
|---|---|---|---|
| GET | `/api/health` | — | `{"ok": true}` |
| POST | `/api/warmup` | — | `{"stt": "warming|ready|disabled|login_required"}` (로그인한 경우에만 STT 컨테이너를 미리 깨움. TTS는 깨우지 않는다) |
| POST | `/api/session` | — | `State` (새 세션, 화면 start) |
| GET | `/api/session/{id}` | — | `State` |
| POST | `/api/session/{id}/utterance` | `multipart/form-data`: `audio`(WAV 16kHz 모노) 또는 JSON `{"text": "..."}` | `State` |
| POST | `/api/session/{id}/action` | JSON `Action` | `State` |
| POST | `/api/tts` | `{"text": "..."}` | `audio/mpeg` (실시간 합성, 레이트 제한) |
| GET | `/api/my-recipes` | — | `[{"recipe_id","dish_name","created_at","audio_ready": bool}]` (로그인) |
| GET | `/api/my-recipes/{id}` | — | `{"recipe_id","dish_name","ingredients":[],"instructions":[]}` |
| PUT | `/api/my-recipes/{id}` | `{"dish_name","ingredients":[],"instructions":[]}` | 같은 형식 |
| DELETE | `/api/my-recipes/{id}` | — | `{"deleted": true}` |

### Action

| type | 필드 | 쓰는 화면 |
|---|---|---|
| `nav` | `name`: `이전`·`다시`·`다음` | cooking_step |
| `goto_step` | `step_number` | cooking_step |
| `start_cooking` | — | recipe_confirm |
| `other_recipe` | — | recipe_confirm |
| `home` | — | 어디서나 |
| `register_start` | — | start (로그인 필요) |
| `register_dish_name` | `value` | register_dish_name |
| `register_add_ingredients` | `items: []` | register_ingredients |
| `register_ingredients_done` | — | register_ingredients |
| `register_add_step` | `text` | register_steps |
| `register_edit_step` | `index`, `text` | register_steps |
| `register_delete_step` | `index` | register_steps |
| `register_save` | — | register_steps |
| `cancel` | — | 등록 화면 |

## 5. 음성 파일

- 키: `server/chefear_api/speech.py::audio_key(text)` = sha256(`VOICE_VERSION` + `\n` + 문장) 앞 32자. 파일 이름 `{키}.mp3`.
- 공용(500개 레시피·고정 문구): Storage 공개 버킷 `tts`, 경로 `standard/{키}.mp3`. 원본 파일은 `data/tts_audio/standard/`.
- 사용자 등록 레시피: 비공개 버킷 `tts-private`, 경로 `users/{owner_id}/{키}.mp3`, 서명 URL(1시간)로만 재생.
- 어떤 키가 올라가 있는지는 `tts_assets` 테이블로 판단한다(`key`, `scope`, `owner_id`).

## 6. 추론 서버 (Modal, `inference/modal_app.py`)

운영(`INFERENCE_BACKEND=modal`)에서는 API가 Modal SDK로 함수를 직접 부른다. STT·TTS는 **공개 주소가 없다**(남이 호출해 비용을 쓸 수 없다).
개발(`INFERENCE_BACKEND=http`)에서는 아래 주소·공유 토큰(`x-chefear-token`)으로 부를 수 있다.

| Modal 클래스.메서드 | 입력 | 출력 | 자원 |
|---|---|---|---|
| `Stt.transcribe` | WAV 바이트 | 텍스트(못 알아들으면 빈 문자열) | L4(`CHEFEAR_STT_GPU`로 배포 때 선택, 비우면 CPU지만 실측 발화당 8~11초라 쓰지 않음), 마지막 요청 후 300초 유지 |
| `Tts.synthesize` | 문장 | mp3 바이트 | L4, 300초 유지 |
| `RecipeAudio.generate` (spawn) | `recipe_id`, `owner_id` | `{"status","made",...}` | L4 배치, 동시 1대 |
| `Stt.warmup`, `Tts.warmup` (spawn) | — | — | 컨테이너를 깨움 |

공개 주소는 `api`(ASGI) 하나뿐이다.

## 7. 입력 검증과 오류 코드

모든 사용자 글자(채팅, 음성 인식 결과, 등록 폼, 마이레시피 수정, TTS)는 `server/chefear_api/guard.py`를 거친다. 정리(유니코드 정규화, 제어문자·보이지 않는 문자 제거), 길이 제한, 명백한 공격 문구 차단 순서다.

| 필드 | 제한 |
|---|---|
| 채팅·음성 인식 결과 | 200자. 넘으면 `notice`로 안내만 하고 처리하지 않음 |
| 요리명 | 80자 |
| 재료 | 항목당 60자, 최대 40개 |
| 조리 단계 | 단계당 200자, 최대 30개 |
| TTS 문장 | 600자 |
| 요청 본문 | 음성 최대 크기 + 64KB 초과는 413 |

채팅·음성에서 공격 문구가 잡히면 대화 기록·DB 조회 없이 `notice`만 돌려주고, 한 세션에서 10회를 넘으면 400 `too_many_invalid`. 폼·수정·TTS는 400 `invalid_text`.

| 상태 | `detail` | 뜻 |
|---|---|---|
| 400 | `invalid_text` `invalid_input` `bad_json` `bad_text` `unknown_action` | 입력 형식·문구 문제 |
| 400 | `text_too_long` `dish_name_too_long` `ingredient_too_long` `step_too_long` `ingredient_too_many` `step_too_many` `too_many_invalid` | 길이·개수 제한 |
| 401 | `login_required` | 로그인 필요 |
| 404 | `not_found` `recipe_not_found` | 없음(남의 레시피도 같은 응답) |
| 413 | `payload_too_large` `audio_too_large` | 크기 제한 |
| 429 | `rate_limited` | IP당 분당 요청 제한 |
| 503 | `stt_unavailable` `tts_unavailable` | 추론 서버 문제 |

웹은 이 코드를 `web/src/lib/errors.ts`에서 한글 문구로 바꿔 보여 준다.
