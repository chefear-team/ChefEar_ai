# RunPod 배포 (팀 GPU 데스크탑 대체)

기존 "팀 GPU 데스크탑 상시 구동 + Cloudflare Tunnel" 구조를 그대로 RunPod GPU Pod로
옮긴다. **랜딩페이지(Vercel)·접근게이트·도메인(chefear.store)은 전혀 안 건드린다** —
Cloudflare Tunnel의 실행 주체만 팀 데스크탑 → RunPod Pod로 바뀐다.

면접 데모용이라 상시 트래픽이 없다는 전제로 설계했다: 평소엔 Pod를 **Stop**(터미네이트
아님)해서 GPU 과금을 멈추고, 면접 직전에 Start만 누르면 이 문서의 나머지 과정 없이
Dockerfile의 `docker/entrypoint.sh`가 cloudflared+Streamlit을 자동으로 다 띄운다 —
로컬에서 `run_local.sh` 같은 걸 실행할 필요가 없다.

## 0. 이 레포에 이미 준비된 것

- `Dockerfile` — CUDA 12.4 베이스에 Python 3.13(소스 빌드)·cloudflared·앱 의존성까지
  다 구운 이미지. `docs`/`ADR` 성격상 팀 데스크탑(`run_local.sh`)과 최대한 동일 조건으로
  맞췄다 — 근거는 Dockerfile 상단 주석 참고.
- `docker/entrypoint.sh` — 컨테이너 시작 시 cloudflared 터널 실행 → Streamlit 앱 실행을
  자동으로 한다. Pod의 Start/Stop이 곧 이 프로세스들의 on/off다.
- `.dockerignore` — `models/`, `result_test*/`, `_work_backups/` 등 수 GB짜리 로컬 산출물을
  빌드 컨텍스트에서 제외(대부분 `.gitignore`에도 있어 원격 레포엔 원래 없음).
- `.streamlit/config.toml` — `headless=true`, `address=0.0.0.0`, `port=8501` 추가.

**아직 검증 안 된 부분(첫 배포 때 반드시 확인)**: 이 Dockerfile로 실제 빌드/실행을 아직
한 번도 안 해봤다. 특히 (1) Python 3.13 소스 빌드가 이 베이스 이미지에서 그대로
성공하는지, (2) `libcublas.so.12` 문제(run_local.sh 주석 참고)가 CUDA 12.4 베이스에서도
재현되는지는 RunPod 빌드 로그/첫 Start 로그로 직접 확인해야 한다. 실패하면 로그 그대로
가져오면 같이 고친다.

## 1. 이 변경사항을 원격 레포에 올리기 (여기까지만 로컬에서 명령어 입력)

```bash
cd "C:\Users\Wook\Desktop\data\porject\proj1-a"
git add Dockerfile docker/entrypoint.sh .dockerignore .streamlit/config.toml docs/runpod_deploy.md
git commit -m "RunPod 배포용 Dockerfile/entrypoint 추가"
git push origin seunguk
```

이후 과정은 전부 Cloudflare 대시보드 + RunPod 콘솔에서만 진행한다(로컬 스크립트 실행 없음).

## 2. Cloudflare Zero Trust — 터널 토큰 발급

기존에 `cloudflared tunnel create`(CLI, 로컬관리형)로 만든 터널이면 credentials.json이
있을 텐데, RunPod 컨테이너로는 **토큰 방식(원격관리형)**이 파일 전송 없이 더 깔끔하다.

1. https://one.dash.cloudflare.com → **Networks → Tunnels**
2. 기존 chefear 터널이 있으면 그걸 열고, 없으면 **Create a tunnel** → *Cloudflared* 선택 →
   이름(예: `chefear-runpod`)
3. **Install and run connector** 화면에서 나오는 토큰 문자열(`eyJ...` 형태의 긴 문자열)을
   복사해둔다 — 아래 4단계에서 RunPod 환경변수 `CLOUDFLARE_TUNNEL_TOKEN`에 그대로 넣는다.
4. **Public Hostname** 탭에서 라우팅 추가:
   - `chefear.store` → Service: `HTTP` / `localhost:8501`
   - (필요하면) `www.chefear.store` 동일하게 추가
