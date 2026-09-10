# landing/ — 소개 페이지

메인 서비스(`src/app.py`)와 코드·의존성을 공유하지 않는 정적 소개용 Streamlit 페이지. 실제 랜딩(`chefear-landingpage.vercel.app`)과 같은 내용이며, 접속 게이트 토큰이 붙은 서비스 링크로 안내한다.

```bash
pip install -r landing/requirements.txt
streamlit run landing/app.py
```

내용을 바꾸려면 `landing/app.py` 안의 섹션(히어로 → Target User → Core Scenario → Service Flow → Core Features → Differentiation → Data & Models → Team) 마크다운 블록을 직접 수정한다. 데이터 수치는 500개 큐레이션 레시피 / 2,950 조리 단계 기준이다.
