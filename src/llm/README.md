# src/llm/ — 담당: 김승욱 (A, 오케스트레이션/통합 주관)

## 이 폴더가 하는 일

로컬 LLM(`LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct`)을 GPU 데스크탑(RTX 5070) 프로세스 안에
`transformers.AutoModelForCausalLM`으로 직접 로드해서, 자유발화에서 요리명을 뽑는 데 쓴다
(`../orchestration/entity_extract_llm.py`가 이 폴더를 얇게 감싼다).

**AGENTS.md 1.5 원칙("서비스 실행 중 외부 LLM API 호출 금지")과 무관하다** — 이 원칙이 막는 건
OpenAI/Anthropic/Gemini/Groq/OpenRouter처럼 인터넷 건너 남의 서버에서 추론이 일어나는 경우다.
여기서는 가중치를 팀 GPU 데스크탑에 직접 올려서 그 프로세스 안에서 추론하므로 완전한 로컬이라
원칙에 걸리지 않는다 — 관련 문서를 다시 확인해보니 로컬 LLM 사용 자체는 이미 허용돼 있었고,
강사님도 로컬 LLM 사용을 추천했다(2026-08-21 팀 확인).

별도 서버(Ollama/FastAPI 등)를 두지 않기로 했다(2026-08-20, Ollama 검토 후 폐기 — 팀이 임의로
프레임워크를 정하지 말고 사용자가 지정한 방식을 따르기로 함).

## 파일별 상태 (확인: 2026-08-21)

| 파일 | 상태 | 역할 |
|---|---|---|
| `infer.py` | 완성 | `load_llm()`(지연 로드+전역 캐시, `tts/infer.py`의 `load_tts_model()`과 동일한 패턴) / `generate_response(prompt)`(그리디 디코딩, `do_sample=False` — 요리명 추출은 매번 같은 답이 나와야 하는 태스크) / `generate_json(prompt) -> dict \| None`(마크다운 코드펜스 자동 제거 후 JSON 파싱, 형식 오류 시 예외 없이 `None`) |

## 알려진 이슈

- **`transformers>=5.0`과 비호환** (2026-08-21 실측) — EXAONE의 원격 코드(`modeling_exaone.py`)가
  `_tied_weights_keys`를 구버전 형식(리스트)으로 정의하는데, `transformers` v5의 tied-weights 처리
  (`modeling_utils.py`의 `get_expanded_tied_weights_keys()`)는 딕셔너리를 기대해서
  `AttributeError`로 로드 자체가 깨진다. 그래서 `MODEL_REVISION`을 v5 마이그레이션 이전 커밋
  (`e949c91dec92095908d34e6b560af77dd0c993f8`, 2024-12-11)으로 고정해뒀다 — 이 리포에 이미 고정된
  `transformers==4.57.3`(`requirements-main.txt`)과 짝을 맞춰야 한다. 새 venv를 팔 때 이 버전을
  벗어나지 않도록 주의할 것.
- `../orchestration/entity_extract_llm.py`가 `extract_dish_name_llm()` 호출을 `app.py`의
  `process_utterance()`에서 아직 `try/except`로 감싸지 않고 있음 — 로드·추론 자체가 실패하면
  지금은 `app.py`까지 예외가 그대로 올라간다(TODO, `docs/specs/llm_dish_name_extract.md` EC-05 참고).

## 진행 방법

- 실행 예시: `docs/specs/llm_dish_name_extract.md`의 "[호출 예시]" 참고
- 로컬 GPU 데스크탑에서 확인하려면 `../../run_local.sh`(계정별 venv를 자동으로 찾아
  `LD_LIBRARY_PATH`까지 잡아준다) 또는 전용 venv(`~/.venvs/chefear`, `requirements-main.txt`
  + `requirements.txt` 설치)에서 직접 `python -c "from llm.infer import load_llm; load_llm()"`
- 2026-08-21 실측: 전용 venv에서 `load_llm()` 단독 로드 약 6.6초(체크포인트 샤드 2개)
- **로컬 디스크 캐시 (2026-08-22, `STT_LOCAL_CACHE_DIR`/`TTS_LOCAL_CACHE_DIR`과 동일 규칙)** —
  EXAONE 가중치는 원래도 `~/.cache/huggingface/hub`(로컬 디스크)에서 읽어서 STT가 겪었던
  네트워크 드라이브 지연(87초)은 없었지만(실측 6초대), `.env`의 `LLM_LOCAL_CACHE_DIR`이
  설정돼 있으면 그 로컬 폴더(HF 캐시 스냅샷 사본, 이 컴퓨터는 `~/models/local_LLM`)를
  repo id 대신 곧장 읽어서 `revision` 고정값 확인차 HF Hub로 나가는 것도 없앤다. 계정별로
  실제 사본이 있어야 하며, 없으면 자동으로 기존 `MODEL_ID`+HF 캐시 경로로 폴백한다.

## 관련 문서

`docs/specs/llm_dish_name_extract.md`(Why/Goal/What/How/AC 전체 스펙), `../orchestration/README.md`,
`tests/test_llm_infer.py`(`generate_json()` mock 유닛테스트).