5. 기존 팀 데스크탑에서 돌던 cloudflared는 RunPod 쪽이 정상 확인된 뒤 종료한다. 같은
   터널을 두 군데서 동시에 못 돌리는 게 아니라 안전을 위해서다 — 헷갈릴 수 있으니 순서상
   RunPod 확인 후 데스크탑 걸 끄는 걸 권장.

## 3. RunPod — Pod 생성

1. https://www.runpod.io 가입, 결제수단 등록
2. (선택, 권장) **Storage → Network Volumes**에서 볼륨 생성(예: 20GB) — HF 모델 캐시를
   여기 두면 나중에 GPU 타입을 바꾸거나 Pod를 새로 만들어도 모델을 다시 안 받는다.
3. **Pods → Deploy** → GPU: **A40 (48GB)** 선택
4. 이미지 소스: **GitHub 연동 빌드** 선택 → 이 레포(`minhahamin/cookEar_ai`, `seunguk`
   브랜치) 연결, Dockerfile 경로는 루트의 `Dockerfile` 그대로. (GitHub 계정이 레포
   소유자(홍민하)면 collaborator 초대가 먼저 필요할 수 있다.)
5. Container Disk: 최소 30GB 이상 권장(모델 캐시+torch/CUDA 라이브러리 용량 고려)
6. Network Volume을 만들었으면 마운트 경로 지정 (예: `/workspace`)
7. **Environment Variables**에 아래 값을 채운다 (`.env.example` 목록과 동일, 실제 값은
   Supabase/HF 콘솔·기존 `.env` 파일에서 그대로 가져오면 됨 — 파일 자체를 옮길 필요 없음,
   `orchestration/db.py::load_env()`가 `.env` 파일이 없으면 조용히 넘어가고 시스템
   환경변수를 그대로 쓴다):

   | 변수 | 값 |
   |---|---|
   | `CLOUDFLARE_TUNNEL_TOKEN` | 2단계에서 복사한 토큰 |
   | `SUPABASE_URL` / `SUPABASE_KEY` | 기존 값 |
   | `HF_TOKEN` | 기존 값 |
   | `HF_STT_CT2_REPO` | `kimseunguk/chefear-stt-ct2-int8` (기존 값) |
   | `ACCESS_GATE_TOKEN` | 기존 값 (랜딩페이지 링크와 동일해야 함) |
   | `ADMIN_ACCESS_TOKEN` / `ADMIN_VOICE_THRESHOLD` | 관리자 페이지 쓸 경우 |
   | (선택) `HF_HOME` | Network Volume 마운트 경로 아래(예: `/workspace/hf_cache`)로 지정하면 모델이 볼륨에 캐시됨 |

8. Deploy → 빌드 로그 확인 (Python 3.13 빌드 단계가 제일 오래 걸림, 수 분~수십 분)

## 4. 첫 확인

1. Pod Start 후 로그에서 순서대로 확인:
   - `[entrypoint] cloudflared: 토큰 방식으로 터널 실행`
   - Cloudflare 쪽 로그(Zero Trust 대시보드에도 연결 상태 표시됨)에 커넥터 연결 확인
   - Streamlit 기동 로그 (`You can now view your Streamlit app...`)
   - STT 모델 로딩 로그에서 CUDA/libcublas 에러가 없는지 (여기가 위 "미검증" 리스크 지점)
2. `https://chefear.store/?key=<ACCESS_GATE_TOKEN>` 접속 → 정상 로딩되는지
3. 실제 마이크 발화 테스트 → WebRTC 연결이 STUN만으로 붙는지, 안 붙으면 TURN 필요
   (기존 `.env`의 `TURN_HOST` 계열 변수로 대응 — 팀 데스크탑처럼 coturn을 RunPod
   Pod 안에서 같이 띄우거나, 별도 TURN 서비스를 붙여야 할 수도 있음. 이건 실측 전엔
   장담 못 함)

## 5. 평소 운영

- 면접 없을 때: RunPod 콘솔에서 Pod **Stop** (Terminate 아님 — 컨테이너 디스크는
  유지되고 GPU 과금만 멈춘다, 스토리지 소액만 청구)
- 면접 전: **Start** 누르면 몇 분 내로 `chefear.store`가 다시 살아난다 (모델 로딩
  때문에 첫 요청은 좀 걸림 — 면접 5분 전에 본인이 한 번 접속해서 워밍업 권장)
- 랜딩페이지·도메인·접근게이트는 그대로라 이 이후로는 위 Start/Stop 외에 아무것도 안
  건드려도 된다
