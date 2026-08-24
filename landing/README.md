# landing/ — ChefEar 소개 페이지

메인 서비스(`src/app.py`)와 완전히 분리된 정적 소개용 Streamlit 페이지입니다. 코드/의존성을
공유하지 않고 이 폴더 하나만으로 실행됩니다 — HF Spaces 등 별도 배포 없이 로컬에서만
띄우는 용도입니다.

## 실행

```bash
pip install -r landing/requirements.txt
streamlit run landing/app.py
```

## 내용 출처

루트 `README.md`의 팀 정보 / Product Goal / Target User / Core Scenario / Core Features /
Differentiation / Data & Models 섹션을 소개 페이지 톤으로 재구성했습니다. 내용을 바꾸려면
`landing/app.py` 안의 각 섹션(히어로 → Target User → Core Scenario → Service Flow → Core
Features → Differentiation → Data & Models → Team) 마크다운 블록을 직접 수정하면 됩니다.
