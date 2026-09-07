# RunPod 배포 (팀 GPU 데스크탑 대체)

기존 "팀 GPU 데스크탑 상시 구동 + Cloudflare Tunnel" 구조를 그대로 RunPod GPU Pod로
옮긴다. **랜딩페이지(Vercel)·접근게이트·도메인(chefear.store)은 전혀 안 건드린다** —
Cloudflare Tunnel의 실행 주체만 팀 데스크탑 → RunPod Pod로 바뀐다.

면접 데모용이라 상시 트래픽이 없다는 전제로 설계했다: 평소엔 Pod를 **Stop**(터미네이트
아님)해서 GPU 과금을 멈추고, 면접 직전에 Start만 누르면 이 문서의 나머지 과정 없이
Dockerfile의 `docker/entrypoint.sh`가 cloudflared+Streamlit을 자동으로 다 띄운다 —
로컬에서 `run_local.sh` 같은 걸 실행할 필요가 없다.

**레포 위치(2026-08-31 확정)**: 원래 팀 공용 레포 `minhahamin/cookEar_ai`(홍민하 개인
계정 소유)에서 작업했으나, GHCR 패키지 공개/PAT 발급 같은 걸 매번 계정 소유자 승인
받아야 하는 문제 때문에 **GitHub Organization `chefear-team`**을 새로 만들어
`chefear-team/ChefEar_ai`로 전체 히스토리를 옮겼다. 승욱님·홍민하 둘 다 Organization
**Owner**라 이제 GHCR 패키지 공개 여부·Workflow 권한 등을 누구 허락도 없이 각자
직접 바꿀 수 있다. 원본 팀 레포는 `upstream` 리모트로 남겨뒀고, 그쪽에 뭔가 새로
바뀌면 필요할 때 골라서 가져오면 된다(자동 동기화 아님).

## 0. 이 레포에 이미 준비된 것

