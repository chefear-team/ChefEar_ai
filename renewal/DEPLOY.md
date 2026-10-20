# ChefEar 리뉴얼 — 배포 절차

구성: 웹(Vercel) + API·STT·TTS(Modal, 마지막 요청 뒤 5분이 지나면 0대) + DB·파일·로그인(Supabase 무료).
키는 채팅·저장소에 붙여 넣지 말고 아래 위치에만 넣는다.

## 0. 먼저 해 둘 것

| 어디 | 무엇 | 비고 |
|---|---|---|
| Hugging Face | 읽기 토큰 1개 | `kimseunguk/qwen3-tts-kss-finetuned`, `kimseunguk/chefear-stt-ct2-int8` 접근 권한이 있는 계정 |
| Supabase | 프로젝트 1개 | 무료 |
| Modal | 가입 후 `pip install modal` → `python -m modal token new` | 월 $30 무료 크레딧. GPU를 쓰려면 결제 수단 등록(소액 인증 결제)이 필요 |
| Vercel | 가입 후 `npm i -g vercel` → `vercel login` | |

## 1. Supabase

1. SQL Editor에서 `db/schema.sql`(새 프로젝트일 때), 이어서 **`db/migrate_renewal.sql`** 을 실행한다. 세션·음성 목록 테이블, 버킷 2개(`tts` 공개 / `tts-private` 비공개), 그리고 공개(anon) 키로 DB를 못 건드리게 하는 보안 변경이 들어 있다. 여러 번 실행해도 안전하다. 채팅창에서 복사하면 따옴표가 바뀌어 오류가 나니 **파일을 열어서 복사**한다.
2. 레시피 500개 적재(새 프로젝트일 때만, 이미 있으면 중복): `.env`에 `SUPABASE_URL`, `SUPABASE_KEY`(서버 전용 키)를 넣고 `python src/orchestration/load_500_recipes.py`.
3. Authentication → URL Configuration: Site URL `https://<웹 주소>`, Redirect URLs에 `https://<웹 주소>/**`.
4. 구글 로그인: Google Cloud Console에서 OAuth 클라이언트(웹 애플리케이션)를 만들고, 승인된 리디렉션 URI에 `https://<프로젝트>.supabase.co/auth/v1/callback`을 넣는다. 클라이언트 ID·시크릿을 Supabase → Authentication → Providers → Google에 넣고 Enable. 동의 화면이 "테스트" 상태면 등록한 사용자만 로그인되니 불특정 사용자가 쓰게 하려면 앱을 게시한다.
5. 이메일 가입을 쓰면 Supabase 기본 메일은 발송 한도가 매우 작다(프로젝트 전체 시간당 몇 통 수준으로 알려져 있음). 많은 사용자를 받으려면 Authentication → Providers → Email에서 **Confirm email**을 끄거나 SMTP를 연결한다. 구글 로그인은 메일이 필요 없다.
6. API 키 두 개를 구분한다: 공개(anon/publishable)는 웹과 `SUPABASE_ANON_KEY`용, `service_role`/`sb_secret`은 서버 전용(웹·저장소에 절대 넣지 않는다).

## 2. 공용 음성 올리기 (직접 만든 mp3 2,724개)

1. 파일을 `data/tts_audio/standard/`에 `data/tts_manifest.csv`의 `file_name` 그대로 넣는다(이 폴더는 git에 올리지 않는다).
2. `python scripts/upload_tts_audio.py --dry-run` — 개수가 맞는지 확인(빠진 것·크기 0·목록에 없는 것을 알려 준다).
3. `python scripts/upload_tts_audio.py` — Storage `tts/standard/`에 올리고 `tts_assets`에 기록한다. 이어하기가 된다.

올리기 전에는 응답 문장 대부분이 실시간 TTS(GPU)로 합성되어 느리고 비용이 든다.

## 3. Modal

1. 비밀값 `chefear`(Modal 대시보드 → Secrets)를 만든다.

   | 이름 | 값 |
   |---|---|
   | `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_ANON_KEY` | Supabase 값(`SUPABASE_KEY`는 서버 전용 키) |
   | `HF_TOKEN` | Hugging Face 읽기 토큰 |
   | `HF_STT_CT2_REPO` | `kimseunguk/chefear-stt-ct2-int8` |
   | `INFERENCE_BACKEND` | `modal` |
   | `ALLOWED_ORIGINS` | 웹 주소(예: `https://chefear.vercel.app`). 처음에는 `*`로 두었다가 좁힌다 |
   | `REGISTER_DAILY_LIMIT` | `5` (선택) |

