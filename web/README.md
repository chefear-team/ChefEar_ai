# ChefEar 웹 클라이언트

Vite + React 18 + TypeScript SPA. 화면은 전부 서버가 주는 `State.screen` 으로 정해지고, 클라이언트가 들고 있는 것은 `session_id`(localStorage)와 로그인 정보뿐이다. API 계약: `../renewal/API_CONTRACT.md`.

## 실행

```bash
cd web
npm install
cp .env.example .env.local   # 값 채우기
npm run dev                  # 개발 서버
npm run build                # tsc 타입검사 + 정적 빌드 -> dist/
npm run preview              # 빌드 결과 확인
```

서버 없이 눌러 보기: `.env.local` 에 `VITE_MOCK=1` (브라우저 안의 가짜 API, 음성 인식은 동작하지 않고 글자 입력/버튼만 된다).

`npm run dev`/`build` 전에 `scripts/copy-vad-assets.mjs` 가 VAD 정적 파일(silero 모델, worklet, onnxruntime wasm)을 `public/vad/` 로 복사한다(git 제외).
개발 서버에서는 `vite.config.ts` 의 `vadDevAssets` 플러그인이 `/vad/*` 를 파일 그대로 내준다(onnxruntime 이 public 파일을 모듈로 import 하는 것을 Vite 가 막기 때문). 운영 빌드에는 영향이 없다.

## 환경변수 (`.env.example`)

| 이름 | 설명 |
|---|---|
| `VITE_API_BASE` | API 주소. 비우면 같은 origin |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | 로그인. 비면 구글/이메일 로그인 숨김 |
| `VITE_GOOGLE_CLIENT_ID` | 구글 클라이언트 ID. 있으면 구글에서 이 사이트(`<origin>/`)로 바로 돌아와 id_token 으로 로그인한다(계정 선택 화면에 이 사이트 주소가 뜸). 그 주소를 구글 클라이언트의 리디렉션 URI 에 등록해야 한다. 비면 Supabase 콜백을 거친다 |
| `VITE_DEMO_VIDEO_URL` | 랜딩의 데모 영상(mp4/webm, YouTube, Vimeo). 비면 숨김 |
| `VITE_MOCK` | `1` 이면 가짜 API |

`VITE_*` 값은 빌드 때 번들에 박힌다. anon key 와 데모 계정은 공개돼도 되는 값만 쓴다.

## 음성

- 서비스 전체가 로그인 전용이다. 로그인 전에는 로그인 화면(구글 우선, 이메일은 시트)만 보이고, 서버도 비로그인 요청을 401 `login_required` 로 거절한다.
- 로그인한 뒤 `시작하기` 를 눌러야 마이크/오디오를 켠다(자동 재생·권한 정책).
- `@ricky0123/vad-web` 의 silero VAD 가 브라우저에서 발화를 잘라 내고, 끝나면 16kHz 모노 16-bit WAV 로 `POST /api/session/{id}/utterance`(multipart `audio`) 로 보낸다.
- 음성이 나오는 동안과 끝난 뒤 600ms 는 VAD 를 멈춘다. 요청 처리 중에도 멈춘다(연결은 유지).
- 레시피 등록·마이레시피 같은 글자 입력 화면에서는 마이크 연결 자체를 닫는다(브라우저 표시등 꺼짐). 조리 흐름으로 돌아오면 다시 연결한다.
- "마이크 끄기" 와 로그아웃도 연결을 닫는다. 로그인 후 `시작하기` 를 누르면 다시 연결된다.
- 말이 안 될 때를 위해 "말 대신 입력하기"(JSON `{text}`)와 버튼이 항상 있다.

## Vercel 배포

1. Vercel 에서 이 저장소를 Import, **Root Directory = `web`**.
2. Framework Preset 은 Vite(자동 감지). Build Command `npm run build`, Output `dist`.
3. Environment Variables 에 위 `VITE_*` 를 등록하고 배포.
4. API 서버(Modal)의 CORS 허용 origin 에 Vercel 도메인을 추가하고, Supabase Auth 의 Redirect URL 에도 같은 도메인을 추가한다. `VITE_GOOGLE_CLIENT_ID` 를 쓰면 구글 클라이언트의 리디렉션 URI 에 `https://<도메인>/` 도 추가한다.
5. `public/privacy.html`, `public/terms.html` 은 구글 로그인 앱 게시에 필요한 개인정보처리방침·약관이다. 실제 동작(수집 항목, 처리 업체)이 바뀌면 같이 고친다.