- `Dockerfile` — 멀티스테이지: 1단계(devel 베이스)에서 Python 3.13을 소스 빌드하고,
  2단계(runtime 베이스, devel보다 수GB 가벼움)에는 빌드된 Python만 `COPY --from`으로
  가져온다 — gcc 등 컴파일 툴체인이 최종 이미지에 안 남는다. CUDA 12.4 + cloudflared +
  앱 의존성까지 다 구운 이미지. 팀 데스크탑(`run_local.sh`)과 최대한 동일 조건으로
  맞췄다 — 근거는 Dockerfile 상단 주석 참고. **실제 빌드 성공 검증됨**(2026-08-31,
  `minhahamin/cookEar_ai` 레포에서 2회 연속 성공 — Actions run #2, #3).
- `docker/entrypoint.sh` — 컨테이너 시작 시 cloudflared 터널 실행 → Streamlit 앱 실행을
  자동으로 한다. Pod의 Start/Stop이 곧 이 프로세스들의 on/off다.
- `.dockerignore` — `models/`, `result_test*/`, `_work_backups/` 등 수 GB짜리 로컬 산출물을
  빌드 컨텍스트에서 제외(대부분 `.gitignore`에도 있어 원격 레포엔 원래 없음).
- `.streamlit/config.toml` — `headless=true`, `address=0.0.0.0`, `port=8501` 추가.
- `.github/workflows/docker-build.yml` — RunPod Pod는 GitHub 레포/Dockerfile을 직접
  빌드하지 못한다(그건 Serverless 전용 기능, Pod는 이미 빌드된 이미지 URL만 받음).
  대신 이 워크플로가 **`main` 브랜치에 push될 때(앱 코드 `src/`/`ui`/`db`/`data`/
  `.streamlit` 포함) 또는 수동 실행**시 이미지를 빌드해서
  `ghcr.io/chefear-team/chefear_ai:latest`에 올려둔다 — RunPod엔 이 이미지 주소만
  붙여넣으면 되고 로컬 Docker는 필요 없다. `seunguk` 등 다른 브랜치에서 검증하고
  싶으면 GitHub 웹 **Actions → Build & Push RunPod Image → Run workflow** 버튼에서
  브랜치를 선택해 수동 실행(`workflow_dispatch`)한다.

**아직 검증 안 된 부분(첫 배포 때 반드시 확인)**: STT 모델 로딩 시 CUDA/libcublas
에러가 없는지는 아직 RunPod Pod 실제 Start로 확인 전이다. Docker 빌드 자체는
`minhahamin/cookEar_ai` 레포에서 검증됐지만, `chefear-team/ChefEar_ai`로 옮긴 뒤
첫 빌드는 다시 해봐야 한다(레포별로 GHCR/Actions 캐시가 따로 쌓임).

## 1. 이 변경사항을 원격 레포에 올리기 (여기까지만 로컬에서 명령어 입력)

```bash
cd "C:\Users\Wook\Desktop\data\porject\proj1-a"
git add Dockerfile docker/entrypoint.sh .dockerignore .streamlit/config.toml docs/runpod_deploy.md .github/workflows/docker-build.yml
git commit -m "RunPod 배포용 Dockerfile/entrypoint 추가"
git push origin main
```

push든 수동 실행이든 트리거되면 GitHub Actions가 빌드를 시작한다 — **Actions 탭에서
빌드가 끝날 때까지 기다렸다가(첫 빌드는 캐시가 없어 30분 안팎)** 3단계로 넘어갈 것.
그 전에 RunPod에 이미지 주소를 넣어봐야 아직 없는 이미지라 실패한다.

**레포 설정 확인 필요(push 전에 한 번, GitHub 웹에서)**: Settings → Actions → General →
Workflow permissions가 "Read and write permissions"로 되어있어야 GITHUB_TOKEN으로
GHCR에 push가 된다. 기본값이 "Read repository contents" only인 경우가 많아서, 안 되어
있으면 이 워크플로의 GHCR push 단계가 403으로 실패한다.

이후 과정은 전부 GitHub/Cloudflare 대시보드 + RunPod 콘솔에서만 진행한다(로컬 스크립트 실행 없음).

## 2. Cloudflare Zero Trust — 터널 토큰 발급

기존 `chefear` 터널은 `cloudflared tunnel create`(CLI)로 만든 **로컬관리형**이라
대시보드에서 토큰을 바로 못 뽑는다(마이그레이션은 되돌릴 수 없어서 안 함). 대신
credentials 파일을 그대로 재사용한다:

1. 팀 데스크탑(WSL) `~/.cloudflared/`에 있는 `<tunnel-id>.json`(credentials)과
   `config.yml`을 RunPod Network Volume(`/workspace/cloudflared/`)로 옮긴다.
   `config.yml`은 이미 `chefear.store → http://localhost:8501`로 설정돼 있어
   내용 수정 없이 그대로 쓴다 — 단 `credentials-file` 경로만 RunPod 쪽 실제
   경로(예: `/workspace/cloudflared/<tunnel-id>.json`)로 맞춰야 한다.
2. RunPod Pod 환경변수 `CLOUDFLARED_CONFIG`에 그 `config.yml` 경로를 지정한다
   (entrypoint.sh가 `CLOUDFLARE_TUNNEL_TOKEN`이 없으면 이 방식으로 폴백함).
3. 기존 팀 데스크탑에서 돌던 cloudflared는 RunPod 쪽이 정상 확인된 뒤 종료한다. 같은
   터널을 두 군데서 동시에 못 돌리는 게 아니라 안전을 위해서다 — 헷갈릴 수 있으니 순서상
   RunPod 확인 후 데스크탑 걸 끄는 걸 권장.

## 3. RunPod — Pod 생성

1. https://www.runpod.io 가입, 결제수단 등록(완료됨)
2. (선택, 권장) **Storage → Network Volumes**에서 볼륨 생성(예: 20GB) — HF 모델 캐시와
   위 cloudflared 파일들을 여기 두면 나중에 GPU 타입을 바꾸거나 Pod를 새로 만들어도
   안 사라진다.
3. **Pods → Deploy** → GPU: **A40 (48GB)** 선택
4. 이미지 소스: **Custom Container / Docker Image** 선택 → Container Image에
   `ghcr.io/chefear-team/chefear_ai:<커밋SHA 또는 latest>` 입력 (Organization 소유
   레포라 대문자는 GHCR 규칙상 소문자로 변환돼 있음에 주의)
   - GHCR 패키지가 기본 private이면 RunPod가 이미지를 못 받아온다. Organization
     Owner(승욱님 또는 홍민하)가 GitHub → `chefear-team` → **Packages** →
     `chefear_ai` → **Package settings** → Change visibility에서 바로 바꿀 수 있다
     (이미지 안에 시크릿은 없음, `.env`/토큰류는 전부 RunPod 환경변수로만 주입).
     private을 유지하고 싶으면 RunPod Pod 생성 화면의 **Container Registry
     Credentials**에 Organization Owner 계정명 + `read:packages` 권한 PAT를
     등록하는 방법도 있음.
5. Container Disk: 최소 30GB 이상 권장(모델 캐시+torch/CUDA 라이브러리 용량 고려)
6. Network Volume을 만들었으면 마운트 경로 지정 (예: `/workspace`)
7. **Environment Variables**에 아래 값을 채운다 (`.env.example` 목록과 동일, 실제 값은
   Supabase/HF 콘솔·기존 `.env` 파일에서 그대로 가져오면 됨 — 파일 자체를 옮길 필요 없음,
   `orchestration/db.py::load_env()`가 `.env` 파일이 없으면 조용히 넘어가고 시스템
   환경변수를 그대로 쓴다):

   | 변수 | 값 |
   |---|---|
   | `CLOUDFLARED_CONFIG` | 2단계에서 옮긴 `config.yml`의 RunPod 상 경로 (안 채우면 기본값 `/workspace/cloudflared/config.yml` 사용됨 — Network Volume을 `/workspace`에 그대로 다시 붙이면 이 값 자체를 안 넣어도 동작함) |
   | `SUPABASE_URL` / `SUPABASE_KEY` | 기존 값 |
   | `HF_TOKEN` | 기존 값 |
   | `HF_STT_CT2_REPO` | `kimseunguk/chefear-stt-ct2-int8` (기존 값) |
   | `ACCESS_GATE_TOKEN` | 기존 값 (랜딩페이지 링크와 동일해야 함) |
   | `ADMIN_ACCESS_TOKEN` / `ADMIN_VOICE_THRESHOLD` | 관리자 페이지 쓸 경우 |
   | (선택) `HF_HOME` | Network Volume 마운트 경로 아래(예: `/workspace/hf_cache`)로 지정하면 모델이 볼륨에 캐시됨 |
   | (선택) `GPU_WORKER_COUNT` | 안 채우면 3. 2026-09-07 실측: 워커 1개(STT+TTS+LLM+임베딩 전부)가 idle 상태에서 VRAM 10.4GB 사용 — A40(45GB 가용) 기준 3워커면 약 31GB, 여유 있음 |
   | `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | 구글 로그인용(2026-09 추가, docs/specs/user_accounts_google_login.md) — 없으면 로컬 아이디/비밀번호 로그인은 되지만 구글 로그인 버튼 누르면 StreamlitAuthError 남 |
   | `GOOGLE_OAUTH_COOKIE_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(32))"`로 생성 — 비어있으면 entrypoint.sh가 컨테이너 시작 자체를 실패시킴(`:?` 필수 처리) |
   | (선택) `GOOGLE_OAUTH_REDIRECT_URI` | 안 채우면 기본값 `https://chefear.store/oauth2callback` |

   위 표에서 `CLOUDFLARED_CONFIG`/`GOOGLE_OAUTH_*` 4개는 `.env.example`에는 없다 —
   `.env` 파일이 아니라 `docker/entrypoint.sh`가 직접 읽는 RunPod Pod 환경변수라서
   그렇다(구글 OAuth 쪽은 `.streamlit/secrets.toml`을 컨테이너 시작 시 이 값들로
   대신 생성해줌). **Pod를 새로 만들기 전에 이 값들이 로컬 `.env`에도 없다는 걸
   기억해둘 것** — RunPod Pod를 지우면 값 자체가 어디에도 안 남으므로, HF_TOKEN 등
   `.env`에 있는 것들과 달리 Google Cloud Console에서 다시 찾아와야 할 수 있다.