2. 배포(STT를 GPU로): `CHEFEAR_STT_GPU=L4 python -m modal deploy inference/modal_app.py`
   - 처음에는 이미지를 만들며 STT(0.82GB)·TTS(4.55GB) 모델을 이미지 안에 미리 받아 둔다(약 5분 30초). 이후 컨테이너가 켜질 때는 내려받지 않는다.
   - 모델을 새로 올렸다면 `inference/modal_app.py`의 `BAKE_VERSION`을 올려야 이미지가 다시 만들어진다. 안 올리면 예전 모델이 계속 쓰인다.
   - 출력된 `api` 주소(`https://<워크스페이스>--chefear-api.<리전>.modal.run`)를 적어 둔다.
   - 배포 직후 1~2분은 내려가는 중인 옛 컨테이너가 응답할 수 있다.
3. **월 지출 한도**: Modal 대시보드 Settings → Usage & billing에서 Spend limit을 `$0`으로 건다. 무료 크레딧이 떨어지면 카드 청구 대신 작업이 멈춘다.

### STT를 GPU로 둔 근거 (`modal run inference/bench_stt.py`, `results/stt/bench_modal.json`)

Fixed100 앞 10문장, 발화당 평균:

| 환경 | 평균 | 모델 로드 | WER |
|---|---|---|---|
| CPU 2 vCPU | 11.27초 | 9.2초 | 11.1% |
| CPU 4 vCPU | 8.12초 | 7.9초 | 11.1% |
| **GPU L4** | **0.20초** | 7.1초 | 15.6% |

WER 차이는 표본이 10문장뿐이라 의미 있게 비교할 수 없다(100문장 전체 재측정이 필요). 속도 차이는 분명해서 STT는 GPU로 한다. GPU도 안 쓰는 동안은 0대라 대기 비용이 없다.

## 4. 웹(Vercel)

CLI로 만들 때:

```bash
cd web
vercel link --yes --project chefear
vercel env add VITE_API_BASE production --value "https://<api 주소>" --yes
vercel env add VITE_SUPABASE_URL production --value "https://<프로젝트>.supabase.co" --yes
vercel env add VITE_SUPABASE_ANON_KEY production --value "<공개 키>" --yes
vercel deploy --prod --yes
```

GitHub 연동으로 만들 때는 이 저장소를 Import하고 **Root Directory = `web`**, Build Command `npm run build`, Output `dist`, 같은 환경변수를 넣는다.

`VITE_*` 값은 브라우저 번들에 들어가므로 공개돼도 되는 값(공개 키, 주소)만 쓴다. 배포 뒤 웹 주소를 Modal 비밀값 `ALLOWED_ORIGINS`와 Supabase Redirect URL에 넣고 `modal deploy`를 한 번 더 한다.

## 5. 쉬는 동안 꺼지지 않게

Supabase 무료 프로젝트는 1주 동안 접속이 없으면 일시정지된다. 저장소 비밀값(Settings → Secrets and variables → Actions)에 `SUPABASE_URL`, `SUPABASE_KEY`를 넣으면 `.github/workflows/keepalive.yml`이 3일마다 DB를 읽어 정지를 막는다. 정기 실행은 **기본 브랜치에 있는 워크플로만** 돈다.

## 6. 확인

1. `GET {api}/api/health` → `{"ok": true}`
2. 웹을 열면 로그인 화면만 보인다. 로그인 전에 `POST {api}/api/session`은 401.
3. 로그인 → "시작하기" → 마이크를 허용 → "된장찌개 어떻게 만들어?" → "응" → "다음".
4. 레시피 등록 → 저장 완료 화면에 음성 준비 안내(보통 1~3분)가 뜨고 끝나면 "준비 완료"로 바뀌는지, 마이레시피에서도 같은 상태인지.
5. 5분 이상 쉬었다가 다시 열어 콜드 스타트 시간을 잰다(API만 깨어나는 데 약 20초, GPU 모델 로드는 더 걸린다).

## 알아 둘 것

- 비용(가정 기반 추정): 한 번의 조리 흐름(5분 사용 + 5분 대기)이 STT L4 약 10분 + API 약 10분이면 약 $0.15 안팎이다. 실제 사용 뒤 `python -m modal billing report`로 확인한다.
- STT 내부 VAD는 기본 끔(브라우저가 이미 말한 구간만 보낸다). 켜려면 비밀값 `STT_VAD_FILTER=1`.
- 요리명 추출용 LLM(EXAONE)은 서비스 경로에서 쓰지 않는다. 같은 발화 세트로 정확도 비교(A/B)는 아직 하지 않았다.
- 이 PC 밖에서 실제 사람이 마이크로 끝까지 돌려 본 기록은 없다(글자 입력 흐름과 브라우저 자동화로 화면·API는 확인). 배포 후 6번으로 확인한다.