8. Deploy → 빌드 로그 확인 (Python 3.13 빌드 단계가 제일 오래 걸림, 수 분~수십 분)

## 4. 첫 확인

1. Pod Start 후 로그에서 순서대로 확인:
   - cloudflared 터널 연결 로그 (`config.yml` 방식이면 `[entrypoint] cloudflared:
     config.yml 방식으로 터널 실행`)
   - Cloudflare 쪽 로그(Zero Trust 대시보드에도 연결 상태 표시됨)에 커넥터 연결 확인
   - Streamlit 기동 로그 (`You can now view your Streamlit app...`)
   - STT 모델 로딩 로그에서 CUDA/libcublas 에러가 없는지 (여기가 위 "미검증" 리스크 지점)
2. `https://chefear.store/?key=<ACCESS_GATE_TOKEN>` 접속 → 정상 로딩되는지
3. 실제 마이크 발화 테스트 → WebRTC 연결이 STUN만으로 붙는지, 안 붙으면 TURN 필요.
   기존 `.env`의 `TURN_HOST`(Tailscale 사설 IP)는 승욱님 다른 기기 테스트 전용이라
   면접관 등 외부 방문자에게는 안 통한다 — 필요하면 공개적으로 접근 가능한 TURN(직접
   공인 IP로 coturn을 열거나 Cloudflare Realtime TURN 같은 관리형 서비스)을 새로
   준비해야 한다. 이건 실측 전엔 장담 못 함.

## 5. 평소 운영

- 면접 없을 때: RunPod 콘솔에서 Pod **Stop** (Terminate 아님 — Network Volume은
  유지되고 GPU 과금만 멈춘다, 스토리지 소액만 청구. **Container Disk는 Stop 시
  날아가니 모델 캐시·cloudflared 설정은 반드시 Network Volume 쪽에 둘 것**)
- 면접 전: **Start** 누르면 몇 분 내로 `chefear.store`가 다시 살아난다 (모델 로딩
  때문에 첫 요청은 좀 걸림 — 면접 5분 전에 본인이 한 번 접속해서 워밍업 권장)
- 랜딩페이지·도메인·접근게이트는 그대로라 이 이후로는 위 Start/Stop 외에 아무것도 안
  건드려도 된다

## 6. Pod 자체를 지웠다가 나중에 다시 만들기 (Terminate, Stop이 아님)

Stop과 달리 Terminate는 Container Disk뿐 아니라 **Pod 자체가 사라진다**(GPU 배정
포함) — 이 문서 1~5단계를 사실상 처음부터 다시 밟아야 한다. 단, git 레포/GHCR
이미지/Cloudflare 터널/도메인은 Pod 생명주기와 완전히 분리돼 있어서 아무것도 안
건드려도 된다:

- **git 쪽은 그대로 둔다.** `chefear-team/ChefEar_ai` 레포·`.github/workflows/
  docker-build.yml`·`Dockerfile` 전부 Pod와 무관하게 존재하고, 이미지는 이미
  `ghcr.io/chefear-team/chefear_ai:latest`에 빌드돼 있다 — 새 Pod 만들 때 이
  주소만 다시 입력하면 된다(재빌드도 재커밋도 불필요, 이미 완료된 상태).
- **Network Volume을 Pod와 같이 지우지만 않았다면** cloudflared 터널
  credentials(`/workspace/cloudflared/`)가 그대로 남아있다 — 새 Pod 생성 시
  **같은 Network Volume을 다시 `/workspace`에 연결**하기만 하면 `CLOUDFLARED_CONFIG`
  값도 새로 안 넣어도 된다(entrypoint.sh 기본값이 그 경로를 그대로 봄). RunPod에서
  Pod Terminate 화면에 "연결된 Network Volume도 삭제"류 체크박스가 따로 있는지
  반드시 확인하고, 있으면 체크 해제할 것 — Volume까지 같이 지우면 2단계(터널 credentials
  재이전)부터 다시 해야 한다.
- **RunPod Pod 환경변수 값 자체는 Pod를 지우면 사라진다**(Container Disk와 달리
  이건 애초에 저장 위치가 Pod 설정이라 백업 개념이 없음). 새로 만들기 전에:
  - `SUPABASE_*`/`HF_*`/`ADMIN_*`/`ACCESS_GATE_TOKEN` 등은 로컬 `.env` 파일에
    이미 있으면 그대로 복사해 넣으면 됨(파일 자체가 사라진 게 아니라면).
  - 위 표의 `GOOGLE_OAUTH_*` 4개는 `.env`에 없을 가능성이 높다 — Google Cloud
    Console(OAuth 클라이언트) 쪽에서 `client_id`/`client_secret`은 다시 확인
    가능하지만 `cookie_secret`은 그때 직접 생성한 랜덤값이라 새로 만들면 된다
    (기존 로그인 세션 쿠키만 무효화될 뿐 기능엔 영향 없음).
- 나머지는 1~5단계 그대로: GPU(A40 등 VRAM 40GB+)·이미지 주소·Container
  Disk 30GB+·Network Volume 재연결·위 환경변수 표 채우기·Deploy → 로그 확인.
